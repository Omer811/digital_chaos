from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from export_sine_surface_stl import resample_indices, smooth2d, write_closed_surface_stl


def select_time_indices(time_values: np.ndarray, count: int, mode: str) -> np.ndarray:
    if count <= 0 or count >= len(time_values):
        return time_values

    if mode == "first":
        return time_values[:count]
    if mode == "last":
        return time_values[-count:]

    # linspace default
    idx = np.linspace(0, len(time_values) - 1, count)
    idx = np.unique(np.round(idx).astype(int))
    if idx[0] != 0:
        idx = np.insert(idx, 0, 0)
    if idx[-1] != len(time_values) - 1:
        idx = np.append(idx, len(time_values) - 1)
    return time_values[idx]


def find_default_csv(run_dir: Path) -> Path:
    candidates = sorted(run_dir.glob("*_steps.csv"))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 0:
        raise FileNotFoundError(f"No *_steps.csv found in {run_dir}")
    raise FileNotFoundError(
        f"Multiple *_steps.csv files found in {run_dir}. Use --csv to select one."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create STL from a run folder with configurable time slice selection"
    )
    parser.add_argument("--run-dir", required=True, help="Run output directory")
    parser.add_argument("--csv", default="", help="Optional explicit CSV path")
    parser.add_argument(
        "--time-slices",
        type=int,
        default=0,
        help="Number of time slices to use (0 = all)",
    )
    parser.add_argument(
        "--time-slice-mode",
        choices=["linspace", "first", "last"],
        default="linspace",
        help="How to pick time slices when downsampling",
    )
    parser.add_argument("--ratio-x", type=float, default=0.5)
    parser.add_argument("--ratio-y", type=float, default=0.5)
    parser.add_argument("--no-smooth", action="store_true")
    parser.add_argument("--out", default="", help="Output STL path")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    csv_path = Path(args.csv) if args.csv else find_default_csv(run_dir)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    required = {"sample_in_cycle", "time_index", "output_norm"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    time_values = np.array(sorted(df["time_index"].unique()), dtype=float)
    chosen_times = select_time_indices(time_values, int(args.time_slices), args.time_slice_mode)
    df = df[df["time_index"].isin(chosen_times)]

    x_all = np.array(sorted(df["sample_in_cycle"].unique()), dtype=float)
    y_all = np.array(sorted(df["time_index"].unique()), dtype=float)
    z_all = (
        df.pivot(index="time_index", columns="sample_in_cycle", values="output_norm")
        .reindex(index=y_all, columns=x_all)
        .to_numpy(dtype=float)
    )

    ix = resample_indices(len(x_all), args.ratio_x)
    iy = resample_indices(len(y_all), args.ratio_y)

    x = x_all[ix]
    y = y_all[iy]
    z = z_all[np.ix_(iy, ix)]
    if not args.no_smooth:
        z = smooth2d(z)

    x_mm = x * 1.0
    y_mm = y * 0.2
    z_mm = z * 40.0

    if args.out:
        out_stl = Path(args.out)
    else:
        out_stl = csv_path.parent / f"{csv_path.stem}_surface_outputonly_{len(y)}slices.stl"

    tris = write_closed_surface_stl(out_stl, x_mm, y_mm, z_mm)
    print(f"csv={csv_path}")
    print(f"stl={out_stl}")
    print(f"time_slices_used={len(y_all)}")
    print(f"grid={len(x)}x{len(y)}")
    print(f"triangles={tris}")
    print(f"size_mb={out_stl.stat().st_size / (1024*1024):.2f}")


if __name__ == "__main__":
    main()
