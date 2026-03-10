#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


def build_payload(stations_df: pd.DataFrame, edges_df: pd.DataFrame, points_df: pd.DataFrame) -> Dict[str, Any]:
    station_lookup = {
        row.station_id: {
            "station_id": row.station_id,
            "station_name": row.station_name,
            "lat": float(row.lat),
            "lon": float(row.lon),
        }
        for row in stations_df.itertuples(index=False)
    }

    edges: List[Dict[str, Any]] = []
    for row in edges_df.itertuples(index=False):
        a = station_lookup.get(row.from_station)
        b = station_lookup.get(row.to_station)
        if not a or not b:
            continue
        edges.append(
            {
                "line_id": row.line_id,
                "from_station": row.from_station,
                "to_station": row.to_station,
                "lon1": a["lon"],
                "lat1": a["lat"],
                "lon2": b["lon"],
                "lat2": b["lat"],
                "weight": int(row.weight) if pd.notna(row.weight) else 1,
            }
        )

    points: List[Dict[str, Any]] = []
    for row in points_df.itertuples(index=False):
        points.append(
            {
                "snapshot_idx": int(row.snapshot_idx),
                "line_id": str(row.line_id),
                "vehicle_id": str(row.vehicle_id),
                "station_id": str(row.station_id),
                "station_name": str(row.station_name),
                "lon": float(row.lon),
                "lat": float(row.lat),
                "time_to_station_sec": None if pd.isna(row.time_to_station_sec) else float(row.time_to_station_sec),
            }
        )

    snapshot_min = min((p["snapshot_idx"] for p in points), default=0)
    snapshot_max = max((p["snapshot_idx"] for p in points), default=0)

    return {
        "meta": {
            "snapshot_min": snapshot_min,
            "snapshot_max": snapshot_max,
            "station_count": len(station_lookup),
            "edge_count": len(edges),
            "point_count": len(points),
        },
        "stations": list(station_lookup.values()),
        "edges": edges,
        "points": points,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build timeline JSON for London metro live UI")
    p.add_argument("--run-dir", required=True, help="Directory containing phase1/phase2 csv outputs")
    p.add_argument("--output", default="", help="Output json path. default: <run-dir>/timeline_data.json")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    out_path = Path(args.output) if args.output else run_dir / "timeline_data.json"

    stations_df = pd.read_csv(run_dir / "phase1_stations.csv")
    edges_df = pd.read_csv(run_dir / "phase1_edges.csv")
    points_df = pd.read_csv(run_dir / "phase2_arrival_points.csv")

    payload = build_payload(stations_df, edges_df, points_df)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload))
    print(str(out_path))


if __name__ == "__main__":
    main()
