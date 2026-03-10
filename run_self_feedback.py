from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import serial
from plotly.subplots import make_subplots


class SelfFeedbackError(RuntimeError):
    pass


def run_cmd(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SelfFeedbackError(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise SelfFeedbackError(f"Config not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def wait_ready(ser: serial.Serial, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "READY":
            return True
    return False


def collect_feedback_samples(cfg: dict) -> pd.DataFrame:
    ard = cfg["arduino"]
    fb = cfg["feedback"]

    req = (
        f"RUN,{int(fb['sample_count'])},{int(fb['initial_state'])},"
        f"{int(fb['threshold'])},{int(fb['settle_us'])},{int(fb['progress_every_samples'])}\n"
    )

    rows: list[dict[str, int]] = []

    print(
        "[self-feedback] opening serial "
        f"{ard['port']} @ {ard['baud_rate']} baud",
        flush=True,
    )
    with serial.Serial(
        ard["port"], int(ard["baud_rate"]), timeout=float(fb["serial_timeout_seconds"])
    ) as ser:
        time.sleep(2.0)
        ser.reset_input_buffer()

        if wait_ready(ser, float(fb["handshake_timeout_seconds"])):
            print("[self-feedback] READY received", flush=True)
        else:
            print("[self-feedback] READY timeout, continuing", flush=True)

        print(f"[self-feedback] sending: {req.strip()}", flush=True)
        ser.write(req.encode("ascii"))
        ser.flush()

        got_begin = False
        deadline = time.time() + float(fb["serial_timeout_seconds"])

        while True:
            if time.time() > deadline:
                raise SelfFeedbackError("Timed out waiting for feedback sequence")

            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith("ERROR"):
                raise SelfFeedbackError(f"Arduino error: {line}")

            if line.startswith("BEGIN,"):
                got_begin = True
                print(f"[self-feedback] {line}", flush=True)
                continue

            if line.startswith("PROGRESS,"):
                parts = line.split(",")
                if len(parts) == 3:
                    done = int(parts[1])
                    total = int(parts[2])
                    pct = (100.0 * done / total) if total > 0 else 0.0
                    print(
                        f"[self-feedback] progress {done}/{total} ({pct:.1f}%)",
                        flush=True,
                    )
                continue

            if line == "END":
                print("[self-feedback] END received", flush=True)
                break

            if line.startswith("DATA,"):
                parts = line.split(",")
                if len(parts) != 4:
                    raise SelfFeedbackError(f"Malformed DATA line: {line}")
                rows.append(
                    {
                        "sample_index": int(parts[1]),
                        "emitted_state": int(parts[2]),
                        "read_value": int(parts[3]),
                    }
                )
                deadline = time.time() + float(fb["serial_timeout_seconds"])

        if not got_begin:
            raise SelfFeedbackError("Did not receive BEGIN")

    if len(rows) != int(fb["sample_count"]):
        raise SelfFeedbackError(
            f"Expected {fb['sample_count']} rows, got {len(rows)}"
        )

    return pd.DataFrame(rows).sort_values("sample_index").reset_index(drop=True)


def plot_feedback(df: pd.DataFrame, out_png: Path, out_html: Path) -> None:
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=df["sample_index"],
            y=df["read_value"],
            mode="lines+markers",
            name="read_value (A1)",
            line={"width": 2},
            marker={"size": 5},
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=df["sample_index"],
            y=df["emitted_state"],
            mode="lines+markers",
            name="emitted_state (A0)",
            line={"width": 2, "dash": "dot"},
            marker={"size": 5},
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title="Self-Feedback Sequence: A0 -> A1",
        xaxis_title="Sample Index",
        legend={"orientation": "h", "y": 1.05, "x": 0.0},
    )
    fig.update_yaxes(title_text="Read Value (0..1023)", secondary_y=False)
    fig.update_yaxes(title_text="Emitted State (0/1)", secondary_y=True, range=[-0.1, 1.1])

    fig.write_image(str(out_png), scale=2, width=1400, height=800)
    fig.write_html(str(out_html), include_plotlyjs="cdn")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Arduino self-feedback sampling")
    parser.add_argument("--config", default="self_feedback_config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ard = cfg["arduino"]
    out_cfg = cfg["output"]

    if bool(ard.get("upload_before_run", True)):
        print("[self-feedback] compiling sketch", flush=True)
        run_cmd(["arduino-cli", "compile", "--fqbn", ard["fqbn"], ard["sketch_path"]])
        print("[self-feedback] uploading sketch", flush=True)
        run_cmd(
            [
                "arduino-cli",
                "upload",
                "-p",
                ard["port"],
                "--fqbn",
                ard["fqbn"],
                ard["sketch_path"],
            ]
        )

    df = collect_feedback_samples(cfg)

    out_dir = Path(out_cfg["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / out_cfg["csv"]
    png_path = out_dir / out_cfg["plot_png"]
    html_path = out_dir / out_cfg["plot_html"]

    df.to_csv(csv_path, index=False)
    print(f"[self-feedback] saved CSV: {csv_path}", flush=True)

    plot_feedback(df, png_path, html_path)
    print(f"[self-feedback] saved plot: {png_path}", flush=True)
    print(f"[self-feedback] saved html: {html_path}", flush=True)


if __name__ == "__main__":
    main()
