from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import serial


class SineFeedbackError(RuntimeError):
    pass


def resolve_arduino_cli() -> str:
    cli = shutil.which("arduino-cli")
    if cli:
        return cli
    fallback = Path("/usr/local/bin/arduino-cli")
    if fallback.exists():
        return str(fallback)
    raise SineFeedbackError("arduino-cli not found in PATH and /usr/local/bin/arduino-cli missing")


def run_cmd(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SineFeedbackError(
            f"Command failed: {' '.join(cmd)}\\nstdout:\\n{result.stdout}\\nstderr:\\n{result.stderr}"
        )


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise SineFeedbackError(f"Config not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def wait_ready(ser: serial.Serial, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "READY":
            return True
    return False


def clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def target_sine_pwm(i: int, cycle_samples: int, periods_per_signal: float = 1.0) -> int:
    if cycle_samples <= 1:
        return 128
    phase_index = i % cycle_samples
    phase = (2.0 * math.pi * periods_per_signal * phase_index) / (cycle_samples - 1)
    normalized = (math.sin(phase) + 1.0) * 0.5
    return clamp_int(int(round(normalized * 255.0)), 0, 255)


def adc_to_pwm(adc: int) -> int:
    return clamp_int(int((adc * 255) / 1023), 0, 255)


def generate_seed_wave(
    cycle_samples: int,
    waveform: str,
    periods_per_signal: float,
    random_noise_seed: int,
) -> list[int]:
    def to_pwm(values: np.ndarray) -> list[int]:
        clipped = np.clip(values, 0.0, 1.0)
        return [clamp_int(int(round(v * 255.0)), 0, 255) for v in clipped]

    mode = waveform.lower()
    x = np.linspace(0.0, 1.0, cycle_samples, endpoint=False)
    periods = max(0.001, periods_per_signal)

    if mode == "sine":
        return [
            target_sine_pwm(i, cycle_samples, periods_per_signal=periods_per_signal)
            for i in range(cycle_samples)
        ]

    if mode == "square":
        phase = (x * periods) % 1.0
        return to_pwm((phase < 0.5).astype(float))

    if mode == "triangle":
        phase = (x * periods) % 1.0
        triangle = 1.0 - np.abs((2.0 * phase) - 1.0)
        return to_pwm(triangle)

    if mode == "sawtooth":
        phase = (x * periods) % 1.0
        return to_pwm(phase)

    if mode == "pulse":
        duty_cycle = 0.2
        phase = (x * periods) % 1.0
        return to_pwm((phase < duty_cycle).astype(float))

    if mode == "chirp":
        f0 = max(0.05, periods * 0.25)
        f1 = max(f0 + 0.05, periods * 2.0)
        phase_cycles = (f0 * x) + (0.5 * (f1 - f0) * x * x)
        chirp = (np.sin(2.0 * math.pi * phase_cycles) + 1.0) * 0.5
        return to_pwm(chirp)

    if mode == "exp_decay":
        carrier = np.sin(2.0 * math.pi * periods * x)
        envelope = np.exp(-4.0 * x)
        decayed = ((carrier + 1.0) * 0.5) * envelope
        return to_pwm(decayed)

    if mode == "random_noise":
        rng = np.random.default_rng(random_noise_seed)
        vals = rng.uniform(0.0, 1.0, size=cycle_samples)
        return to_pwm(vals)

    raise SineFeedbackError(
        "Unsupported seed_waveform='{}'. Expected one of: "
        "sine, square, triangle, sawtooth, pulse, chirp, exp_decay, random_noise".format(waveform)
    )


def read_nonempty_line(ser: serial.Serial, deadline: float) -> str:
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line:
            return line
    raise SineFeedbackError("Timed out waiting for board response")


def read_exact_bytes(ser: serial.Serial, count: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    received = 0
    while received < count:
        if time.time() >= deadline:
            raise SineFeedbackError(
                f"Timed out waiting for binary payload ({received}/{count} bytes)"
            )
        chunk = ser.read(count - received)
        if not chunk:
            continue
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)


def collect_steps(cfg: dict) -> pd.DataFrame:
    ard = cfg["arduino"]
    exp = cfg["experiment"]
    cycle_samples = int(exp.get("sine_samples_per_cycle", exp.get("steps", 1000)))
    cycle_samples = max(2, cycle_samples)
    seed_waveform = str(exp.get("seed_waveform", "sine"))
    periods_per_signal = float(exp.get("periods_per_signal", 1.0))
    random_noise_seed = int(exp.get("random_noise_seed", 42))
    time_slices = int(exp.get("time_slices", max(1, int(exp.get("steps", cycle_samples)) // cycle_samples)))
    time_slices = max(1, time_slices)
    max_samples = int(exp.get("max_samples", time_slices * cycle_samples))
    max_samples = max(1, max_samples)
    stop_when_decay = bool(exp.get("stop_when_decay", False))
    decay_threshold_norm = float(exp.get("decay_threshold_norm", 0.02))
    decay_metric = str(exp.get("decay_metric", "peak_to_peak")).lower()
    min_slices_before_decay_check = max(1, int(exp.get("min_slices_before_decay_check", 1)))
    pwm_pin = int(exp["pwm_pin"])
    analog_pin = int(exp["analog_pin"])
    settle_us = int(exp["settle_us"])
    progress_every = max(1, int(exp["progress_every_steps"]))
    oversample_count = int(exp.get("oversample_count", 16))
    oversample_delay_us = int(exp.get("oversample_delay_us", 50))
    requested_buffer_samples = int(exp.get("buffer_samples", 0))

    rows: list[dict[str, int | None]] = []

    print(
        f"[sine-feedback] opening serial {ard['port']} @ {ard['baud_rate']} baud",
        flush=True,
    )
    with serial.Serial(
        ard["port"], int(ard["baud_rate"]), timeout=float(exp["serial_timeout_seconds"])
    ) as ser:
        time.sleep(2.0)
        ser.reset_input_buffer()

        if wait_ready(ser, float(exp["handshake_timeout_seconds"])):
            print("[sine-feedback] READY received", flush=True)
        else:
            print("[sine-feedback] READY timeout, continuing", flush=True)

        setup_req = f"SETUP,{pwm_pin},{analog_pin}\n"
        print(f"[sine-feedback] sending: {setup_req.strip()}", flush=True)
        ser.write(setup_req.encode("ascii"))
        ser.flush()

        deadline = time.time() + float(exp["serial_timeout_seconds"])
        setup_line = read_nonempty_line(ser, deadline)
        if setup_line != "OK_SETUP":
            raise SineFeedbackError(f"SETUP failed: {setup_line}")
        print("[sine-feedback] setup acknowledged", flush=True)

        ser.write(b"CAPS\n")
        ser.flush()
        deadline = time.time() + float(exp["serial_timeout_seconds"])
        caps_line = read_nonempty_line(ser, deadline)
        if not caps_line.startswith("CAPS,"):
            raise SineFeedbackError(f"CAPS query failed: {caps_line}")
        board_max_buffer = int(caps_line.split(",", 1)[1])
        if board_max_buffer < 1:
            raise SineFeedbackError(f"Board reported invalid max buffer size: {board_max_buffer}")

        if requested_buffer_samples <= 0:
            buffer_samples = board_max_buffer
        else:
            buffer_samples = min(requested_buffer_samples, board_max_buffer)
        buffer_samples = max(1, buffer_samples)
        print(
            "[sine-feedback] buffer size selected: "
            f"{buffer_samples} samples (board max={board_max_buffer}, requested={requested_buffer_samples})",
            flush=True,
        )

        seed_wave = generate_seed_wave(
            cycle_samples=cycle_samples,
            waveform=seed_waveform,
            periods_per_signal=periods_per_signal,
            random_noise_seed=random_noise_seed,
        )
        command_wave = seed_wave[:]
        total_steps = min(time_slices * cycle_samples, max_samples)
        completed = 0
        produced_slices = 0
        stop_reason = "completed_requested_slices"
        print(
            f"[sine-feedback] running waveform-feedback loop: "
            f"{time_slices} slices x {cycle_samples} samples "
            f"(max_samples={max_samples})",
            flush=True,
        )

        for t in range(time_slices):
            next_wave: list[int] = []
            measured_wave_norm: list[float] = []
            slice_sample_count = 0

            s = 0
            while s < cycle_samples:
                if completed >= max_samples:
                    stop_reason = "max_samples_reached"
                    break

                remaining_slice = cycle_samples - s
                remaining_total = max_samples - completed
                chunk_n = min(buffer_samples, remaining_slice, remaining_total)
                command_chunk = command_wave[s : s + chunk_n]

                run_req = f"RUN,{chunk_n},{settle_us},{oversample_count},{oversample_delay_us}\n"
                ser.write(run_req.encode("ascii"))
                ser.flush()

                deadline = time.time() + float(exp["serial_timeout_seconds"])
                ack_line = read_nonempty_line(ser, deadline)
                if ack_line.startswith("ERROR"):
                    raise SineFeedbackError(f"Arduino error before payload: {ack_line}")
                if ack_line != "OK_RUN":
                    raise SineFeedbackError(f"Unexpected RUN ack: {ack_line}")

                ser.write(bytes(command_chunk))
                ser.flush()

                deadline = time.time() + float(exp["serial_timeout_seconds"])
                data_line = read_nonempty_line(ser, deadline)
                if data_line.startswith("ERROR"):
                    raise SineFeedbackError(f"Arduino error during RUN: {data_line}")
                if not data_line.startswith("DATA,"):
                    raise SineFeedbackError(f"Unexpected RUN response header: {data_line}")

                data_count = int(data_line.split(",", 1)[1])
                if data_count != chunk_n:
                    raise SineFeedbackError(
                        f"RUN response count mismatch: expected {chunk_n}, got {data_count}"
                    )

                deadline = time.time() + float(exp["serial_timeout_seconds"])
                payload = read_exact_bytes(ser, 2 * data_count, deadline)
                adc_chunk = np.frombuffer(payload, dtype="<u2")
                if len(adc_chunk) != data_count:
                    raise SineFeedbackError(
                        f"RUN payload size mismatch: expected {data_count}, got {len(adc_chunk)}"
                    )

                for offset in range(data_count):
                    sample_in_cycle = s + offset
                    command_pwm = command_chunk[offset]
                    seed_pwm = seed_wave[sample_in_cycle] if t == 0 else None
                    adc_avg = int(adc_chunk[offset])
                    measured_pwm = adc_to_pwm(adc_avg)
                    measured_wave_norm.append(adc_avg / 1023.0)

                    # Strict feedback mode: next waveform is based only on measured output.
                    next_pwm = measured_pwm
                    next_wave.append(next_pwm)

                    idx = t * cycle_samples + sample_in_cycle
                    rows.append(
                        {
                            "sample_index": idx,
                            "sample_in_cycle": sample_in_cycle,
                            "time_index": t,
                            "seed_pwm": seed_pwm,
                            "command_pwm": command_pwm,
                            "read_adc_avg": adc_avg,
                            "read_adc_min": adc_avg,
                            "read_adc_max": adc_avg,
                            "measured_pwm": measured_pwm,
                            "next_pwm": next_pwm,
                        }
                    )

                    completed += 1
                    slice_sample_count += 1
                    if (completed % progress_every) == 0 or completed == total_steps:
                        pct = 100.0 * completed / total_steps
                        print(
                            f"[sine-feedback] progress {completed}/{total_steps} ({pct:.1f}%)",
                            flush=True,
                        )

                s += data_count

            if slice_sample_count == 0:
                break

            produced_slices += 1

            # Keep feedback waveform continuity only if full slice was collected.
            if slice_sample_count == cycle_samples:
                command_wave = next_wave
            else:
                stop_reason = "max_samples_reached"
                break

            if stop_when_decay and produced_slices >= min_slices_before_decay_check:
                if decay_metric == "std":
                    metric_value = float(np.std(measured_wave_norm))
                    metric_name = "std"
                elif decay_metric == "mean":
                    metric_value = float(np.mean(measured_wave_norm))
                    metric_name = "mean"
                else:
                    metric_value = float(max(measured_wave_norm) - min(measured_wave_norm))
                    metric_name = "peak_to_peak"

                if metric_value <= decay_threshold_norm:
                    stop_reason = f"decay_threshold_reached ({metric_name}={metric_value:.6f})"
                    print(
                        f"[sine-feedback] stop condition met: {stop_reason}",
                        flush=True,
                    )
                    break

        print(
            f"[sine-feedback] completed {completed} samples across {produced_slices} slices "
            f"(reason: {stop_reason})",
            flush=True,
        )

    if len(rows) == 0:
        raise SineFeedbackError("No samples were collected")

    df = pd.DataFrame(rows).sort_values("sample_index").reset_index(drop=True)
    df["input_norm"] = df["command_pwm"] / 255.0
    df["output_norm"] = df["read_adc_avg"] / 1023.0
    return df


def plot_2d(df: pd.DataFrame, png_path: Path, html_path: Path) -> None:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["sample_index"],
            y=df["input_norm"],
            mode="lines+markers",
            name="Input Command",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["sample_index"],
            y=df["output_norm"],
            mode="lines+markers",
            name="Output Readback (A0)",
        )
    )
    fig.update_layout(
        title=f"Sine Feedback Loop ({len(df)} Steps)",
        xaxis_title="Sample Index",
        yaxis_title="Normalized Amplitude",
    )
    fig.write_image(str(png_path), scale=2, width=1400, height=800)
    fig.write_html(str(html_path), include_plotlyjs="cdn")


def plot_3d(df: pd.DataFrame, png_path: Path, html_path: Path, mode: str = "slice_lines") -> None:
    fig = go.Figure()
    if mode == "markers_only":
        fig.add_trace(
            go.Scatter3d(
                x=df["sample_in_cycle"],
                y=df["input_norm"],
                z=df["time_index"],
                mode="markers",
                marker={
                    "size": 2.5,
                    "color": df["sample_in_cycle"],
                    "colorscale": "Blues",
                    "opacity": 0.85,
                },
                name="Input Command",
                legendgroup="input",
                showlegend=True,
            )
        )
        fig.add_trace(
            go.Scatter3d(
                x=df["sample_in_cycle"],
                y=df["output_norm"],
                z=df["time_index"],
                mode="markers",
                marker={
                    "size": 2.5,
                    "color": df["sample_in_cycle"],
                    "colorscale": "Oranges",
                    "opacity": 0.85,
                },
                name="Output (measured)",
                legendgroup="output",
                showlegend=True,
            )
        )
    else:
        for t in sorted(df["time_index"].unique()):
            slice_df = df[df["time_index"] == t]
            fig.add_trace(
                go.Scatter3d(
                    x=slice_df["sample_in_cycle"],
                    y=slice_df["input_norm"],
                    z=slice_df["time_index"],
                    mode="lines",
                    line={"width": 2, "color": "#1d4ed8"},
                    opacity=0.55,
                    name="Input Command",
                    legendgroup="input",
                    showlegend=bool(t == 0),
                )
            )
            fig.add_trace(
                go.Scatter3d(
                    x=slice_df["sample_in_cycle"],
                    y=slice_df["output_norm"],
                    z=slice_df["time_index"],
                    mode="lines",
                    line={"width": 2, "color": "#ea580c"},
                    opacity=0.55,
                    name="Output (measured)",
                    legendgroup="output",
                    showlegend=bool(t == 0),
                )
            )
    fig.update_layout(
        title="Sine Feedback 3D: sample/value/time",
        template="plotly_white",
        legend={
            "x": 0.01,
            "y": 0.99,
            "bgcolor": "rgba(255,255,255,0.75)",
            "groupclick": "togglegroup",
        },
        scene={
            "xaxis_title": "Sample in Signal",
            "yaxis_title": "Sample Value (normalized)",
            "zaxis_title": "Time Index",
            "xaxis": {"backgroundcolor": "#f8fafc", "gridcolor": "#cbd5e1"},
            "yaxis": {"backgroundcolor": "#f8fafc", "gridcolor": "#cbd5e1"},
            "zaxis": {"backgroundcolor": "#f8fafc", "gridcolor": "#cbd5e1"},
        },
    )
    fig.write_image(str(png_path), scale=2, width=1400, height=1000)
    fig.write_html(str(html_path), include_plotlyjs="cdn")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PWM sine feedback experiment")
    parser.add_argument("--config", default="sine_feedback_config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ard = cfg["arduino"]
    out = cfg["output"]
    arduino_cli = resolve_arduino_cli()

    if bool(ard.get("upload_before_run", True)):
        print("[sine-feedback] compiling sketch", flush=True)
        run_cmd([arduino_cli, "compile", "--fqbn", ard["fqbn"], ard["sketch_path"]])
        print("[sine-feedback] uploading sketch", flush=True)
        run_cmd(
            [
                arduino_cli,
                "upload",
                "-p",
                ard["port"],
                "--fqbn",
                ard["fqbn"],
                ard["sketch_path"],
            ]
        )

    df = collect_steps(cfg)

    out_dir = Path(out["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / out["csv"]
    p2_png = out_dir / out["plot_2d_png"]
    p2_html = out_dir / out["plot_2d_html"]
    p3_png = out_dir / out["plot_3d_png"]
    p3_html = out_dir / out["plot_3d_html"]

    df.to_csv(csv_path, index=False)
    plot_2d(df, p2_png, p2_html)
    plot_3d(df, p3_png, p3_html, mode=str(out.get("plot_3d_mode", "slice_lines")))

    stl_enabled = bool(out.get("stl_enabled", True))
    stl_ratio_x = float(out.get("stl_ratio_x", 0.5))
    stl_ratio_y = float(out.get("stl_ratio_y", 0.5))
    stl_file = str(out.get("stl_file", f"{csv_path.stem}_surface_outputonly_medratio.stl"))
    if stl_enabled:
        stl_path = out_dir / stl_file
        exporter = Path(__file__).with_name("export_sine_surface_stl.py")
        if not exporter.exists():
            raise SineFeedbackError(f"Missing STL exporter script: {exporter}")
        run_cmd(
            [
                sys.executable,
                str(exporter),
                "--csv",
                str(csv_path),
                "--ratio-x",
                str(stl_ratio_x),
                "--ratio-y",
                str(stl_ratio_y),
                "--out",
                str(stl_path),
            ]
        )
        print(f"[sine-feedback] saved STL: {stl_path}", flush=True)

    print(f"[sine-feedback] saved CSV: {csv_path}", flush=True)
    print(f"[sine-feedback] saved 2D plot: {p2_png}", flush=True)
    print(f"[sine-feedback] saved 3D plot: {p3_png}", flush=True)


if __name__ == "__main__":
    main()
