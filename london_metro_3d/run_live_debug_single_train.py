#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    from london_metro_3d.metro_pipeline import (
        MetroConfig,
        TflClient,
        fetch_phase1_network,
        map_arrivals_to_coordinates,
        normalize_arrivals,
    )
    from london_metro_3d.run_live_mode import build_sequence_edge_payload
    from london_metro_3d.live_positioning import (
        build_segment_seconds_from_timetable,
        build_station_lookup,
        choose_vehicle_id_from_arrivals,
        derive_vehicle_position_from_arrivals,
        resolve_station_fragment,
    )
except ModuleNotFoundError:
    from metro_pipeline import (  # type: ignore
        MetroConfig,
        TflClient,
        fetch_phase1_network,
        map_arrivals_to_coordinates,
        normalize_arrivals,
    )
    from run_live_mode import build_sequence_edge_payload  # type: ignore
    from live_positioning import (  # type: ignore
        build_segment_seconds_from_timetable,
        build_station_lookup,
        choose_vehicle_id_from_arrivals,
        derive_vehicle_position_from_arrivals,
        resolve_station_fragment,
    )


LINE_DEPTHS = {
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
    "dlr": -12.0,
    "elizabeth": -24.0,
}


@dataclass
class DebugConfig:
    line_id: str
    snapshots: int
    interval_sec: float
    output_dir: str
    credentials_file: str
    tfl_app_id: str
    tfl_key: str
    vehicle_id: str
    rate_limit_per_min: int
    ema_alpha: float
    median_window: int
    vote_window: int
    strict_destination: bool


def parse_args() -> DebugConfig:
    p = argparse.ArgumentParser(description="Single-line single-train live debug collector")
    p.add_argument("--line-id", default="victoria")
    p.add_argument("--snapshots", type=int, default=120)
    p.add_argument("--interval-sec", type=float, default=3.0)
    p.add_argument("--output-dir", default="output/london_metro_3d/live_debug_single_train")
    p.add_argument("--credentials-file", default="")
    p.add_argument("--tfl-app-id", default="")
    p.add_argument("--tfl-key", default="")
    p.add_argument("--vehicle-id", default="", help="Optional fixed vehicle id")
    p.add_argument("--rate-limit-per-min", type=int, default=450)
    p.add_argument("--ema-alpha", type=float, default=0.35, help="EMA smoothing factor on segment progress [0..1]")
    p.add_argument("--median-window", type=int, default=5, help="Window size for median filter on progress")
    p.add_argument("--vote-window", type=int, default=5, help="Window size for segment direction voting")
    p.add_argument("--strict-destination", dest="strict_destination", action="store_true", default=True)
    p.add_argument("--no-strict-destination", dest="strict_destination", action="store_false")
    a = p.parse_args()
    return DebugConfig(
        line_id=a.line_id.strip(),
        snapshots=max(1, a.snapshots),
        interval_sec=max(0.2, a.interval_sec),
        output_dir=a.output_dir,
        credentials_file=a.credentials_file,
        tfl_app_id=a.tfl_app_id,
        tfl_key=a.tfl_key,
        vehicle_id=a.vehicle_id.strip(),
        rate_limit_per_min=max(30, a.rate_limit_per_min),
        ema_alpha=max(0.0, min(1.0, float(a.ema_alpha))),
        median_window=max(1, int(a.median_window)),
        vote_window=max(1, int(a.vote_window)),
        strict_destination=bool(a.strict_destination),
    )


def load_credentials(path: str) -> Dict[str, Any]:
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


def build_cfg(dc: DebugConfig) -> MetroConfig:
    cfg = MetroConfig()
    cfg.mode = "live"
    cfg.phase = "all"
    cfg.line_ids = [dc.line_id]
    cfg.snapshots = dc.snapshots
    cfg.snapshot_interval_sec = dc.interval_sec
    cfg.request_rate_limit_per_min = dc.rate_limit_per_min
    cfg.verbose = True

    creds = load_credentials(dc.credentials_file)
    if creds:
        cfg.tfl_app_id = str(creds.get("tfl_app_id", ""))
        active = str(creds.get("active_key", "primary")).strip().lower()
        key = str(creds.get("tfl_app_key_secondary", "") if active == "secondary" else creds.get("tfl_app_key_primary", ""))
        cfg.tfl_subscription_key = key
        cfg.tfl_app_key = key

    if dc.tfl_app_id:
        cfg.tfl_app_id = dc.tfl_app_id
    if dc.tfl_key:
        cfg.tfl_subscription_key = dc.tfl_key
        cfg.tfl_app_key = dc.tfl_key

    return cfg


def select_primary_prediction(points_df: pd.DataFrame) -> pd.DataFrame:
    if points_df.empty:
        return points_df.copy()
    df = points_df.copy()
    if "time_to_station_sec" in df.columns:
        df["_tts_rank"] = df["time_to_station_sec"].fillna(1e12)
        df = df.sort_values(["vehicle_id", "_tts_rank", "snapshot_idx"], ascending=[True, True, True])
        out = df.groupby("vehicle_id", as_index=False).first()
        return out.drop(columns=["_tts_rank"], errors="ignore")
    return df.groupby("vehicle_id", as_index=False).first()


def _interp_between_point(
    from_name: str,
    to_name: str,
    tts_to_to_station: float,
    station_lookup: Dict[str, Dict[str, Any]],
    segment_seconds: Dict[tuple, float],
    default_seg_sec: float = 180.0,
) -> Optional[Dict[str, float]]:
    a = resolve_station_fragment(from_name, station_lookup)
    b = resolve_station_fragment(to_name, station_lookup)
    if not a or not b:
        return None
    seg_t = float(segment_seconds.get((a["station_id"], b["station_id"]), default_seg_sec))
    alpha = max(0.0, min(1.0, 1.0 - (float(tts_to_to_station) / max(1e-6, seg_t))))
    return {
        "lon": float(a["lon"] + (b["lon"] - a["lon"]) * alpha),
        "lat": float(a["lat"] + (b["lat"] - a["lat"]) * alpha),
    }


def _project_t_on_segment(
    sample: Dict[str, Any],
    station_lookup: Dict[str, Dict[str, Any]],
) -> Optional[float]:
    frm = str(sample.get("segment_from") or "")
    to = str(sample.get("segment_to") or "")
    if not frm or not to or frm == to:
        return None
    a = resolve_station_fragment(frm, station_lookup)
    b = resolve_station_fragment(to, station_lookup)
    if not a or not b:
        return None
    ax = float(a["lon"])
    ay = float(a["lat"])
    bx = float(b["lon"])
    by = float(b["lat"])
    vx = bx - ax
    vy = by - ay
    vv = vx * vx + vy * vy
    if vv <= 1e-12:
        return None
    sx = float(sample.get("lon"))
    sy = float(sample.get("lat"))
    t = ((sx - ax) * vx + (sy - ay) * vy) / vv
    return max(0.0, min(1.0, t))


def _segment_key(sample: Dict[str, Any]) -> Optional[str]:
    frm = str(sample.get("segment_from") or "").strip()
    to = str(sample.get("segment_to") or "").strip()
    if not frm or not to or frm == to:
        return None
    return f"{frm}->{to}"


def _extract_route_sequences(route_payload: Dict[str, Any]) -> List[List[str]]:
    seqs: List[List[str]] = []
    for seq in route_payload.get("stopPointSequences", []) or []:
        ids = [str(sp.get("id")) for sp in seq.get("stopPoint", []) if sp.get("id")]
        if len(ids) >= 2:
            seqs.append(ids)
    return seqs


def _station_id_from_name(name: str, station_lookup: Dict[str, Dict[str, Any]]) -> Optional[str]:
    st = resolve_station_fragment(name, station_lookup)
    if not st:
        return None
    sid = str(st.get("station_id") or "")
    return sid or None


def _segments_share_endpoint(prev_sample: Dict[str, Any], cur_sample: Dict[str, Any]) -> bool:
    p1 = str(prev_sample.get("segment_from") or "")
    p2 = str(prev_sample.get("segment_to") or "")
    c1 = str(cur_sample.get("segment_from") or "")
    c2 = str(cur_sample.get("segment_to") or "")
    if not p1 or not p2 or not c1 or not c2:
        return False
    prev_set = {p1, p2}
    cur_set = {c1, c2}
    return len(prev_set.intersection(cur_set)) > 0


def _is_segment_toward_destination(
    from_name: str,
    to_name: str,
    destination_name: str,
    station_lookup: Dict[str, Dict[str, Any]],
    route_sequences: List[List[str]],
) -> Optional[bool]:
    sid_from = _station_id_from_name(from_name, station_lookup)
    sid_to = _station_id_from_name(to_name, station_lookup)
    sid_dst = _station_id_from_name(destination_name, station_lookup)
    if not sid_from or not sid_to or not sid_dst:
        return None

    votes: List[bool] = []
    for seq in route_sequences:
        if sid_from not in seq or sid_to not in seq or sid_dst not in seq:
            continue
        i_from = seq.index(sid_from)
        i_to = seq.index(sid_to)
        i_dst = seq.index(sid_dst)
        # Allowed only if this edge step moves closer (or equal) to destination index.
        votes.append(abs(i_dst - i_to) <= abs(i_dst - i_from))
    if not votes:
        return None
    return votes.count(True) >= votes.count(False)


def _best_vehicle_row_by_tts(vehicle_rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_t = float("inf")
    for row in vehicle_rows:
        try:
            t = float(row.get("timeToStation"))
        except (TypeError, ValueError):
            continue
        if t < best_t:
            best_t = t
            best = row
    return best


def _interp_point_for_t(
    from_name: str,
    to_name: str,
    t: float,
    station_lookup: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, float]]:
    a = resolve_station_fragment(from_name, station_lookup)
    b = resolve_station_fragment(to_name, station_lookup)
    if not a or not b:
        return None
    tt = max(0.0, min(1.0, float(t)))
    return {
        "lon": float(a["lon"] + (b["lon"] - a["lon"]) * tt),
        "lat": float(a["lat"] + (b["lat"] - a["lat"]) * tt),
    }


def _dominant_segment_key(history_samples: List[Dict[str, Any]], vote_window: int) -> Optional[str]:
    if not history_samples:
        return None
    keys = [_segment_key(s) for s in history_samples[-vote_window:]]
    keys = [k for k in keys if k]
    if not keys:
        return None
    counts: Dict[str, int] = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1])
    if best[1] < max(2, vote_window // 2):
        return None
    return best[0]


def stabilize_sample(
    last_sample: Optional[Dict[str, Any]],
    current_sample: Optional[Dict[str, Any]],
    station_lookup: Dict[str, Dict[str, Any]],
    segment_seconds: Dict[tuple, float],
    history_samples: List[Dict[str, Any]],
    ema_alpha: float,
    median_window: int,
    vote_window: int,
    route_sequences: List[List[str]],
    strict_destination: bool,
) -> Optional[Dict[str, Any]]:
    if not current_sample:
        return current_sample
    if not last_sample:
        return current_sample

    cur = dict(current_sample)
    prev = last_sample
    same_segment = (
        str(prev.get("segment_from") or "") == str(cur.get("segment_from") or "")
        and str(prev.get("segment_to") or "") == str(cur.get("segment_to") or "")
        and str(cur.get("segment_from") or "") != ""
    )
    prev_source = str(prev.get("position_source") or "")
    cur_source = str(cur.get("position_source") or "")

    # If source quality degrades abruptly, keep the previous between-position for continuity.
    if prev_source.startswith("between_interp") and cur_source in {"next_station", "at_station"}:
        cur_tts = cur.get("time_to_station_sec")
        if cur_tts is None or float(cur_tts) > 40.0:
            held = dict(prev)
            held["position_source"] = "held_prev_between"
            held["raw_time_to_station_sec"] = cur_tts
            return held

    # Enforce non-increasing tts and non-regressing position on same segment.
    if same_segment and prev_source.startswith("between_interp") and cur_source.startswith("between_interp"):
        try:
            prev_tts = float(prev.get("time_to_station_sec"))
            cur_tts = float(cur.get("time_to_station_sec"))
        except (TypeError, ValueError):
            return cur

        if cur_tts > prev_tts + 3.0:
            cur_tts = prev_tts
            cur["time_to_station_sec"] = cur_tts
            interp = _interp_between_point(
                str(cur.get("segment_from") or ""),
                str(cur.get("segment_to") or ""),
                cur_tts,
                station_lookup,
                segment_seconds,
            )
            if interp:
                cur["lon"] = interp["lon"]
                cur["lat"] = interp["lat"]
            cur["position_source"] = "between_interp_clamped"
            cur["stabilization_note"] = "clamped_non_increasing_tts"

    # Reject rapid direction flips on the same station pair unless we were near segment endpoints.
    prev_from = str(prev.get("segment_from") or "")
    prev_to = str(prev.get("segment_to") or "")
    cur_from = str(cur.get("segment_from") or "")
    cur_to = str(cur.get("segment_to") or "")
    reversed_pair = prev_from and prev_to and (cur_from == prev_to and cur_to == prev_from)
    if reversed_pair:
        prev_t = _project_t_on_segment(prev, station_lookup)
        near_endpoint = prev_t is not None and (prev_t <= 0.08 or prev_t >= 0.92)
        if not near_endpoint:
            held = dict(prev)
            held["position_source"] = "held_prev_direction"
            held["raw_time_to_station_sec"] = cur.get("time_to_station_sec")
            held["stabilization_note"] = "rejected_direction_flip_mid_segment"
            return held

    # Reject discontinuous segment hops unless previous sample is close to an endpoint.
    prev_key = _segment_key(prev)
    cur_key = _segment_key(cur)
    if prev_key and cur_key and prev_key != cur_key:
        prev_t = _project_t_on_segment(prev, station_lookup)
        near_endpoint = prev_t is not None and (prev_t <= 0.12 or prev_t >= 0.88)
        if not near_endpoint and not _segments_share_endpoint(prev, cur):
            held = dict(prev)
            held["position_source"] = "held_discontinuous_hop"
            held["raw_time_to_station_sec"] = cur.get("time_to_station_sec")
            held["stabilization_note"] = "rejected_segment_hop_without_shared_endpoint"
            return held

    if strict_destination:
        dest = str(cur.get("destination_name") or prev.get("destination_name") or "")
        seg_from = str(cur.get("segment_from") or "")
        seg_to = str(cur.get("segment_to") or "")
        if dest and seg_from and seg_to and seg_from != seg_to:
            toward = _is_segment_toward_destination(
                from_name=seg_from,
                to_name=seg_to,
                destination_name=dest,
                station_lookup=station_lookup,
                route_sequences=route_sequences,
            )
            if toward is False:
                held = dict(prev)
                held["position_source"] = "held_destination_direction"
                held["raw_time_to_station_sec"] = cur.get("time_to_station_sec")
                held["stabilization_note"] = "rejected_not_toward_destination"
                return held

    # Segment-direction voting: prefer a stable direction over short-lived flips.
    dom = _dominant_segment_key(history_samples, vote_window=vote_window)
    cur_key = _segment_key(cur)
    prev_key = _segment_key(prev)
    if dom and cur_key and prev_key and cur_key != dom and prev_key == dom:
        prev_t = _project_t_on_segment(prev, station_lookup)
        if prev_t is None or (0.08 < prev_t < 0.92):
            held = dict(prev)
            held["position_source"] = "held_vote_direction"
            held["raw_time_to_station_sec"] = cur.get("time_to_station_sec")
            held["stabilization_note"] = "direction_voted_to_previous"
            return held

    # Temporal smoothing on segment progress t: median + EMA + forward clamp.
    stable_key = _segment_key(cur)
    if stable_key:
        from_name = str(cur.get("segment_from") or "")
        to_name = str(cur.get("segment_to") or "")
        raw_t = _project_t_on_segment(cur, station_lookup)
        if raw_t is not None:
            hist_t: List[float] = []
            for s in history_samples[-median_window:]:
                if _segment_key(s) == stable_key:
                    t = _project_t_on_segment(s, station_lookup)
                    if t is not None:
                        hist_t.append(t)

            cand_t = raw_t
            if hist_t:
                cand_t = float(statistics.median(hist_t + [raw_t]))

            prev_t = _project_t_on_segment(prev, station_lookup) if _segment_key(prev) == stable_key else None
            if prev_t is not None:
                ema_t = ema_alpha * cand_t + (1.0 - ema_alpha) * prev_t
                # UI coherence preference: same segment is forward-only.
                cand_t = max(prev_t, ema_t)
            cand_t = max(0.0, min(1.0, cand_t))

            interp = _interp_point_for_t(from_name, to_name, cand_t, station_lookup)
            if interp:
                cur["lon"] = interp["lon"]
                cur["lat"] = interp["lat"]
                # Keep tts coherent with smoothed progress.
                a = resolve_station_fragment(from_name, station_lookup)
                b = resolve_station_fragment(to_name, station_lookup)
                if a and b:
                    seg_t = float(segment_seconds.get((a["station_id"], b["station_id"]), 180.0))
                    cur["time_to_station_sec"] = max(0.0, (1.0 - cand_t) * seg_t)
                cur["position_source"] = "between_interp_filtered"
                cur["stabilization_note"] = "median_ema_forward_clamp"

    return cur


def main() -> None:
    dc = parse_args()
    cfg = build_cfg(dc)
    out_dir = pathlib.Path(dc.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = TflClient(cfg)
    print(f"[Debug] Loading route graph for line='{dc.line_id}'")
    stations_df, _edges_df, route_payloads = fetch_phase1_network(cfg, client)
    station_lookup = build_station_lookup(stations_df.to_dict(orient="records"))
    edges = build_sequence_edge_payload(route_payloads, LINE_DEPTHS)
    segment_seconds: Dict[tuple, float] = {}
    try:
        seqs = route_payloads.get(dc.line_id, {}).get("stopPointSequences", []) or []
        if seqs:
            stop_ids = [sp.get("id") for sp in seqs[0].get("stopPoint", []) if sp.get("id")]
            if len(stop_ids) >= 2:
                tt = client.get_json(f"/Line/{dc.line_id}/Timetable/{stop_ids[0]}/to/{stop_ids[-1]}")
                segment_seconds.update(build_segment_seconds_from_timetable(tt, route_payloads.get(dc.line_id, {})))
    except Exception as err:
        print(f"[Debug] Timetable segment-time fetch failed: {err}")
    route_sequences = _extract_route_sequences(route_payloads.get(dc.line_id, {}))
    static_payload = {
        "line_id": dc.line_id,
        "line_depth": float(LINE_DEPTHS.get(dc.line_id, -20.0)),
        "edges": edges,
        "stations": stations_df.to_dict(orient="records"),
    }
    (out_dir / "debug_static.json").write_text(json.dumps(static_payload))

    chosen_vehicle: Optional[str] = dc.vehicle_id or None
    last_sample: Optional[Dict[str, Any]] = None
    samples: List[Dict[str, Any]] = []
    history_path = out_dir / "debug_snapshots.jsonl"
    if history_path.exists():
        history_path.unlink()

    for i in range(dc.snapshots):
        captured = dt.datetime.now(dt.timezone.utc)
        arrivals = [a for a in client.get_json(f"/Line/{dc.line_id}/Arrivals") if int(a.get("operationType") or 0) == 1]
        arrivals_df = normalize_arrivals(arrivals, snapshot_idx=i, captured_at_utc=captured)
        points_df = map_arrivals_to_coordinates(arrivals_df, stations_df)
        primary_df = select_primary_prediction(points_df)
        chosen_vehicle = choose_vehicle_id_from_arrivals(arrivals, dc.vehicle_id, chosen_vehicle)

        current_sample = None
        if chosen_vehicle:
            vehicle_rows = [a for a in arrivals if str(a.get("vehicleId") or "") == str(chosen_vehicle)]
            best_row = _best_vehicle_row_by_tts(vehicle_rows) or (vehicle_rows[0] if vehicle_rows else None)
            inferred = derive_vehicle_position_from_arrivals(
                vehicle_rows=vehicle_rows,
                station_lookup=station_lookup,
                segment_seconds=segment_seconds,
            )
            if inferred:
                current_sample = {
                    "snapshot_idx": i,
                    "captured_at_utc": captured.isoformat(),
                    **inferred,
                    "raw_time_to_station_sec": inferred.get("time_to_station_sec"),
                    "raw_current_location": str((best_row or {}).get("currentLocation") or ""),
                    "raw_station_name": str((best_row or {}).get("stationName") or ""),
                    "raw_station_id": str((best_row or {}).get("naptanId") or ""),
                    "raw_vehicle_id": str((best_row or {}).get("vehicleId") or ""),
                    "raw_line_id": str((best_row or {}).get("lineId") or ""),
                    "raw_time_to_station_sec": (
                        float((best_row or {}).get("timeToStation"))
                        if (best_row or {}).get("timeToStation") is not None
                        else None
                    ),
                    "destination_name": str((best_row or {}).get("destinationName") or ""),
                    "platform_name": str((best_row or {}).get("platformName") or ""),
                    "tfl_direction": str((best_row or {}).get("direction") or ""),
                }
                current_sample = stabilize_sample(
                    last_sample=last_sample,
                    current_sample=current_sample,
                    station_lookup=station_lookup,
                    segment_seconds=segment_seconds,
                    history_samples=samples,
                    ema_alpha=dc.ema_alpha,
                    median_window=dc.median_window,
                    vote_window=dc.vote_window,
                    route_sequences=route_sequences,
                    strict_destination=dc.strict_destination,
                )
                samples.append(current_sample)
                last_sample = current_sample

        live_payload = {
            "line_id": dc.line_id,
            "vehicle_id": chosen_vehicle,
            "captured_at_utc": captured.isoformat(),
            "snapshot_idx": i,
            "edges": edges,
            "stations": stations_df.to_dict(orient="records"),
            "sample": current_sample,
            "samples": samples[-400:],
            "meta": {
                "arrivals_count": len(arrivals),
                "mapped_points": len(points_df),
                "primary_vehicle_points": len(primary_df),
            },
        }
        (out_dir / "live_debug_state.json").write_text(json.dumps(live_payload))
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(live_payload) + "\n")

        raw_loc = ""
        if current_sample:
            raw_loc = str(current_sample.get("raw_current_location") or "")
        print(
            f"[Debug] snapshot {i + 1}/{dc.snapshots} arrivals={len(arrivals)} mapped={len(points_df)} "
            f"vehicles={len(primary_df)} chosen={chosen_vehicle} raw_currentLocation='{raw_loc}'"
        )

        if i != dc.snapshots - 1:
            time.sleep(dc.interval_sec)

    print(f"[Debug] Complete. Open london_metro_3d/live_debug_single_train.html")


if __name__ == "__main__":
    main()
