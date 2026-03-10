# London Metro 3D Experiment

This experiment builds a **3D view of London Underground traffic flow** using TfL API data, then computes **3D hotspots** where trains pass most frequently.

## Phases

1. Phase 1 (`network`): fetch line route sequences and build station/edge graph.
2. Phase 2 (`arrivals`): collect train arrival snapshots and map events to station coordinates.
3. Phase 3 (`traces + hotspots`): reconstruct per-train traces over time and aggregate 3D hotspot voxels.
4. Phase 4 (`visualization`): render Plotly 3D output (`HTML` + optional `PNG`).

## Files

- `london_metro_3d/metro_pipeline.py`: core phase logic.
- `london_metro_3d/run_experiment.py`: CLI runner.
- `london_metro_3d/tfl_credentials.example.json`: template for primary/secondary TfL keys.
- `london_metro_3d/build_timeline_data.py`: converts phase outputs to timeline JSON for live UI playback.
- `london_metro_3d/live_timeline.html`: interactive timeline UI (fast-forward + cumulative hotspots).
- `london_metro_3d/tests/test_metro_pipeline.py`: phase/unit/integration tests.
- `london_metro_3d/tests/test_timeline_data.py`: timeline JSON build tests.
- `london_metro_3d/config.example.json`: JSON-configurable run settings.
- `london_metro_3d/fixtures/*.json`: offline fixtures for deterministic tests.

## Test each phase separately

```bash
python3 -m unittest london_metro_3d.tests.test_metro_pipeline london_metro_3d.tests.test_timeline_data -v
```

Full flow validation (pipeline + timeline export + 429 retry behavior):

```bash
python3 -m unittest london_metro_3d.tests.test_full_flow -v
```

## Run by phase (fixture mode)

```bash
# Phase 1 only
python3 london_metro_3d/run_experiment.py --mode fixture --phase 1 --line-ids victoria --output-dir output/london_metro_3d/phase1_fixture

# Phase 2 only
python3 london_metro_3d/run_experiment.py --mode fixture --phase 2 --line-ids victoria --output-dir output/london_metro_3d/phase2_fixture

# Phase 3 only
python3 london_metro_3d/run_experiment.py --mode fixture --phase 3 --line-ids victoria --output-dir output/london_metro_3d/phase3_fixture

# Phase 4 only (requires prior phase CSVs in output dir)
python3 london_metro_3d/run_experiment.py --mode fixture --phase 4 --line-ids victoria --output-dir output/london_metro_3d/phase4_fixture
```

## Run full pipeline (live TfL)

```bash
python3 london_metro_3d/run_experiment.py \
  --mode live \
  --phase all \
  --line-ids bakerloo,central,circle,district,hammersmith-city,jubilee,metropolitan,northern,piccadilly,victoria,waterloo-city \
  --snapshots 10 \
  --snapshot-interval-sec 10 \
  --output-dir output/london_metro_3d/live_run
```

Notes for rate-limits (`429 Too Many Requests`):
- The pipeline now retries HTTP `429/5xx` with exponential backoff.
- It now uses a single `/Line/Mode/tube/Arrivals` call per snapshot (filtered to requested lines), which is much lighter than per-line polling.
- It enforces a hard in-process cap via `request_rate_limit_per_min` (default: `450`) to stay below your `500/min` subscription.

## Credentials file (primary + secondary keys)

Create `london_metro_3d/tfl_credentials.local.json` (ignored by git) from the example:

```json
{
  "tfl_app_id": "",
  "tfl_app_key_primary": "<PRIMARY>",
  "tfl_app_key_secondary": "<SECONDARY>",
  "active_key": "primary"
}
```

Then run without passing keys in CLI:

```bash
python3 london_metro_3d/run_experiment.py --mode live --phase all
```

Switch keys by changing `active_key` to `secondary`.

If TfL rejects unauthenticated requests in your environment, pass credentials:

```bash
python3 london_metro_3d/run_experiment.py --mode live --phase all \
  --tfl-app-id "<APP_ID>" --tfl-app-key "<APP_KEY>"
```

## Outputs

- `phase1_stations.csv`
- `phase1_edges.csv`
- `phase2_arrivals_raw.csv`
- `phase2_arrival_points.csv`
- `phase3_vehicle_traces.csv`
- `phase3_hotspots.csv`
- `london_metro_3d.html`
- `london_metro_3d.png` (if Kaleido available)

## Live Timeline UI (define timeline + fast-forward hotspots)

Build timeline JSON from a run:

```bash
python3 london_metro_3d/build_timeline_data.py \
  --run-dir output/london_metro_3d/live_run \
  --output output/london_metro_3d/live_run/timeline_data.json
```

Serve and open locally:

```bash
python3 -m http.server 8000
```

Then open:

`http://localhost:8000/london_metro_3d/live_timeline.html`

In the UI:
- set Start/End snapshot to define timeline window
- set Snapshot Step + FPS for fast-forward speed
- press `Play`
- hotspots are cumulative, so you can watch them emerge over time
