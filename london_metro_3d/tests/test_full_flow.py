from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import urllib.error

from london_metro_3d.build_timeline_data import build_payload
from london_metro_3d.metro_pipeline import MetroConfig, TflClient, run_pipeline


FIXTURE_DIR = Path("london_metro_3d/fixtures")


class _DummyResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class TestLiveRetry(unittest.TestCase):
    def test_retry_on_429_then_success(self) -> None:
        cfg = MetroConfig(request_max_retries=1, request_backoff_sec=0.0)
        client = TflClient(cfg)

        err = urllib.error.HTTPError(
            url="https://api.tfl.gov.uk/test",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "0"},
            fp=None,
        )
        ok_resp = _DummyResponse(b'{"ok": true}')

        with mock.patch("urllib.request.urlopen", side_effect=[err, ok_resp]) as mocked:
            out = client.get_json("/Line/Mode/tube")

        self.assertTrue(out["ok"])
        self.assertEqual(mocked.call_count, 2)


class TestEndToEndFixtureFlow(unittest.TestCase):
    def test_pipeline_then_timeline_json(self) -> None:
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

            run_dir = Path(tmp)
            self.assertTrue((run_dir / "london_metro_3d.html").exists())
            stations_df = pd.read_csv(run_dir / "phase1_stations.csv")
            edges_df = pd.read_csv(run_dir / "phase1_edges.csv")
            points_df = pd.read_csv(run_dir / "phase2_arrival_points.csv")

            payload = build_payload(stations_df, edges_df, points_df)
            out_json = run_dir / "timeline_data.json"
            out_json.write_text(json.dumps(payload))

            loaded = json.loads(out_json.read_text())
            self.assertGreaterEqual(loaded["meta"]["station_count"], 1)
            self.assertGreaterEqual(loaded["meta"]["edge_count"], 1)
            self.assertGreaterEqual(loaded["meta"]["point_count"], 1)


if __name__ == "__main__":
    unittest.main()
