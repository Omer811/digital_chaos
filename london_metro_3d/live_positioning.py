from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Tuple


def normalize_station_name(name: str) -> str:
    s = (name or "").lower().strip()
    s = s.replace("&", " and ")
    for token in (" underground station", " station", ".", ",", "'", "-", "(", ")"):
        s = s.replace(token, " ")
    s = " ".join(s.split())
    return s


def parse_between(current_location: str) -> Optional[Tuple[str, str]]:
    s = (current_location or "").strip()
    if not s.lower().startswith("between "):
        return None
    body = s[8:].strip()
    parts = body.split(" and ", 1)
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def parse_at(current_location: str) -> Optional[str]:
    s = (current_location or "").strip()
    if not s.lower().startswith("at "):
        return None
    body = s[3:].strip()
    cut = body.lower().find(" platform")
    if cut >= 0:
        body = body[:cut].strip()
    return body or None


def build_station_lookup(stations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for st in stations:
        name = str(st.get("station_name") or st.get("name") or "")
        sid = str(st.get("station_id") or st.get("id") or st.get("naptanId") or "")
        if not name or not sid:
            continue
        key = normalize_station_name(name)
        out[key] = {
            "station_id": sid,
            "station_name": name,
            "lon": float(st.get("lon")),
            "lat": float(st.get("lat")),
        }
    return out


def resolve_station_fragment(fragment: str, lookup: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not fragment:
        return None
    k = normalize_station_name(fragment)
    if k in lookup:
        return lookup[k]
    for name_key, row in lookup.items():
        if name_key.startswith(k) or k.startswith(name_key) or k in name_key:
            return row
    return None


def _extract_route_sequences(route_payload: Dict[str, Any]) -> List[List[str]]:
    seqs: List[List[str]] = []
    for seq in route_payload.get("stopPointSequences", []):
        ids = [str(sp.get("id")) for sp in seq.get("stopPoint", []) if sp.get("id")]
        if len(ids) >= 2:
            seqs.append(ids)
    return seqs


def build_segment_seconds_from_timetable(
    timetable_payload: Dict[str, Any],
    route_payload: Dict[str, Any],
) -> Dict[Tuple[str, str], float]:
    seqs = _extract_route_sequences(route_payload)
    seg_samples: Dict[Tuple[str, str], List[float]] = {}

    routes = (timetable_payload.get("timetable") or {}).get("routes") or []
    for route in routes:
        for station_interval in route.get("stationIntervals") or []:
            intervals = station_interval.get("intervals") or []
            stop_time = {}
            for item in intervals:
                sid = item.get("stopId")
                tta = item.get("timeToArrival")
                if sid is None or tta is None:
                    continue
                try:
                    stop_time[str(sid)] = float(tta)
                except (TypeError, ValueError):
                    continue

            for ids in seqs:
                for a, b in zip(ids, ids[1:]):
                    if a in stop_time and b in stop_time:
                        dt = stop_time[b] - stop_time[a]
                        if dt > 0:
                            seg_samples.setdefault((a, b), []).append(dt)

    out: Dict[Tuple[str, str], float] = {}
    for key, vals in seg_samples.items():
        out[key] = float(statistics.median(vals))
    return out


def choose_vehicle_id_from_arrivals(
    arrivals: List[Dict[str, Any]],
    fixed_vehicle_id: str,
    last_vehicle_id: Optional[str],
) -> Optional[str]:
    if not arrivals:
        return last_vehicle_id
    by_vehicle: Dict[str, List[Dict[str, Any]]] = {}
    for a in arrivals:
        vid = str(a.get("vehicleId") or "")
        if not vid:
            continue
        by_vehicle.setdefault(vid, []).append(a)
    if not by_vehicle:
        return last_vehicle_id

    if fixed_vehicle_id and fixed_vehicle_id in by_vehicle:
        return fixed_vehicle_id

    if last_vehicle_id and last_vehicle_id in by_vehicle:
        return last_vehicle_id

    def score(rows: List[Dict[str, Any]]) -> float:
        has_between = any(str(r.get("currentLocation") or "").lower().startswith("between ") for r in rows)
        tts_vals = []
        for r in rows:
            try:
                tts_vals.append(float(r.get("timeToStation")))
            except Exception:
                pass
        min_tts = min(tts_vals) if tts_vals else 1e9
        station_var = len({str(r.get("stationName") or "") for r in rows})
        return (1000.0 if has_between else 0.0) + station_var * 5.0 - min_tts * 0.01

    ranked = sorted(by_vehicle.items(), key=lambda kv: score(kv[1]), reverse=True)
    return ranked[0][0] if ranked else last_vehicle_id


def derive_vehicle_position_from_arrivals(
    vehicle_rows: List[Dict[str, Any]],
    station_lookup: Dict[str, Dict[str, Any]],
    segment_seconds: Dict[Tuple[str, str], float],
    default_seg_sec: float = 180.0,
) -> Optional[Dict[str, Any]]:
    if not vehicle_rows:
        return None

    rows = []
    for r in vehicle_rows:
        tts = r.get("timeToStation")
        if tts is None:
            continue
        try:
            rows.append((float(tts), r))
        except (TypeError, ValueError):
            continue
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])

    tts, base = rows[0]
    current_location = str(base.get("currentLocation") or "")
    line_id = str(base.get("lineId") or "")
    vehicle_id = str(base.get("vehicleId") or "")

    next_station_name = str(base.get("stationName") or "")
    next_station = resolve_station_fragment(next_station_name, station_lookup)

    source = "station_anchor"
    segment_from = None
    segment_to = None
    lon = None
    lat = None

    bt = parse_between(current_location)
    if bt:
        a_name, b_name = bt
        a = resolve_station_fragment(a_name, station_lookup)
        b = resolve_station_fragment(b_name, station_lookup) or next_station
        if a and b:
            tts_to_b = None
            for x_tts, x_row in rows:
                nm = resolve_station_fragment(str(x_row.get("stationName") or ""), station_lookup)
                if nm and nm["station_id"] == b["station_id"]:
                    tts_to_b = x_tts
                    break
            if tts_to_b is None:
                tts_to_b = tts

            seg_t = segment_seconds.get((a["station_id"], b["station_id"]), default_seg_sec)
            alpha = max(0.0, min(1.0, 1.0 - (tts_to_b / max(1e-6, seg_t))))
            lon = a["lon"] + (b["lon"] - a["lon"]) * alpha
            lat = a["lat"] + (b["lat"] - a["lat"]) * alpha
            source = "between_interp"
            segment_from = a["station_name"]
            segment_to = b["station_name"]
            tts = tts_to_b

    if lon is None or lat is None:
        at_name = parse_at(current_location)
        at_station = resolve_station_fragment(at_name or "", station_lookup) if at_name else None
        if at_station:
            lon = at_station["lon"]
            lat = at_station["lat"]
            source = "at_station"
            segment_from = at_station["station_name"]
            segment_to = at_station["station_name"]

    if (lon is None or lat is None) and next_station:
        lon = next_station["lon"]
        lat = next_station["lat"]
        source = "next_station"
        segment_from = next_station["station_name"]
        segment_to = next_station["station_name"]

    if lon is None or lat is None:
        return None

    return {
        "vehicle_id": vehicle_id,
        "line_id": line_id,
        "lon": float(lon),
        "lat": float(lat),
        "time_to_station_sec": float(tts),
        "current_location": current_location,
        "segment_from": segment_from,
        "segment_to": segment_to,
        "position_source": source,
    }
