# Arduino Noise PCA Visualizer

Collect analog noise from Arduino UNO, project samples to 3D with PCA, and export Plotly visualizations as PNG.

## What It Does
- Uploads an Arduino sketch (optional, configurable).
- Samples `N` rows from any subset of UNO analog pins (`A0..A5`) over serial.
- Runs PCA to 3 components.
- Saves:
  - raw samples CSV
  - PCA points CSV
  - Plotly 3D scatter PNG (and HTML)

## Project Layout
- `arduino/noise_sampler/noise_sampler.ino` Arduino sketch + serial protocol
- `main.py` pipeline entrypoint
- `config.json` all runtime configuration
- `src/` modular Python code (collector, PCA, visualizations)

## Requirements
- Python 3.9+
- `arduino-cli`
- Arduino UNO connected (default port in config is `/dev/cu.usbmodem1201`)

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Run

```bash
python3 main.py --config config.json
```

On success, outputs are written to:
- `output/data/raw_samples.csv`
- `output/data/pca_points.csv`
- `output/plots/pca_3d_scatter.png`
- `output/plots/pca_3d_scatter.html`

## Config
Edit `config.json`:
- `arduino.port` serial port
- `arduino.upload_before_run` compile/upload each run
- `sampling.sample_count` number of rows to capture
- `sampling.pins` analog pin numbers (0..5)
- `sampling.delay_us` delay between sample rows
- `sampling.channel_settle_us` delay after switching ADC channel
- `sampling.throwaway_reads_after_switch` discarded reads before kept read
- `sampling.progress_every_samples` Arduino emits progress every N samples (0 disables)
- `correlation.auto_increase_delay_until_uncorrelated` enable lag-1 correlation guard
- `correlation.lag1_abs_threshold` max allowed `abs(corr(x_t, x_t-1))` across pins
- `correlation.delay_step_us` delay increment per retry
- `correlation.max_delay_us` cap for delay search
- `correlation.max_attempts` cap retries
- `correlation.fail_if_unmet` fail run if threshold is still not met at the cap
- `entropy.xor_group_size` XOR-fold N raw bits into one bit
- `entropy.use_von_neumann` apply Von Neumann corrector to debias bit pairs
- `entropy.use_crc_mixing` apply rolling CRC32 over byte blocks
- `entropy.use_hash_blocks` hash fixed-size blocks (`sha1` or `sha256`)
- `entropy.hash_partial_block` hash the last short block instead of dropping it
- `processing.standardize` apply z-score before PCA
- output file/dir names

Correlation tuning report is saved at `output/data/correlation_report.json`.
Conditioned entropy outputs are saved at:
- `output/data/conditioned_entropy.bin`
- `output/data/entropy_report.json`

## Extending
- Add sampling modes in `src/serial_collector.py`.
- Add additional visualizers under `src/visualizations/` by implementing `BaseVisualizer`.
- Register multiple visualizers inside `src/pipeline.py`.
