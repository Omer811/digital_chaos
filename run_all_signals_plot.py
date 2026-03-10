from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all seed waveforms with fixed sampling settings.")
    parser.add_argument("--output-dir", default="", help="Optional output root directory")
    parser.add_argument("--tag", default="", help="Optional tag prefix")
    parser.add_argument("--port", default="/dev/cu.usbmodem1201")
    parser.add_argument("--fqbn", default="arduino:avr:uno")
    parser.add_argument("--sketch-path", default="arduino/sine_feedback")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--baud-rate", type=int, default=115200)
    parser.add_argument("--buffer-samples", type=int, default=0, help="0 = auto/board max")
    args = parser.parse_args()

    now_tag = datetime.now().strftime("run_%Y_%m_%d_%H%M%S")
    tag = args.tag or f"all_signals_{now_tag}"
    output_dir = Path(args.output_dir) if args.output_dir else Path("output/sine_feedback") / tag

    cmd = [
        "python3",
        "run_feedback_pipeline.py",
        "--all-seed-waveforms",
        "--samples-per-slice",
        "200",
        "--time-slices",
        "2000",
        "--periods-per-signal",
        "1",
        "--output-dir",
        str(output_dir),
        "--tag",
        tag,
        "--port",
        args.port,
        "--fqbn",
        args.fqbn,
        "--sketch-path",
        args.sketch_path,
        "--baud-rate",
        str(args.baud_rate),
        "--buffer-samples",
        str(args.buffer_samples),
    ]
    if args.no_upload:
        cmd.append("--no-upload")

    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
