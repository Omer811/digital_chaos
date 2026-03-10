from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def resample_indices(n: int, ratio: float) -> np.ndarray:
    ratio = max(0.01, min(1.0, ratio))
    m = max(2, int(round(n * ratio)))
    idx = np.linspace(0, n - 1, m)
    idx = np.unique(np.round(idx).astype(int))
    if idx[0] != 0:
        idx = np.insert(idx, 0, 0)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    return idx


def smooth2d(z: np.ndarray) -> np.ndarray:
    k = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=float)
    k /= k.sum()
    zp = np.pad(z, ((1, 1), (1, 1)), mode="edge")
    zs = np.zeros_like(z)
    for i in range(z.shape[0]):
        for j in range(z.shape[1]):
            zs[i, j] = np.sum(zp[i : i + 3, j : j + 3] * k)
    return zs


def normal(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> np.ndarray:
    n = np.cross(p2 - p1, p3 - p1)
    norm = np.linalg.norm(n)
    if norm == 0:
        return np.array([0.0, 0.0, 0.0])
    return n / norm


def write_closed_surface_stl(out_stl: Path, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> int:
    triangles: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    ny, nx = z.shape

    for iy in range(ny - 1):
        for ix in range(nx - 1):
            p00 = np.array([x[ix], y[iy], z[iy, ix]])
            p10 = np.array([x[ix + 1], y[iy], z[iy, ix + 1]])
            p01 = np.array([x[ix], y[iy + 1], z[iy + 1, ix]])
            p11 = np.array([x[ix + 1], y[iy + 1], z[iy + 1, ix + 1]])
            triangles.append((p00, p10, p11))
            triangles.append((p00, p11, p01))

    base_z = -1.5
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            p00 = np.array([x[ix], y[iy], base_z])
            p10 = np.array([x[ix + 1], y[iy], base_z])
            p01 = np.array([x[ix], y[iy + 1], base_z])
            p11 = np.array([x[ix + 1], y[iy + 1], base_z])
            triangles.append((p00, p11, p10))
            triangles.append((p00, p01, p11))

    def add_wall(a_top: np.ndarray, b_top: np.ndarray, a_bot: np.ndarray, b_bot: np.ndarray) -> None:
        triangles.append((a_bot, b_bot, b_top))
        triangles.append((a_bot, b_top, a_top))

    for ix in range(nx - 1):
        top_a = np.array([x[ix], y[0], z[0, ix]])
        top_b = np.array([x[ix + 1], y[0], z[0, ix + 1]])
        bot_a = np.array([x[ix], y[0], base_z])
        bot_b = np.array([x[ix + 1], y[0], base_z])
        add_wall(top_a, top_b, bot_a, bot_b)

        top_a = np.array([x[ix], y[-1], z[-1, ix]])
        top_b = np.array([x[ix + 1], y[-1], z[-1, ix + 1]])
        bot_a = np.array([x[ix], y[-1], base_z])
        bot_b = np.array([x[ix + 1], y[-1], base_z])
        add_wall(top_b, top_a, bot_b, bot_a)

    for iy in range(ny - 1):
        top_a = np.array([x[0], y[iy], z[iy, 0]])
        top_b = np.array([x[0], y[iy + 1], z[iy + 1, 0]])
        bot_a = np.array([x[0], y[iy], base_z])
        bot_b = np.array([x[0], y[iy + 1], base_z])
        add_wall(top_b, top_a, bot_b, bot_a)

        top_a = np.array([x[-1], y[iy], z[iy, -1]])
        top_b = np.array([x[-1], y[iy + 1], z[iy + 1, -1]])
        bot_a = np.array([x[-1], y[iy], base_z])
        bot_b = np.array([x[-1], y[iy + 1], base_z])
        add_wall(top_a, top_b, bot_a, bot_b)

    with out_stl.open("w", encoding="ascii") as f:
        f.write("solid sine_feedback_surface\n")
        for p1, p2, p3 in triangles:
            n = normal(p1, p2, p3)
            f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
            f.write("    outer loop\n")
            f.write(f"      vertex {p1[0]:.6e} {p1[1]:.6e} {p1[2]:.6e}\n")
            f.write(f"      vertex {p2[0]:.6e} {p2[1]:.6e} {p2[2]:.6e}\n")
            f.write(f"      vertex {p3[0]:.6e} {p3[1]:.6e} {p3[2]:.6e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write("endsolid sine_feedback_surface\n")

    return len(triangles)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export output_norm surface CSV to STL")
    parser.add_argument("--csv", required=True, help="Path to sine feedback CSV")
    parser.add_argument("--ratio-x", type=float, default=0.5, help="Subsample ratio along sample axis")
    parser.add_argument("--ratio-y", type=float, default=0.5, help="Subsample ratio along time axis")
    parser.add_argument("--no-smooth", action="store_true", help="Disable smoothing")
    parser.add_argument("--out", default="", help="Output STL path")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    required = {"sample_in_cycle", "time_index", "output_norm"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

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
        stem = csv_path.stem
        out_stl = csv_path.parent / f"{stem}_surface_outputonly_medratio.stl"

    tris = write_closed_surface_stl(out_stl, x_mm, y_mm, z_mm)
    print(f"stl={out_stl}")
    print(f"grid={len(x)}x{len(y)}")
    print(f"triangles={tris}")
    print(f"size_mb={out_stl.stat().st_size / (1024*1024):.2f}")


if __name__ == "__main__":
    main()
