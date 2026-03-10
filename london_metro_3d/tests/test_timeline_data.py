from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from london_metro_3d.build_timeline_data import build_payload


class TestTimelineData(unittest.TestCase):
    def test_build_payload(self) -> None:
        stations_df = pd.DataFrame(
            [
                {"station_id": "A", "station_name": "A", "lat": 51.5, "lon": -0.1},
                {"station_id": "B", "station_name": "B", "lat": 51.6, "lon": -0.2},
            ]
        )
        edges_df = pd.DataFrame(
            [{"line_id": "victoria", "from_station": "A", "to_station": "B", "weight": 1}]
        )
        points_df = pd.DataFrame(
            [
                {
                    "snapshot_idx": 0,
                    "line_id": "victoria",
                    "vehicle_id": "v1",
                    "station_id": "A",
                    "station_name": "A",
                    "lon": -0.1,
                    "lat": 51.5,
                    "time_to_station_sec": 30,
                }
            ]
        )

        payload = build_payload(stations_df, edges_df, points_df)
        self.assertEqual(payload["meta"]["station_count"], 2)
        self.assertEqual(payload["meta"]["edge_count"], 1)
        self.assertEqual(payload["meta"]["point_count"], 1)
        self.assertEqual(payload["meta"]["snapshot_min"], 0)
        self.assertEqual(payload["meta"]["snapshot_max"], 0)

    def test_json_serializable(self) -> None:
        payload = {
            "meta": {"snapshot_min": 0, "snapshot_max": 0, "station_count": 0, "edge_count": 0, "point_count": 0},
            "stations": [],
            "edges": [],
            "points": [],
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "timeline.json"
            out.write_text(json.dumps(payload))
            loaded = json.loads(out.read_text())
            self.assertIn("meta", loaded)


if __name__ == "__main__":
    unittest.main()
