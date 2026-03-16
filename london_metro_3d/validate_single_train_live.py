#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect and validate single-train live motion")
    p.add_argument("--line-id", default="victoria")
    p.add_argument("--snapshots", type=int, default=30)
    p.add_argument("--interval-sec", type=float, default=1.5)
    p.add_argument("--output-dir", default="output/london_metro_3d/live_debug_single_train_test")
    p.add_argument("--lookahead-frames", type=int, default=10)
    p.add_argument("--backward-tol", type=float, default=0.04, help="Allowed backward projection delta")
    p.add_argument("--jump-threshold-m", type=float, default=3500.0)
    p.add_argument("--max-backward-events", type=int, default=0)
    p.add_argument("--max-jump-events", type=int, default=1)
    p.add_argument("--interp-ms", type=float, default=1400.0)
    p.add_argument("--fps", type=float, default=60.0)
    p.add_argument("--ui-backward-tol", type=float, default=0.0015)
    p.add_argument("--max-ui-backward-events", type=int, default=0)
    p.add_argument("--max-ui-flip-events", type=int, default=0)
    p.add_argument("--max-ui-hop-events", type=int, default=0)
    p.add_argument("--credentials-file", default="")
    p.add_argument("--vehicle-id", default="")
    return p.parse_args()


def norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def station_lookup(frame: dict) -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}
    for st in frame.get("stations", []) or []:
        name = norm(str(st.get("station_name") or ""))
        if not name:
            continue
        try:
            out[name] = (float(st["lon"]), float(st["lat"]))
        except Exception:
            continue
    return out


def project_t(sample: dict, lookup: Dict[str, Tuple[float, float]]) -> Optional[float]:
    frm = norm(str(sample.get("segment_from") or ""))
    to = norm(str(sample.get("segment_to") or ""))
    if not frm or not to or frm == to:
        return None
    if frm not in lookup or to not in lookup:
        return None
    ax, ay = lookup[frm]
    bx, by = lookup[to]
    vx, vy = bx - ax, by - ay
    vv = vx * vx + vy * vy
    if vv <= 1e-12:
        return None
    sx, sy = float(sample.get("lon")), float(sample.get("lat"))
    t = ((sx - ax) * vx + (sy - ay) * vy) / vv
    return max(0.0, min(1.0, t))


def haversine_m(a_lon: float, a_lat: float, b_lon: float, b_lat: float) -> float:
    r = 6371000.0
    p1 = math.radians(a_lat)
    p2 = math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(max(0.0, h)))


def load_frames(path: pathlib.Path) -> List[dict]:
    frames: List[dict] = []
    if not path.exists():
        return frames
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            frames.append(json.loads(line))
        except Exception:
            continue
    return frames


def analyze(frames: List[dict], backward_tol: float, jump_threshold_m: float) -> dict:
    samples: List[Tuple[dict, dict]] = []
    for fr in frames:
        smp = fr.get("sample")
        if not smp:
            continue
        samples.append((fr, smp))

    backward_events = 0
    jump_events = 0
    same_segment_steps = 0
    measured_steps = 0

    prev: Optional[Tuple[dict, dict]] = None
    for cur in samples:
        if prev is None:
            prev = cur
            continue
        prev_fr, prev_s = prev
        cur_fr, cur_s = cur

        same_seg = (
            str(prev_s.get("segment_from") or "") == str(cur_s.get("segment_from") or "")
            and str(prev_s.get("segment_to") or "") == str(cur_s.get("segment_to") or "")
            and str(prev_s.get("segment_from") or "") != ""
        )

        measured_steps += 1
        if same_seg:
            same_segment_steps += 1
            lk_prev = station_lookup(prev_fr)
            lk_cur = station_lookup(cur_fr)
            t1 = project_t(prev_s, lk_prev)
            t2 = project_t(cur_s, lk_cur)
            if t1 is not None and t2 is not None and (t2 + backward_tol) < t1:
                backward_events += 1

            try:
                d = haversine_m(
                    float(prev_s.get("lon")), float(prev_s.get("lat")),
                    float(cur_s.get("lon")), float(cur_s.get("lat")),
                )
                if d > jump_threshold_m:
                    jump_events += 1
            except Exception:
                pass

        prev = cur

    return {
        "frame_count": len(frames),
        "sample_count": len(samples),
        "measured_steps": measured_steps,
        "same_segment_steps": same_segment_steps,
        "backward_events": backward_events,
        "jump_events": jump_events,
        "backward_ratio": (backward_events / same_segment_steps) if same_segment_steps else 0.0,
        "jump_ratio": (jump_events / same_segment_steps) if same_segment_steps else 0.0,
    }


def replay_ui_analyze(
    frames: List[dict],
    interp_ms: float,
    fps: float,
    backward_tol: float,
) -> dict:
    samples: List[Tuple[dict, dict]] = []
    for fr in frames:
        smp = fr.get("sample")
        if smp:
            samples.append((fr, smp))

    if len(samples) < 2:
        return {
            "ui_render_steps": 0,
            "ui_backward_events": 0,
            "ui_flip_events": 0,
            "ui_hop_events": 0,
            "ui_backward_ratio": 0.0,
            "ui_flip_ratio": 0.0,
            "ui_hop_ratio": 0.0,
        }

    steps_per_segment = max(2, int(round(max(1e-3, interp_ms) / (1000.0 / max(1.0, fps)))))
    ui_render_steps = 0
    ui_backward_events = 0
    ui_flip_events = 0
    ui_hop_events = 0
    same_dir_steps = 0

    last_dir_key: Optional[str] = None
    last_pair_key: Optional[str] = None
    last_t: Optional[float] = None

    for i in range(len(samples) - 1):
        prev_fr, prev_s = samples[i]
        cur_fr, cur_s = samples[i + 1]
        lk = station_lookup(cur_fr)
        for k in range(1, steps_per_segment + 1):
            a = k / steps_per_segment
            try:
                lon = float(prev_s.get("lon")) + (float(cur_s.get("lon")) - float(prev_s.get("lon"))) * a
                lat = float(prev_s.get("lat")) + (float(cur_s.get("lat")) - float(prev_s.get("lat"))) * a
            except Exception:
                continue

            frame_like = dict(cur_s)
            frame_like["lon"] = lon
            frame_like["lat"] = lat

            frm = norm(str(frame_like.get("segment_from") or ""))
            to = norm(str(frame_like.get("segment_to") or ""))
            dir_key = f"{frm}->{to}" if frm and to and frm != to else ""
            pair_key = "||".join(sorted([frm, to])) if frm and to and frm != to else ""

            t = project_t(frame_like, lk)
            if t is None:
                ui_render_steps += 1
                continue

            if last_dir_key == dir_key and last_t is not None:
                same_dir_steps += 1
                if t + backward_tol < last_t:
                    ui_backward_events += 1

            if last_pair_key == pair_key and last_dir_key and dir_key and last_dir_key != dir_key and last_t is not None:
                if 0.08 < last_t < 0.92:
                    ui_flip_events += 1
            elif last_pair_key and pair_key and last_pair_key != pair_key and last_t is not None:
                if 0.12 < last_t < 0.88:
                    ui_hop_events += 1

            last_dir_key = dir_key or last_dir_key
            last_pair_key = pair_key or last_pair_key
            last_t = t
            ui_render_steps += 1

    return {
        "ui_render_steps": ui_render_steps,
        "ui_backward_events": ui_backward_events,
        "ui_flip_events": ui_flip_events,
        "ui_hop_events": ui_hop_events,
        "ui_backward_ratio": (ui_backward_events / same_dir_steps) if same_dir_steps else 0.0,
        "ui_flip_ratio": (ui_flip_events / ui_render_steps) if ui_render_steps else 0.0,
        "ui_hop_ratio": (ui_hop_events / ui_render_steps) if ui_render_steps else 0.0,
    }


def run_collection(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        "london_metro_3d/run_live_debug_single_train.py",
        "--line-id", args.line_id,
        "--snapshots", str(max(3, int(args.snapshots))),
        "--interval-sec", str(max(0.2, float(args.interval_sec))),
        "--output-dir", args.output_dir,
    ]
    if args.credentials_file:
        cmd += ["--credentials-file", args.credentials_file]
    if args.vehicle_id:
        cmd += ["--vehicle-id", args.vehicle_id]

    print("[LiveTest] Running collector:")
    print("[LiveTest]   " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    out_dir = pathlib.Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_collection(args)

    history = out_dir / "debug_snapshots.jsonl"
    frames = load_frames(history)
    report = analyze(frames, float(args.backward_tol), float(args.jump_threshold_m))
    ui_report = replay_ui_analyze(
        frames=frames,
        interp_ms=float(args.interp_ms),
        fps=float(args.fps),
        backward_tol=float(args.ui_backward_tol),
    )
    report.update(ui_report)

    ok = (
        report["backward_events"] <= int(args.max_backward_events)
        and report["jump_events"] <= int(args.max_jump_events)
        and report["ui_backward_events"] <= int(args.max_ui_backward_events)
        and report["ui_flip_events"] <= int(args.max_ui_flip_events)
        and report["ui_hop_events"] <= int(args.max_ui_hop_events)
    )
    report["pass"] = bool(ok)

    report_path = out_dir / "live_validation_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"[LiveTest] report -> {report_path}")
    print(json.dumps(report, indent=2))

    if not ok:
        print("[LiveTest] FAIL: motion criteria exceeded", file=sys.stderr)
        return 1
    print("[LiveTest] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
