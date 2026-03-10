from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import plotly.express as px

from run_rng_method import collect_bytes, load_config, run_cmd


def _prepare_device(cfg: dict) -> None:
    ard = cfg["arduino"]
    method_name = cfg["method"]["name"]
    if bool(ard.get("upload_before_run", True)):
        print(f"[{method_name}] compiling sketch", flush=True)
        run_cmd(["arduino-cli", "compile", "--fqbn", ard["fqbn"], ard["sketch_path"]])
        print(f"[{method_name}] uploading sketch", flush=True)
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


def _capture_triplets(cfg: dict, runs: int) -> pd.DataFrame:
    method_name = cfg["method"]["name"]
    run_frames: list[pd.DataFrame] = []

    for run_idx in range(1, runs + 1):
        print(f"[{method_name}] capture run {run_idx}/{runs}", flush=True)
        df = collect_bytes(cfg)
        run_frames.append(df[["byte_index", "byte_value"]].rename(columns={"byte_value": f"run_{run_idx}"}))

    merged = run_frames[0]
    for frame in run_frames[1:]:
        merged = merged.merge(frame, on="byte_index", how="inner")

    return merged.sort_values("byte_index").reset_index(drop=True)


def _plot_triplets(df: pd.DataFrame, method_name: str, png_path: Path, html_path: Path) -> None:
    fig = px.scatter_3d(
        df,
        x="run_1",
        y="run_2",
        z="run_3",
        color="byte_index",
        color_continuous_scale="Turbo",
        opacity=0.8,
        title=f"{method_name}: 3 captures per time point (3D)",
    )
    fig.update_traces(marker={"size": 4})
    fig.update_layout(
        scene={
            "xaxis_title": "Run 1 Byte",
            "yaxis_title": "Run 2 Byte",
            "zaxis_title": "Run 3 Byte",
        }
    )
    fig.write_image(str(png_path), scale=2, width=1400, height=1000)
    fig.write_html(str(html_path), include_plotlyjs="cdn")


def _write_outputs(cfg: dict, merged: pd.DataFrame, runs: int) -> dict:
    method_name = cfg["method"]["name"]
    out_dir = Path(cfg["output"]["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"{method_name}_triplets.csv"
    png_path = out_dir / f"{method_name}_triplets_3d.png"
    html_path = out_dir / f"{method_name}_triplets_3d.html"
    report_path = out_dir / f"{method_name}_triplets_report.json"

    merged.to_csv(csv_path, index=False)
    _plot_triplets(merged, method_name, png_path, html_path)

    report = {
        "method": method_name,
        "runs": runs,
        "points": int(len(merged)),
        "min_value": int(merged[["run_1", "run_2", "run_3"]].min().min()),
        "max_value": int(merged[["run_1", "run_2", "run_3"]].max().max()),
        "files": {
            "csv": str(csv_path),
            "png": str(png_path),
            "html": str(html_path),
        },
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"[{method_name}] saved triplets CSV: {csv_path}", flush=True)
    print(f"[{method_name}] saved triplets plot: {png_path}", flush=True)
    print(f"[{method_name}] saved triplets html: {html_path}", flush=True)
    print(f"[{method_name}] saved triplets report: {report_path}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture 3 RNG samples per time point and plot 3D")
    parser.add_argument(
        "--configs",
        nargs="+",
        default=["jitter_rng_config.json", "race_rng_config.json"],
        help="List of method config files",
    )
    parser.add_argument("--runs", type=int, default=3, help="Capture repetitions per time point")
    args = parser.parse_args()

    runs = max(3, int(args.runs))
    all_reports: list[dict] = []

    for config_path in args.configs:
        cfg = load_config(config_path)
        method_name = cfg["method"]["name"]
        print(f"[{method_name}] starting triplet pipeline with {runs} runs", flush=True)
        _prepare_device(cfg)
        merged = _capture_triplets(cfg, runs=runs)
        report = _write_outputs(cfg, merged, runs=runs)
        all_reports.append(report)

    print(json.dumps({"triplet_runs": all_reports}, indent=2))


if __name__ == "__main__":
    main()
