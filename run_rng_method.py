from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import serial


class RNGRunError(RuntimeError):
    pass


def run_cmd(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RNGRunError(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise RNGRunError(f"Config not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def wait_ready(ser: serial.Serial, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "READY":
            return True
    return False


def collect_bytes(cfg: dict) -> pd.DataFrame:
    ard = cfg["arduino"]
    method = cfg["method"]

    req = f"RUN,{int(method['byte_count'])},{int(method['progress_every_bytes'])}\n"

    rows: list[dict[str, int]] = []

    print(
        f"[{method['name']}] opening serial {ard['port']} @ {ard['baud_rate']} baud",
        flush=True,
    )
    with serial.Serial(
        ard["port"], int(ard["baud_rate"]), timeout=float(method["serial_timeout_seconds"])
    ) as ser:
        time.sleep(2.0)
        ser.reset_input_buffer()

        if wait_ready(ser, float(method["handshake_timeout_seconds"])):
            print(f"[{method['name']}] READY received", flush=True)
        else:
            print(f"[{method['name']}] READY timeout, continuing", flush=True)

        print(f"[{method['name']}] sending: {req.strip()}", flush=True)
        ser.write(req.encode("ascii"))
        ser.flush()

        got_begin = False
        deadline = time.time() + float(method["serial_timeout_seconds"])

        while True:
            if time.time() > deadline:
                raise RNGRunError("Timed out waiting for byte stream")

            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith("ERROR"):
                raise RNGRunError(f"Arduino error: {line}")

            if line.startswith("BEGIN,"):
                got_begin = True
                print(f"[{method['name']}] {line}", flush=True)
                continue

            if line.startswith("PROGRESS,"):
                parts = line.split(",")
                if len(parts) == 3:
                    done = int(parts[1])
                    total = int(parts[2])
                    pct = (100.0 * done / total) if total > 0 else 0.0
                    print(
                        f"[{method['name']}] progress {done}/{total} ({pct:.1f}%)",
                        flush=True,
                    )
                continue

            if line == "END":
                print(f"[{method['name']}] END received", flush=True)
                break

            if line.startswith("DATA,"):
                parts = line.split(",")
                if len(parts) != 3:
                    raise RNGRunError(f"Malformed DATA line: {line}")
                rows.append(
                    {
                        "byte_index": int(parts[1]),
                        "byte_value": int(parts[2]),
                    }
                )
                deadline = time.time() + float(method["serial_timeout_seconds"])

        if not got_begin:
            raise RNGRunError("Did not receive BEGIN")

    if len(rows) != int(method["byte_count"]):
        raise RNGRunError(f"Expected {method['byte_count']} bytes, got {len(rows)}")

    df = pd.DataFrame(rows).sort_values("byte_index").reset_index(drop=True)
    df["bit_ones"] = df["byte_value"].apply(lambda x: bin(int(x) & 0xFF).count("1"))
    return df


def build_report(df: pd.DataFrame, method_name: str) -> dict:
    total_bits = len(df) * 8
    ones = int(df["bit_ones"].sum())
    zeros = total_bits - ones
    mean_byte = float(df["byte_value"].mean()) if len(df) else 0.0
    return {
        "method": method_name,
        "byte_count": int(len(df)),
        "total_bits": int(total_bits),
        "ones": ones,
        "zeros": zeros,
        "ones_ratio": (ones / total_bits) if total_bits else 0.0,
        "mean_byte_value": mean_byte,
    }


def render_plot(df: pd.DataFrame, method_name: str, png_path: Path, html_path: Path) -> None:
    fig = px.line(
        df,
        x="byte_index",
        y="byte_value",
        markers=True,
        title=f"{method_name} output bytes over time",
    )
    fig.update_layout(xaxis_title="Byte Index", yaxis_title="Byte Value (0..255)")
    fig.write_image(str(png_path), scale=2, width=1400, height=800)
    fig.write_html(str(html_path), include_plotlyjs="cdn")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a configured RNG Arduino method")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    ard = cfg["arduino"]
    method = cfg["method"]
    out = cfg["output"]

    if bool(ard.get("upload_before_run", True)):
        print(f"[{method['name']}] compiling sketch", flush=True)
        run_cmd(["arduino-cli", "compile", "--fqbn", ard["fqbn"], ard["sketch_path"]])
        print(f"[{method['name']}] uploading sketch", flush=True)
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

    df = collect_bytes(cfg)

    out_dir = Path(out["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / out["csv"]
    png_path = out_dir / out["plot_png"]
    html_path = out_dir / out["plot_html"]
    report_path = out_dir / out["report_json"]

    df.to_csv(csv_path, index=False)
    report = build_report(df, method["name"])
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    render_plot(df, method["name"], png_path, html_path)

    print(f"[{method['name']}] saved CSV: {csv_path}", flush=True)
    print(f"[{method['name']}] saved report: {report_path}", flush=True)
    print(f"[{method['name']}] saved plot: {png_path}", flush=True)
    print(f"[{method['name']}] saved html: {html_path}", flush=True)


if __name__ == "__main__":
    main()
