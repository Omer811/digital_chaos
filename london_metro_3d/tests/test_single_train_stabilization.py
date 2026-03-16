from __future__ import annotations

import unittest

from london_metro_3d.live_positioning import build_station_lookup
from london_metro_3d.run_live_debug_single_train import (
    _is_segment_toward_destination,
    _project_t_on_segment,
    stabilize_sample,
)


class TestSingleTrainStabilization(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = build_station_lookup(
            [
                {"station_id": "A", "station_name": "A", "lon": 0.0, "lat": 0.0},
                {"station_id": "B", "station_name": "B", "lon": 1.0, "lat": 0.0},
                {"station_id": "C", "station_name": "C", "lon": 2.0, "lat": 0.0},
                {"station_id": "D", "station_name": "D", "lon": 3.0, "lat": 0.0},
            ]
        )
        self.route_sequences = [["A", "B", "C", "D"]]
        self.segment_seconds = {
            ("A", "B"): 100.0,
            ("B", "C"): 100.0,
            ("C", "D"): 100.0,
        }

    def test_direction_toward_destination_positive(self) -> None:
        ok = _is_segment_toward_destination(
            from_name="B",
            to_name="C",
            destination_name="D",
            station_lookup=self.lookup,
            route_sequences=self.route_sequences,
        )
        self.assertTrue(ok)

    def test_direction_toward_destination_negative(self) -> None:
        ok = _is_segment_toward_destination(
            from_name="B",
            to_name="A",
            destination_name="D",
            station_lookup=self.lookup,
            route_sequences=self.route_sequences,
        )
        self.assertFalse(ok)

    def test_stabilize_rejects_not_toward_destination(self) -> None:
        prev = {
            "segment_from": "B",
            "segment_to": "C",
            "destination_name": "D",
            "position_source": "between_interp",
            "lon": 1.4,
            "lat": 0.0,
            "time_to_station_sec": 60.0,
        }
        cur = {
            "segment_from": "B",
            "segment_to": "A",  # wrong direction for destination D
            "destination_name": "D",
            "position_source": "between_interp",
            "lon": 0.9,
            "lat": 0.0,
            "time_to_station_sec": 70.0,
        }
        out = stabilize_sample(
            last_sample=prev,
            current_sample=cur,
            station_lookup=self.lookup,
            segment_seconds=self.segment_seconds,
            history_samples=[prev],
            ema_alpha=0.35,
            median_window=5,
            vote_window=5,
            route_sequences=self.route_sequences,
            strict_destination=True,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["segment_from"], "B")
        self.assertEqual(out["segment_to"], "C")
        self.assertEqual(out["position_source"], "held_destination_direction")

    def test_stabilize_clamps_progress_forward_same_segment(self) -> None:
        prev = {
            "segment_from": "B",
            "segment_to": "C",
            "destination_name": "D",
            "position_source": "between_interp",
            "lon": 1.7,
            "lat": 0.0,
            "time_to_station_sec": 30.0,
        }
        # raw sample regresses backward on same segment
        cur = {
            "segment_from": "B",
            "segment_to": "C",
            "destination_name": "D",
            "position_source": "between_interp",
            "lon": 1.3,
            "lat": 0.0,
            "time_to_station_sec": 70.0,
        }
        out = stabilize_sample(
            last_sample=prev,
            current_sample=cur,
            station_lookup=self.lookup,
            segment_seconds=self.segment_seconds,
            history_samples=[prev],
            ema_alpha=0.35,
            median_window=5,
            vote_window=5,
            route_sequences=self.route_sequences,
            strict_destination=True,
        )
        self.assertIsNotNone(out)
        prev_t = _project_t_on_segment(prev, self.lookup)
        out_t = _project_t_on_segment(out, self.lookup)
        self.assertIsNotNone(prev_t)
        self.assertIsNotNone(out_t)
        self.assertGreaterEqual(out_t, prev_t)


if __name__ == "__main__":
    unittest.main()
