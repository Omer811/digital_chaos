from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
import shutil
from typing import Any

import pandas as pd
import plotly.express as px
import serial


class MCP23017Error(RuntimeError):
    pass


def resolve_arduino_cli() -> str:
    cli = shutil.which("arduino-cli")
    if cli:
        return cli
    fallback = Path("/usr/local/bin/arduino-cli")
    if fallback.exists():
        return str(fallback)
    raise MCP23017Error("arduino-cli not found in PATH and /usr/local/bin/arduino-cli missing")


def run_cmd(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MCP23017Error(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def load_config(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise MCP23017Error(f"Config not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def wait_ready(ser: serial.Serial, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "READY":
            return True
    return False


def collect_samples(cfg: dict[str, Any]) -> pd.DataFrame:
    ard = cfg["arduino"]
    mcp = cfg["mcp23017"]

    i2c_addr = int(str(mcp["i2c_address"]), 0)
    req = (
        f"RUN,{int(mcp['sample_count'])},{int(mcp['delay_us'])},"
        f"{int(mcp['progress_every_samples'])},{i2c_addr}\n"
    )

    rows: list[dict[str, int]] = []

    print(
        f"[mcp23017] opening serial {ard['port']} @ {ard['baud_rate']} baud", flush=True
    )
    with serial.Serial(
        ard["port"], int(ard["baud_rate"]), timeout=float(mcp["serial_timeout_seconds"])
    ) as ser:
        time.sleep(2.0)
        ser.reset_input_buffer()

        if wait_ready(ser, float(mcp["handshake_timeout_seconds"])):
            print("[mcp23017] READY received", flush=True)
        else:
            print("[mcp23017] READY timeout, continuing", flush=True)

        print(f"[mcp23017] sending: {req.strip()}", flush=True)
        ser.write(req.encode("ascii"))
        ser.flush()

        got_begin = False
        deadline = time.time() + float(mcp["serial_timeout_seconds"])

        while True:
            if time.time() > deadline:
                raise MCP23017Error("Timed out waiting for MCP23017 stream")

            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith("ERROR"):
                raise MCP23017Error(f"Arduino error: {line}")

            if line.startswith("BEGIN,"):
                got_begin = True
                print(f"[mcp23017] {line}", flush=True)
                continue

            if line.startswith("PROGRESS,"):
                parts = line.split(",")
                if len(parts) == 3:
                    done = int(parts[1])
                    total = int(parts[2])
                    pct = (100.0 * done / total) if total > 0 else 0.0
                    print(f"[mcp23017] progress {done}/{total} ({pct:.1f}%)", flush=True)
                continue

            if line == "END":
                print("[mcp23017] END received", flush=True)
                break

            if line.startswith("DATA,"):
                parts = line.split(",")
                if len(parts) != 4:
                    raise MCP23017Error(f"Malformed DATA line: {line}")
                rows.append(
                    {
                        "sample_index": int(parts[1]),
                        "gpioa": int(parts[2]),
                        "gpiob": int(parts[3]),
                    }
                )
                deadline = time.time() + float(mcp["serial_timeout_seconds"])

        if not got_begin:
            raise MCP23017Error("Did not receive BEGIN")

    if len(rows) != int(mcp["sample_count"]):
        raise MCP23017Error(f"Expected {mcp['sample_count']} samples, got {len(rows)}")

    return pd.DataFrame(rows).sort_values("sample_index").reset_index(drop=True)


def expand_pin_bits(raw_df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"sample_index": raw_df["sample_index"]})

    for bit in range(8):
        out[f"GPA{bit}"] = raw_df["gpioa"].apply(lambda v, b=bit: (int(v) >> b) & 1)
    for bit in range(8):
        out[f"GPB{bit}"] = raw_df["gpiob"].apply(lambda v, b=bit: (int(v) >> b) & 1)

    return out


def lag1_abs_corr(bits_df: pd.DataFrame, pin_cols: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for col in pin_cols:
        c = bits_df[col].iloc[1:].corr(bits_df[col].shift(1).iloc[1:])
        if pd.isna(c):
            result[col] = 1.0
        else:
            result[col] = abs(float(c))
    return result


def correlation_report(bits_df: pd.DataFrame, pin_cols: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    corr_matrix = bits_df[pin_cols].corr().fillna(0.0)
    lag1 = lag1_abs_corr(bits_df, pin_cols)

    abs_no_diag = corr_matrix.abs().copy()
    for p in pin_cols:
        abs_no_diag.loc[p, p] = 0.0

    stacked = abs_no_diag.stack()
    max_pair = stacked.idxmax()
    report = {
        "pin_count": len(pin_cols),
        "sample_count": int(len(bits_df)),
        "lag1_abs_corr_by_pin": lag1,
        "max_lag1_abs_corr": float(max(lag1.values())) if lag1 else 0.0,
        "max_abs_pair_corr": float(stacked.max()) if len(stacked) else 0.0,
        "max_abs_pair": [str(max_pair[0]), str(max_pair[1])],
    }
    return corr_matrix, report


def plot_pin_states(bits_df: pd.DataFrame, pin_cols: list[str], png_path: Path, html_path: Path) -> None:
    z = bits_df[pin_cols].T.values
    fig = px.imshow(
        z,
        labels={"x": "Sample Index", "y": "Pin", "color": "State"},
        x=bits_df["sample_index"],
        y=pin_cols,
        aspect="auto",
        color_continuous_scale=[(0.0, "#0f172a"), (1.0, "#22c55e")],
        title="MCP23017 Floating Pin States Over Time",
    )
    fig.write_image(str(png_path), scale=2, width=1400, height=900)
    fig.write_html(str(html_path), include_plotlyjs="cdn")


def plot_corr_heatmap(corr_matrix: pd.DataFrame, png_path: Path, html_path: Path) -> None:
    fig = px.imshow(
        corr_matrix,
        labels={"x": "Pin", "y": "Pin", "color": "Correlation"},
        x=corr_matrix.columns,
        y=corr_matrix.index,
        zmin=-1,
        zmax=1,
        color_continuous_scale="RdBu",
        title="MCP23017 Pin Correlation Matrix",
    )
    fig.write_image(str(png_path), scale=2, width=1200, height=1000)
    fig.write_html(str(html_path), include_plotlyjs="cdn")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MCP23017 floating pin sampling experiment")
    parser.add_argument("--config", default="mcp23017_config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ard = cfg["arduino"]
    mcp_cfg = cfg["mcp23017"]
    out_cfg = cfg["output"]
    arduino_cli = resolve_arduino_cli()

    if bool(ard.get("upload_before_run", True)):
        print("[mcp23017] compiling sketch", flush=True)
        run_cmd([arduino_cli, "compile", "--fqbn", ard["fqbn"], ard["sketch_path"]])
        print("[mcp23017] uploading sketch", flush=True)
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

    raw_df = collect_samples(cfg)
    bits_df = expand_pin_bits(raw_df)
    all_pin_cols = [c for c in bits_df.columns if c != "sample_index"]
    selected_pins = mcp_cfg.get("selected_pins")
    if selected_pins:
        pin_cols = [p for p in selected_pins if p in all_pin_cols]
        if not pin_cols:
            raise MCP23017Error("selected_pins is set, but none match available MCP pin columns")
        bits_df = bits_df[["sample_index"] + pin_cols]
    else:
        pin_cols = all_pin_cols

    corr_matrix, report = correlation_report(bits_df, pin_cols)

    out_dir = Path(out_cfg["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_csv = out_dir / out_cfg["raw_bytes_csv"]
    bits_csv = out_dir / out_cfg["expanded_bits_csv"]
    corr_csv = out_dir / out_cfg["corr_matrix_csv"]
    report_json = out_dir / out_cfg["corr_report_json"]
    pins_png = out_dir / out_cfg["pins_plot_png"]
    pins_html = out_dir / out_cfg["pins_plot_html"]
    corr_png = out_dir / out_cfg["corr_plot_png"]
    corr_html = out_dir / out_cfg["corr_plot_html"]

    raw_df.to_csv(raw_csv, index=False)
    bits_df.to_csv(bits_csv, index=False)
    corr_matrix.to_csv(corr_csv, index=True)
    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    plot_pin_states(bits_df, pin_cols, pins_png, pins_html)
    plot_corr_heatmap(corr_matrix, corr_png, corr_html)

    print(f"[mcp23017] saved raw bytes: {raw_csv}", flush=True)
    print(f"[mcp23017] saved expanded bits: {bits_csv}", flush=True)
    print(f"[mcp23017] saved correlation matrix: {corr_csv}", flush=True)
    print(f"[mcp23017] saved correlation report: {report_json}", flush=True)
    print(f"[mcp23017] saved pin-state plot: {pins_png}", flush=True)
    print(f"[mcp23017] saved corr heatmap: {corr_png}", flush=True)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
