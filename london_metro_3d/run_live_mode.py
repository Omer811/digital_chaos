#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import time
from typing import Any, Dict, List

import pandas as pd

try:
    from london_metro_3d.metro_pipeline import (
        MetroConfig,
        TflClient,
        fetch_phase1_network,
        map_arrivals_to_coordinates,
        normalize_arrivals,
    )
except ModuleNotFoundError:
    from metro_pipeline import (  # type: ignore
        MetroConfig,
        TflClient,
        fetch_phase1_network,
        map_arrivals_to_coordinates,
        normalize_arrivals,
    )


DEFAULT_LINE_DEPTHS = {
    "bakerloo": -32.0,
    "central": -40.0,
    "circle": -8.0,
    "district": -10.0,
    "hammersmith-city": -7.0,
    "jubilee": -36.0,
    "metropolitan": -14.0,
    "northern": -44.0,
    "piccadilly": -38.0,
    "victoria": -34.0,
    "waterloo-city": -42.0,
}


def load_credentials_from_default_or(path: str) -> Dict[str, Any]:
    if path:
        p = pathlib.Path(path)
        return json.loads(p.read_text()) if p.exists() else {}

    for candidate in (
        pathlib.Path("london_metro_3d/tfl_credentials.local.json"),
        pathlib.Path("london_metro_3d/tfl_credentials.json"),
    ):
        if candidate.exists():
            return json.loads(candidate.read_text())
    return {}


def make_cfg(args: argparse.Namespace) -> MetroConfig:
    cfg = MetroConfig()
    cfg.mode = "live"
    cfg.phase = "all"
    cfg.output_dir = args.output_dir
    cfg.snapshot_interval_sec = args.interval_sec
    cfg.snapshots = max(1, args.snapshots)
    cfg.request_rate_limit_per_min = args.rate_limit_per_min
    cfg.verbose = True

    cfg.line_ids = []

    creds = load_credentials_from_default_or(args.credentials_file)
    if creds:
        cfg.tfl_app_id = str(creds.get("tfl_app_id", ""))
        active_key = str(creds.get("active_key", "primary")).strip().lower()
        key_value = str(
            creds.get("tfl_app_key_secondary", "")
            if active_key == "secondary"
            else creds.get("tfl_app_key_primary", "")
        )
        cfg.tfl_subscription_key = key_value
        cfg.tfl_app_key = key_value

    if args.tfl_app_id:
        cfg.tfl_app_id = args.tfl_app_id
    if args.tfl_key:
        cfg.tfl_subscription_key = args.tfl_key
        cfg.tfl_app_key = args.tfl_key

    return cfg


def parse_csv_tokens(value: str) -> List[str]:
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def fetch_line_ids_for_modes(client: TflClient, modes: List[str]) -> List[str]:
    line_ids: List[str] = []
    seen = set()
    for mode in modes:
        rows = client.get_json(f"/Line/Mode/{mode}")
        for row in rows:
            lid = row.get("id")
            if not lid or lid in seen:
                continue
            seen.add(lid)
            line_ids.append(lid)
    return line_ids


def build_edge_payload(edges_df: pd.DataFrame, stations_df: pd.DataFrame, line_depths: Dict[str, float]) -> List[Dict[str, Any]]:
    station_map = stations_df.set_index("station_id")
    edges = []
    for row in edges_df.itertuples(index=False):
        if row.from_station not in station_map.index or row.to_station not in station_map.index:
            continue
        a = station_map.loc[row.from_station]
        b = station_map.loc[row.to_station]
        depth = float(line_depths.get(row.line_id, -20.0))
        edges.append(
            {
                "line_id": row.line_id,
                "lon1": float(a.lon),
                "lat1": float(a.lat),
                "z1": depth,
                "lon2": float(b.lon),
                "lat2": float(b.lat),
                "z2": depth,
            }
        )
    return edges


def build_sequence_edge_payload(
    route_payloads: Dict[str, Dict[str, Any]], line_depths: Dict[str, float]
) -> List[Dict[str, Any]]:
    edges: List[Dict[str, Any]] = []
    seen = set()
    for line_id, payload in route_payloads.items():
        depth = float(line_depths.get(line_id, -20.0))
        coord_map: Dict[str, Any] = {}
        for st in payload.get("stations", []):
            sid = st.get("id") or st.get("naptanId")
            if sid and st.get("lon") is not None and st.get("lat") is not None:
                coord_map[sid] = (float(st["lon"]), float(st["lat"]))

        for seq in payload.get("stopPointSequences", []):
            pts = []
            for sp in seq.get("stopPoint", []):
                sid = sp.get("id")
                if not sid:
                    continue
                if sid in coord_map:
                    lon, lat = coord_map[sid]
                elif sp.get("lon") is not None and sp.get("lat") is not None:
                    lon, lat = float(sp["lon"]), float(sp["lat"])
                    coord_map[sid] = (lon, lat)
                else:
                    continue
                pts.append((sid, lon, lat))
            for i in range(len(pts) - 1):
                _, lon1, lat1 = pts[i]
                _, lon2, lat2 = pts[i + 1]
                key = (line_id, round(lon1, 6), round(lat1, 6), round(lon2, 6), round(lat2, 6))
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "line_id": line_id,
                        "lon1": lon1,
                        "lat1": lat1,
                        "z1": depth,
                        "lon2": lon2,
                        "lat2": lat2,
                        "z2": depth,
                    }
                )
    return edges


def build_train_payload(points_df: pd.DataFrame, line_depths: Dict[str, float]) -> List[Dict[str, Any]]:
    trains = []
    if points_df.empty:
        return trains
    for row in points_df.itertuples(index=False):
        depth = float(line_depths.get(str(row.line_id), -20.0))
        trains.append(
            {
                "line_id": str(row.line_id),
                "vehicle_id": str(row.vehicle_id),
                "station_id": str(row.station_id),
                "station_name": str(row.station_name),
                "lon": float(row.lon),
                "lat": float(row.lat),
                "z": depth,
                "time_to_station_sec": None if pd.isna(row.time_to_station_sec) else float(row.time_to_station_sec),
            }
        )
    return trains


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def run_live_mode(cfg: MetroConfig, args: argparse.Namespace) -> None:
    out_dir = pathlib.Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = TflClient(cfg)
    modes = parse_csv_tokens(args.modes) or ["tube"]
    explicit_line_ids = parse_csv_tokens(args.line_ids)
    if explicit_line_ids:
        cfg.line_ids = explicit_line_ids
    else:
        print(f"[LiveMode] Loading line ids for modes={modes}...")
        cfg.line_ids = fetch_line_ids_for_modes(client, modes)
    print(f"[LiveMode] Total lines selected={len(cfg.line_ids)}")

    print("[LiveMode] Loading network graph...")
    stations_df, edges_df, route_payloads = fetch_phase1_network(cfg, client)
    line_depths = dict(DEFAULT_LINE_DEPTHS)

    sequence_edges = build_sequence_edge_payload(route_payloads, line_depths)
    edges_payload = sequence_edges if sequence_edges else build_edge_payload(edges_df, stations_df, line_depths)
    write_json(
        out_dir / "live_network_static.json",
        {
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "modes": modes,
            "line_depths": line_depths,
            "edges": edges_payload,
            "stations": stations_df.to_dict(orient="records"),
        },
    )
    print(f"[LiveMode] Network ready: stations={len(stations_df)} edges={len(edges_payload)}")

    history_path = out_dir / "live_snapshots.jsonl"
    if args.reset_history and history_path.exists():
        history_path.unlink()

    line_set = set(cfg.line_ids)
    for snapshot_idx in range(cfg.snapshots):
        captured_at = dt.datetime.now(dt.timezone.utc)
        print(f"[LiveMode] Snapshot {snapshot_idx + 1}/{cfg.snapshots} @ {captured_at.isoformat()}")
        arrivals_all = []
        mode_counts = {}
        for mode in modes:
            rows = client.get_json(f"/Mode/{mode}/Arrivals")
            mode_counts[mode] = len(rows)
            arrivals_all.extend(rows)
        arrivals_filtered = [a for a in arrivals_all if a.get("lineId") in line_set]

        arrivals_df = normalize_arrivals(arrivals_filtered, snapshot_idx=snapshot_idx, captured_at_utc=captured_at)
        points_df = map_arrivals_to_coordinates(arrivals_df, stations_df)
        trains_payload = build_train_payload(points_df, line_depths)
        unique_vehicles = len({t["vehicle_id"] for t in trains_payload})

        live_payload = {
            "snapshot_idx": snapshot_idx,
            "captured_at_utc": captured_at.isoformat(),
            "modes": modes,
            "line_depths": line_depths,
            "edges": edges_payload,
            "streets": [],
            "trains": trains_payload,
            "meta": {
                "arrivals_all_count": len(arrivals_all),
                "arrivals_filtered_count": len(arrivals_filtered),
                "trains_rendered_count": len(trains_payload),
                "unique_vehicle_count": unique_vehicles,
                "mode_counts": mode_counts,
                "line_count": len(cfg.line_ids),
            },
        }

        write_json(out_dir / "live_state.json", live_payload)
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(live_payload) + "\n")

        print(
            "[LiveMode]   "
            f"all={len(arrivals_all)} filtered={len(arrivals_filtered)} rendered={len(trains_payload)} unique_vehicles={unique_vehicles}"
        )

        if snapshot_idx != cfg.snapshots - 1:
            time.sleep(cfg.snapshot_interval_sec)

    write_json(
        out_dir / "live_session_manifest.json",
        {
            "output_dir": str(out_dir),
            "snapshots": cfg.snapshots,
            "snapshot_interval_sec": cfg.snapshot_interval_sec,
            "modes": modes,
            "line_count": len(cfg.line_ids),
            "history_file": str(history_path),
            "live_state_file": str(out_dir / "live_state.json"),
            "network_file": str(out_dir / "live_network_static.json"),
        },
    )
    print(f"[LiveMode] Complete. Open london_metro_3d/live_network_realtime.html")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Realtime London network 3D mode with snapshot capture")
    p.add_argument("--output-dir", default="output/london_metro_3d/live_realtime", help="Output folder")
    p.add_argument("--snapshots", type=int, default=300, help="Number of snapshots")
    p.add_argument("--interval-sec", type=float, default=2.0, help="Seconds between snapshots")
    p.add_argument("--rate-limit-per-min", type=int, default=450, help="Hard cap requests per minute")
    p.add_argument("--modes", default="tube", help="Comma-separated TfL modes, e.g. tube,dlr,overground,elizabeth-line")
    p.add_argument("--line-ids", default="", help="Optional explicit comma-separated line ids override")
    p.add_argument("--credentials-file", default="", help="Credentials json path")
    p.add_argument("--tfl-app-id", default="", help="Optional app id override")
    p.add_argument("--tfl-key", default="", help="Optional key override")
    p.add_argument("--reset-history", action="store_true", help="Clear previous jsonl history before run")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = make_cfg(args)
    run_live_mode(cfg, args)


if __name__ == "__main__":
    main()
