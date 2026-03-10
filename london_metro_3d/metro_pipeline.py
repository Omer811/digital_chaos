from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go


@dataclasses.dataclass
class MetroConfig:
    output_dir: str = "output/london_metro_3d"
    phase: str = "all"  # 1|2|3|4|all
    mode: str = "live"  # live|fixture
    fixture_dir: str = "london_metro_3d/fixtures"
    line_ids: List[str] = dataclasses.field(default_factory=lambda: [
        "bakerloo",
        "central",
        "circle",
        "district",
        "hammersmith-city",
        "jubilee",
        "metropolitan",
        "northern",
        "piccadilly",
        "victoria",
        "waterloo-city",
    ])
    snapshots: int = 8
    snapshot_interval_sec: float = 8.0
    use_mode_arrivals_endpoint: bool = True
    hotspot_grid_lon_bins: int = 36
    hotspot_grid_lat_bins: int = 36
    hotspot_grid_time_bins: int = 24
    hotspot_top_k: int = 600
    user_agent: str = "Mozilla/5.0 (CityLab Metro Experiment)"
    tfl_app_id: str = ""
    tfl_app_key: str = ""
    request_timeout_sec: float = 30.0
    request_max_retries: int = 4
    request_backoff_sec: float = 1.0
    respect_retry_after: bool = True
    request_rate_limit_per_min: int = 450


def load_config(path: str) -> MetroConfig:
    cfg = MetroConfig()
    data = json.loads(pathlib.Path(path).read_text()) if path else {}
    for key, value in data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg


class TflClient:
    def __init__(self, cfg: MetroConfig):
        self.cfg = cfg
        self._request_timestamps = deque()

    def _build_url(self, path: str) -> str:
        base = f"https://api.tfl.gov.uk{path}"
        query = {}
        if self.cfg.tfl_app_id:
            query["app_id"] = self.cfg.tfl_app_id
        if self.cfg.tfl_app_key:
            query["app_key"] = self.cfg.tfl_app_key
        if not query:
            return base
        return f"{base}?{urllib.parse.urlencode(query)}"

    def get_json(self, path: str) -> Any:
        url = self._build_url(path)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.cfg.user_agent,
                "Accept": "application/json",
            },
        )
        max_retries = max(0, int(self.cfg.request_max_retries))
        for attempt in range(max_retries + 1):
            try:
                self._acquire_request_slot()
                with urllib.request.urlopen(req, timeout=float(self.cfg.request_timeout_sec)) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as err:
                if not self._should_retry_http(err, attempt, max_retries):
                    raise
                time.sleep(self._retry_delay(err, attempt))
            except urllib.error.URLError:
                if attempt >= max_retries:
                    raise
                time.sleep(float(self.cfg.request_backoff_sec) * (2 ** attempt))
        raise RuntimeError("Unexpected retry loop exit in get_json")

    def _acquire_request_slot(self) -> None:
        per_min = max(1, int(self.cfg.request_rate_limit_per_min))
        now = time.monotonic()
        cutoff = now - 60.0
        while self._request_timestamps and self._request_timestamps[0] < cutoff:
            self._request_timestamps.popleft()

        if len(self._request_timestamps) >= per_min:
            earliest = self._request_timestamps[0]
            wait_s = max(0.01, 60.0 - (now - earliest))
            time.sleep(wait_s)
            now = time.monotonic()
            cutoff = now - 60.0
            while self._request_timestamps and self._request_timestamps[0] < cutoff:
                self._request_timestamps.popleft()

        self._request_timestamps.append(time.monotonic())

    def _should_retry_http(self, err: urllib.error.HTTPError, attempt: int, max_retries: int) -> bool:
        if attempt >= max_retries:
            return False
        return err.code in (429, 500, 502, 503, 504)

    def _retry_delay(self, err: urllib.error.HTTPError, attempt: int) -> float:
        if self.cfg.respect_retry_after:
            retry_after = None
            try:
                retry_after = err.headers.get("Retry-After")
            except Exception:
                retry_after = None
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except (TypeError, ValueError):
                    pass
        return float(self.cfg.request_backoff_sec) * (2 ** attempt)


# -------------------- Phase 1 --------------------

def build_network_from_route_sequences(route_payloads: Dict[str, Dict[str, Any]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    stations: Dict[str, Dict[str, Any]] = {}
    edge_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)

    for line_id, payload in route_payloads.items():
        for st in payload.get("stations", []):
            sid = st.get("id") or st.get("naptanId")
            if not sid:
                continue
            lat = st.get("lat")
            lon = st.get("lon")
            if lat is None or lon is None:
                continue
            stations[sid] = {
                "station_id": sid,
                "station_name": st.get("name", sid),
                "lat": float(lat),
                "lon": float(lon),
            }

        for seq in payload.get("stopPointSequences", []):
            stop_ids = [sp.get("id") for sp in seq.get("stopPoint", []) if sp.get("id")]
            for a, b in zip(stop_ids, stop_ids[1:]):
                if a == b:
                    continue
                edge_counts[(line_id, a, b)] += 1

    stations_df = pd.DataFrame(sorted(stations.values(), key=lambda x: x["station_id"]))
    edges_rows = [
        {"line_id": line_id, "from_station": a, "to_station": b, "weight": w}
        for (line_id, a, b), w in edge_counts.items()
    ]
    edges_df = pd.DataFrame(edges_rows)
    return stations_df, edges_df


def fetch_phase1_network(cfg: MetroConfig, client: TflClient) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Dict[str, Any]]]:
    route_payloads: Dict[str, Dict[str, Any]] = {}
    for line_id in cfg.line_ids:
        route_payloads[line_id] = client.get_json(f"/Line/{line_id}/Route/Sequence/all")

    stations_df, edges_df = build_network_from_route_sequences(route_payloads)
    return stations_df, edges_df, route_payloads


# -------------------- Phase 2 --------------------

def normalize_arrivals(arrivals: Iterable[Dict[str, Any]], snapshot_idx: int, captured_at_utc: dt.datetime) -> pd.DataFrame:
    rows = []
    for a in arrivals:
        sid = a.get("naptanId")
        if not sid:
            continue
        line_id = a.get("lineId") or "unknown"
        vehicle_id = a.get("vehicleId") or f"anon-{a.get('id', 'x')}"
        station_name = a.get("stationName") or sid
        tts = a.get("timeToStation")
        try:
            time_to_station = float(tts) if tts is not None else math.nan
        except (TypeError, ValueError):
            time_to_station = math.nan

        expected_arrival = a.get("expectedArrival")
        rows.append(
            {
                "snapshot_idx": snapshot_idx,
                "captured_at_utc": captured_at_utc.isoformat(),
                "line_id": line_id,
                "vehicle_id": vehicle_id,
                "station_id": sid,
                "station_name": station_name,
                "time_to_station_sec": time_to_station,
                "expected_arrival": expected_arrival,
                "direction": a.get("direction"),
                "destination_name": a.get("destinationName"),
                "platform_name": a.get("platformName"),
            }
        )
    return pd.DataFrame(rows)


def fetch_phase2_arrivals(cfg: MetroConfig, client: TflClient) -> pd.DataFrame:
    chunks = []
    line_set = set(cfg.line_ids)
    for snapshot_idx in range(cfg.snapshots):
        captured_at_utc = dt.datetime.now(dt.timezone.utc)
        if cfg.use_mode_arrivals_endpoint:
            arrivals_all = client.get_json("/Line/Mode/tube/Arrivals")
            arrivals = [a for a in arrivals_all if (a.get("lineId") in line_set)]
            chunks.append(normalize_arrivals(arrivals, snapshot_idx=snapshot_idx, captured_at_utc=captured_at_utc))
        else:
            for line_id in cfg.line_ids:
                arrivals = client.get_json(f"/Line/{line_id}/Arrivals")
                chunk = normalize_arrivals(arrivals, snapshot_idx=snapshot_idx, captured_at_utc=captured_at_utc)
                chunks.append(chunk)
        if snapshot_idx != cfg.snapshots - 1:
            time.sleep(cfg.snapshot_interval_sec)

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def map_arrivals_to_coordinates(arrivals_df: pd.DataFrame, stations_df: pd.DataFrame) -> pd.DataFrame:
    merged = arrivals_df.merge(
        stations_df[["station_id", "station_name", "lat", "lon"]],
        on="station_id",
        how="left",
        suffixes=("", "_station"),
    )
    merged = merged.dropna(subset=["lat", "lon"]).copy()
    merged["t_minutes"] = merged["snapshot_idx"].astype(float)
    return merged


# -------------------- Phase 3 --------------------

def build_vehicle_traces(points_df: pd.DataFrame) -> pd.DataFrame:
    if points_df.empty:
        return points_df.copy()
    sort_cols = ["vehicle_id", "snapshot_idx"]
    if "time_to_station_sec" in points_df.columns:
        sort_cols.append("time_to_station_sec")
    out = points_df.sort_values(sort_cols, na_position="last").copy()
    out["trace_order"] = out.groupby("vehicle_id").cumcount()
    return out


def compute_hotspot_voxels(points_df: pd.DataFrame, cfg: MetroConfig) -> pd.DataFrame:
    if points_df.empty:
        return pd.DataFrame(columns=["lon", "lat", "t_minutes", "count"])

    lon = points_df["lon"].to_numpy(dtype=float)
    lat = points_df["lat"].to_numpy(dtype=float)
    t = points_df["t_minutes"].to_numpy(dtype=float)

    lon_bins = np.linspace(lon.min(), lon.max(), cfg.hotspot_grid_lon_bins + 1)
    lat_bins = np.linspace(lat.min(), lat.max(), cfg.hotspot_grid_lat_bins + 1)
    t_bins = np.linspace(t.min(), t.max() if t.max() > t.min() else t.min() + 1, cfg.hotspot_grid_time_bins + 1)

    lon_idx = np.clip(np.digitize(lon, lon_bins) - 1, 0, cfg.hotspot_grid_lon_bins - 1)
    lat_idx = np.clip(np.digitize(lat, lat_bins) - 1, 0, cfg.hotspot_grid_lat_bins - 1)
    t_idx = np.clip(np.digitize(t, t_bins) - 1, 0, cfg.hotspot_grid_time_bins - 1)

    counts: Dict[Tuple[int, int, int], int] = defaultdict(int)
    for a, b, c in zip(lon_idx, lat_idx, t_idx):
        counts[(int(a), int(b), int(c))] += 1

    rows = []
    for (i, j, k), count in counts.items():
        lon_c = (lon_bins[i] + lon_bins[i + 1]) / 2
        lat_c = (lat_bins[j] + lat_bins[j + 1]) / 2
        t_c = (t_bins[k] + t_bins[k + 1]) / 2
        rows.append({"lon": lon_c, "lat": lat_c, "t_minutes": t_c, "count": count})

    out = pd.DataFrame(rows).sort_values("count", ascending=False)
    return out.head(cfg.hotspot_top_k).reset_index(drop=True)


# -------------------- Phase 4 --------------------

def _line_color(line_id: str) -> str:
    palette = {
        "bakerloo": "#B36305",
        "central": "#E32017",
        "circle": "#FFD300",
        "district": "#00782A",
        "hammersmith-city": "#F3A9BB",
        "jubilee": "#A0A5A9",
        "metropolitan": "#9B0056",
        "northern": "#000000",
        "piccadilly": "#003688",
        "victoria": "#0098D4",
        "waterloo-city": "#95CDBA",
    }
    return palette.get(line_id, "#34d399")


def render_3d_visuals(
    stations_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    points_df: pd.DataFrame,
    traces_df: pd.DataFrame,
    hotspots_df: pd.DataFrame,
    out_dir: pathlib.Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    station_lookup = stations_df.set_index("station_id")

    fig = go.Figure()

    # Network edges on z=0
    for line_id, group in edges_df.groupby("line_id"):
        xs: List[float] = []
        ys: List[float] = []
        zs: List[float] = []
        for _, row in group.iterrows():
            a = row["from_station"]
            b = row["to_station"]
            if a not in station_lookup.index or b not in station_lookup.index:
                continue
            n1 = station_lookup.loc[a]
            n2 = station_lookup.loc[b]
            xs.extend([n1["lon"], n2["lon"], None])
            ys.extend([n1["lat"], n2["lat"], None])
            zs.extend([0, 0, None])
        fig.add_trace(
            go.Scatter3d(
                x=xs,
                y=ys,
                z=zs,
                mode="lines",
                name=f"Line: {line_id}",
                line={"width": 2, "color": _line_color(line_id)},
                opacity=0.35,
                legendgroup=f"line-{line_id}",
            )
        )

    # Current train points by line
    if not points_df.empty:
        latest_idx = points_df["snapshot_idx"].max()
        latest = points_df[points_df["snapshot_idx"] == latest_idx]
        for line_id, group in latest.groupby("line_id"):
            fig.add_trace(
                go.Scatter3d(
                    x=group["lon"],
                    y=group["lat"],
                    z=group["t_minutes"],
                    mode="markers",
                    name=f"Trains now: {line_id}",
                    marker={"size": 3.5, "color": _line_color(line_id), "opacity": 0.9},
                    text=group["vehicle_id"],
                    hovertemplate="line=%{customdata[0]}<br>vehicle=%{text}<br>station=%{customdata[1]}<extra></extra>",
                    customdata=np.stack([group["line_id"], group["station_name"]], axis=1),
                    legendgroup=f"train-{line_id}",
                )
            )

    # Trajectories (journey traces)
    if not traces_df.empty:
        for vehicle_id, group in traces_df.groupby("vehicle_id"):
            if len(group) < 2:
                continue
            fig.add_trace(
                go.Scatter3d(
                    x=group["lon"],
                    y=group["lat"],
                    z=group["t_minutes"],
                    mode="lines",
                    name=f"Trace {vehicle_id}",
                    line={"width": 1.2, "color": _line_color(group["line_id"].iloc[0])},
                    opacity=0.3,
                    showlegend=False,
                )
            )

    # 3D hotspots
    if not hotspots_df.empty:
        fig.add_trace(
            go.Scatter3d(
                x=hotspots_df["lon"],
                y=hotspots_df["lat"],
                z=hotspots_df["t_minutes"],
                mode="markers",
                name="Hotspots",
                marker={
                    "size": np.clip(hotspots_df["count"].to_numpy(dtype=float), 2, 16),
                    "color": hotspots_df["count"],
                    "colorscale": "Turbo",
                    "opacity": 0.75,
                    "colorbar": {"title": "Pass count"},
                },
                hovertemplate="count=%{marker.color}<br>lon=%{x:.4f}<br>lat=%{y:.4f}<br>time bin=%{z:.2f}<extra></extra>",
            )
        )

    fig.update_layout(
        template="plotly_dark",
        title="London Underground 3D Flow + Hotspots",
        scene={
            "xaxis_title": "Longitude",
            "yaxis_title": "Latitude",
            "zaxis_title": "Time Slice",
            "bgcolor": "rgba(8,10,17,1)",
        },
        legend={"font": {"size": 10}},
        margin={"l": 0, "r": 0, "b": 0, "t": 44},
    )

    html_path = out_dir / "london_metro_3d.html"
    png_path = out_dir / "london_metro_3d.png"
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    try:
        fig.write_image(str(png_path), width=1600, height=1000, scale=1)
    except Exception:
        # Keep pipeline usable even if kaleido is not available.
        pass


def save_csv(df: pd.DataFrame, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def load_fixture_json(fixture_dir: pathlib.Path, filename: str) -> Any:
    return json.loads((fixture_dir / filename).read_text())


def run_pipeline(cfg: MetroConfig) -> Dict[str, Any]:
    out_dir = pathlib.Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = pathlib.Path(cfg.fixture_dir)
    client = TflClient(cfg)

    artifacts: Dict[str, Any] = {}

    # Phase 1
    if cfg.phase in ("1", "all", "2", "3", "4"):
        if cfg.mode == "fixture":
            route_payloads = {}
            for line_id in cfg.line_ids:
                candidate = fixture_dir / f"route_sequence_{line_id}.json"
                if candidate.exists():
                    route_payloads[line_id] = json.loads(candidate.read_text())
            if not route_payloads:
                route_payloads["victoria"] = load_fixture_json(fixture_dir, "route_sequence_victoria.json")
            stations_df, edges_df = build_network_from_route_sequences(route_payloads)
        else:
            stations_df, edges_df, _ = fetch_phase1_network(cfg, client)

        save_csv(stations_df, out_dir / "phase1_stations.csv")
        save_csv(edges_df, out_dir / "phase1_edges.csv")
        artifacts["stations_df"] = stations_df
        artifacts["edges_df"] = edges_df

    # Phase 2
    if cfg.phase in ("2", "all", "3", "4"):
        stations_df = artifacts.get("stations_df")
        if stations_df is None:
            stations_df = pd.read_csv(out_dir / "phase1_stations.csv")

        if cfg.mode == "fixture":
            arrivals = load_fixture_json(fixture_dir, "arrivals_victoria.json")
            arrivals_df = normalize_arrivals(arrivals, snapshot_idx=0, captured_at_utc=dt.datetime.now(dt.timezone.utc))
        else:
            arrivals_df = fetch_phase2_arrivals(cfg, client)

        points_df = map_arrivals_to_coordinates(arrivals_df, stations_df)
        save_csv(arrivals_df, out_dir / "phase2_arrivals_raw.csv")
        save_csv(points_df, out_dir / "phase2_arrival_points.csv")
        artifacts["points_df"] = points_df

    # Phase 3
    if cfg.phase in ("3", "all", "4"):
        points_df = artifacts.get("points_df")
        if points_df is None:
            points_df = pd.read_csv(out_dir / "phase2_arrival_points.csv")

        traces_df = build_vehicle_traces(points_df)
        hotspots_df = compute_hotspot_voxels(points_df, cfg)
        save_csv(traces_df, out_dir / "phase3_vehicle_traces.csv")
        save_csv(hotspots_df, out_dir / "phase3_hotspots.csv")
        artifacts["traces_df"] = traces_df
        artifacts["hotspots_df"] = hotspots_df

    # Phase 4
    if cfg.phase in ("4", "all"):
        stations_df = artifacts.get("stations_df")
        edges_df = artifacts.get("edges_df")
        points_df = artifacts.get("points_df")
        traces_df = artifacts.get("traces_df")
        hotspots_df = artifacts.get("hotspots_df")

        if stations_df is None:
            stations_df = pd.read_csv(out_dir / "phase1_stations.csv")
        if edges_df is None:
            edges_df = pd.read_csv(out_dir / "phase1_edges.csv")
        if points_df is None:
            points_df = pd.read_csv(out_dir / "phase2_arrival_points.csv")
        if traces_df is None:
            traces_df = pd.read_csv(out_dir / "phase3_vehicle_traces.csv")
        if hotspots_df is None:
            hotspots_df = pd.read_csv(out_dir / "phase3_hotspots.csv")

        render_3d_visuals(stations_df, edges_df, points_df, traces_df, hotspots_df, out_dir)

    return artifacts
