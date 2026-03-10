#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib

from metro_pipeline import MetroConfig, load_config, run_pipeline


def load_credentials(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="London Metro 3D Experiment")
    p.add_argument("--config", default="", help="Path to JSON config")
    p.add_argument("--credentials-file", default="", help="Path to local TfL credentials JSON")
    p.add_argument("--phase", default="", choices=["1", "2", "3", "4", "all"], help="Override phase")
    p.add_argument("--mode", default="", choices=["live", "fixture"], help="Override mode")
    p.add_argument("--output-dir", default="", help="Override output directory")
    p.add_argument("--snapshots", type=int, default=None, help="Override snapshots for phase 2 live mode")
    p.add_argument("--snapshot-interval-sec", type=float, default=None, help="Override poll interval seconds")
    p.add_argument("--line-ids", default="", help="Comma list, e.g. victoria,northern,jubilee")
    p.add_argument("--tfl-app-id", default="", help="TfL app_id (optional)")
    p.add_argument("--tfl-app-key", default="", help="TfL app_key (optional)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config) if args.config else MetroConfig()

    if args.phase:
        cfg.phase = args.phase
    if args.mode:
        cfg.mode = args.mode
    if args.output_dir:
        cfg.output_dir = args.output_dir
    if args.snapshots is not None:
        cfg.snapshots = args.snapshots
    if args.snapshot_interval_sec is not None:
        cfg.snapshot_interval_sec = args.snapshot_interval_sec
    if args.line_ids:
        cfg.line_ids = [x.strip() for x in args.line_ids.split(",") if x.strip()]

    creds = {}
    if args.credentials_file:
        creds = load_credentials(pathlib.Path(args.credentials_file))
    else:
        # Prefer local ignored file; fallback to non-local json if user created that.
        for candidate in (
            pathlib.Path("london_metro_3d/tfl_credentials.local.json"),
            pathlib.Path("london_metro_3d/tfl_credentials.json"),
        ):
            creds = load_credentials(candidate)
            if creds:
                break
    if creds:
        cfg.tfl_app_id = str(creds.get("tfl_app_id", cfg.tfl_app_id))
        active_key = str(creds.get("active_key", "primary")).strip().lower()
        if active_key == "secondary":
            key_value = str(creds.get("tfl_app_key_secondary", cfg.tfl_app_key))
        else:
            key_value = str(creds.get("tfl_app_key_primary", cfg.tfl_app_key))
        # In TfL APIM product subscriptions, this key is commonly used as Ocp-Apim-Subscription-Key.
        cfg.tfl_subscription_key = key_value
        cfg.tfl_app_key = key_value

    if args.tfl_app_id:
        cfg.tfl_app_id = args.tfl_app_id
    if args.tfl_app_key:
        cfg.tfl_app_key = args.tfl_app_key

    pathlib.Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    run_pipeline(cfg)
    summary = {
        "output_dir": cfg.output_dir,
        "phase": cfg.phase,
        "mode": cfg.mode,
        "snapshots": cfg.snapshots,
        "snapshot_interval_sec": cfg.snapshot_interval_sec,
        "line_ids": cfg.line_ids,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
