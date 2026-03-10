from __future__ import annotations

import unittest

import pandas as pd

from london_metro_3d.run_live_mode import build_edge_payload, build_train_payload


class TestLiveModePayloads(unittest.TestCase):
    def test_build_edge_payload_depth(self) -> None:
        stations_df = pd.DataFrame(
            [
                {"station_id": "A", "station_name": "A", "lat": 51.5, "lon": -0.1},
                {"station_id": "B", "station_name": "B", "lat": 51.6, "lon": -0.2},
            ]
        )
        edges_df = pd.DataFrame([{"line_id": "victoria", "from_station": "A", "to_station": "B", "weight": 1}])
        payload = build_edge_payload(edges_df, stations_df, {"victoria": -34.0})
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["z1"], -34.0)
        self.assertEqual(payload[0]["z2"], -34.0)

    def test_build_train_payload(self) -> None:
        points_df = pd.DataFrame(
            [
                {
                    "line_id": "victoria",
                    "vehicle_id": "v1",
                    "station_id": "A",
                    "station_name": "A",
                    "lon": -0.1,
                    "lat": 51.5,
                    "time_to_station_sec": 25.0,
                }
            ]
        )
        trains = build_train_payload(points_df, {"victoria": -34.0})
        self.assertEqual(len(trains), 1)
        self.assertEqual(trains[0]["z"], -34.0)
        self.assertEqual(trains[0]["line_id"], "victoria")


if __name__ == "__main__":
    unittest.main()
