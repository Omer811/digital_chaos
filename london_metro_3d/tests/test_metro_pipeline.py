from __future__ import annotations

import datetime as dt
import json
import pathlib
import tempfile
import unittest

import pandas as pd

from london_metro_3d.metro_pipeline import (
    MetroConfig,
    build_network_from_route_sequences,
    build_vehicle_traces,
    compute_hotspot_voxels,
    map_arrivals_to_coordinates,
    normalize_arrivals,
    run_pipeline,
)


FIXTURE_DIR = pathlib.Path("london_metro_3d/fixtures")


class TestPhase1Network(unittest.TestCase):
    def test_build_network_from_fixture(self) -> None:
        payload = json.loads((FIXTURE_DIR / "route_sequence_victoria.json").read_text())
        stations_df, edges_df = build_network_from_route_sequences({"victoria": payload})

        self.assertGreaterEqual(len(stations_df), 3)
        self.assertGreaterEqual(len(edges_df), 2)
        self.assertIn("940GZZLUOXF", set(stations_df["station_id"]))


class TestPhase2Arrivals(unittest.TestCase):
    def test_normalize_and_map(self) -> None:
        arrivals = json.loads((FIXTURE_DIR / "arrivals_victoria.json").read_text())
        payload = json.loads((FIXTURE_DIR / "route_sequence_victoria.json").read_text())
        stations_df, _ = build_network_from_route_sequences({"victoria": payload})

        normalized = normalize_arrivals(arrivals, snapshot_idx=2, captured_at_utc=dt.datetime.now(dt.timezone.utc))
        points = map_arrivals_to_coordinates(normalized, stations_df)

        self.assertEqual(len(normalized), 3)
        self.assertGreaterEqual(len(points), 3)
        self.assertIn("lon", points.columns)
        self.assertIn("lat", points.columns)


class TestPhase3Hotspots(unittest.TestCase):
    def test_trace_and_hotspots(self) -> None:
        points = pd.DataFrame(
            [
                {"vehicle_id": "v1", "snapshot_idx": 0, "line_id": "victoria", "station_name": "A", "lon": -0.10, "lat": 51.50, "t_minutes": 0},
                {"vehicle_id": "v1", "snapshot_idx": 1, "line_id": "victoria", "station_name": "B", "lon": -0.11, "lat": 51.51, "t_minutes": 1},
                {"vehicle_id": "v2", "snapshot_idx": 1, "line_id": "victoria", "station_name": "A", "lon": -0.10, "lat": 51.50, "t_minutes": 1},
            ]
        )
        traces = build_vehicle_traces(points)
        self.assertEqual(traces["trace_order"].max(), 1)

        cfg = MetroConfig(mode="fixture", phase="3", hotspot_grid_lon_bins=8, hotspot_grid_lat_bins=8, hotspot_grid_time_bins=4)
        hotspots = compute_hotspot_voxels(points, cfg)
        self.assertGreaterEqual(len(hotspots), 1)
        self.assertGreaterEqual(int(hotspots["count"].max()), 1)


class TestIntegrationFixture(unittest.TestCase):
    def test_full_pipeline_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = MetroConfig(
                output_dir=tmp,
                mode="fixture",
                phase="all",
                fixture_dir=str(FIXTURE_DIR),
                line_ids=["victoria"],
                snapshots=1,
            )
            run_pipeline(cfg)

            self.assertTrue((pathlib.Path(tmp) / "phase1_stations.csv").exists())
            self.assertTrue((pathlib.Path(tmp) / "phase2_arrival_points.csv").exists())
            self.assertTrue((pathlib.Path(tmp) / "phase3_hotspots.csv").exists())
            self.assertTrue((pathlib.Path(tmp) / "london_metro_3d.html").exists())


if __name__ == "__main__":
    unittest.main()
