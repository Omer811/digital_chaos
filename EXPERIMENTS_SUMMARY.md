# Experiments Summary

This file summarizes all experiments currently implemented in this project, with purpose, wiring, how to run, outputs, and latest observed status.

## 1) Arduino Analog Noise -> PCA (5 analog pins)
- Purpose: sample analog pins (`A0..A4`), project to 3D via PCA, visualize cloud structure.
- Entry: `main.py` with `config.json`
- Arduino sketch: `arduino/noise_sampler/noise_sampler.ino`
- Wiring: no special wiring required for floating-pin test; optional noise antennas/jumpers on analog pins.
- Run: `python3 main.py --config config.json`
- Outputs:
  - `output/data/raw_samples.csv`
  - `output/data/pca_points.csv`
  - `output/plots/pca_3d_scatter.png`
- Notes:
  - Includes configurable ADC-settle controls.
  - Includes delay auto-retry based on lag-1 correlation threshold.

## 2) Raw 3D analog space (A0/A1/A2)
- Purpose: visualize raw sample space directly, without PCA.
- Source data: `output/data/raw_samples.csv`
- Outputs:
  - `output/plots/raw_a0_a1_a2_3d.png`
  - `output/plots/raw_a0_a1_a2_3d.html`

## 3) Entropy conditioning pipeline
- Purpose: post-process sampled bits to reduce bias/correlation.
- Implemented stages:
  - XOR folding
  - Von Neumann corrector
  - CRC32 mixing
  - SHA block hashing (SHA-1/SHA-256)
- Core file: `src/entropy.py`
- Outputs:
  - `output/data/conditioned_entropy.bin`
  - `output/data/entropy_report.json`

## 4) Self-feedback A0 -> A1 sequence
- Purpose: drive state on one pin and feed readback into next emitted state.
- Entry: `run_self_feedback.py` with `self_feedback_config.json`
- Arduino sketch: `arduino/self_feedback/self_feedback.ino`
- Wiring:
  - `A0` connected to `A1`
- Run: `python3 run_self_feedback.py --config self_feedback_config.json`
- Outputs:
  - `output/self_feedback/self_feedback_samples.csv`
  - `output/self_feedback/self_feedback_2d.png`

## 5) RNG Method 3: Clock jitter (`jitter_rng`)
- Purpose: derive bits from watchdog/clock timing jitter.
- Entry: `run_rng_method.py --config jitter_rng_config.json`
- Arduino sketch: `arduino/jitter_rng/jitter_rng.ino`
- Outputs:
  - `output/jitter_rng/jitter_rng_bytes.csv`
  - `output/jitter_rng/jitter_rng_2d.png`
  - `output/jitter_rng/jitter_rng_report.json`
- Latest observed report:
  - ones ratio: `0.4873` (from `output/jitter_rng/jitter_rng_report.json`)

## 6) RNG Method 4: Race/metastability-style (`race_rng`)
- Purpose: derive bits from near-simultaneous timer race outcomes (+jitter mixing).
- Entry: `run_rng_method.py --config race_rng_config.json`
- Arduino sketch: `arduino/race_rng/race_rng.ino`
- Outputs:
  - `output/race_rng/race_rng_bytes.csv`
  - `output/race_rng/race_rng_2d.png`
  - `output/race_rng/race_rng_report.json`
- Latest observed report:
  - ones ratio: `0.4521` (from `output/race_rng/race_rng_report.json`)

## 7) 3-run triplet 3D plots for RNG methods
- Purpose: capture each RNG method 3 times and plot points `(run1, run2, run3)` in 3D.
- Entry: `run_rng_triplets.py`
- Run:
  - `python3 run_rng_triplets.py --configs jitter_rng_config.json race_rng_config.json --runs 3`
- Outputs:
  - `output/jitter_rng/jitter_rng_triplets.csv`
  - `output/jitter_rng/jitter_rng_triplets_3d.png`
  - `output/race_rng/race_rng_triplets.csv`
  - `output/race_rng/race_rng_triplets_3d.png`

## 8) MCP23017 floating GPIO experiment
- Purpose: sample MCP23017 pin states over I2C, visualize activity and pin correlation.
- Entry: `run_mcp23017_experiment.py` with `mcp23017_config.json`
- Arduino sketch: `arduino/mcp23017_sampler/mcp23017_sampler.ino`
- Wiring guide: `MCP23017_WIRING.md`
- Current config scope: `GPA0..GPA5` only (`selected_pins`)
- Run: `python3 run_mcp23017_experiment.py --config mcp23017_config.json`
- Outputs:
  - `output/mcp23017/mcp23017_raw_bytes.csv`
  - `output/mcp23017/mcp23017_pin_bits.csv`
  - `output/mcp23017/mcp23017_corr_report.json`
  - `output/mcp23017/mcp23017_pin_states.png`
  - `output/mcp23017/mcp23017_corr_heatmap.png`
- Latest observed report:
  - `pin_count=6`, `max_lag1_abs_corr=1.0`, strongest pair `GPA2/GPA4` with `1.0`

## 9) PWM sine feedback loop (updated to 1000 samples/cycle)
- Purpose: generate PWM sine target, read analog response with oversampling, and compute next PWM on the host computer.
- Entry: `run_sine_feedback.py` with `sine_feedback_config.json`
- Arduino sketch: `arduino/sine_feedback/sine_feedback.ino`
- Wiring guide: `SINE_FEEDBACK_WIRING.md`
- Current default:
  - `steps=1000` (one sine cycle sampled at 1000 points)
  - `oversample_count=16`, `oversample_delay_us=50`
- Run: `python3 run_sine_feedback.py --config sine_feedback_config.json`
- Outputs:
  - `output/sine_feedback/sine_feedback_steps.csv`
  - `output/sine_feedback/sine_feedback_2d.png`
  - `output/sine_feedback/sine_feedback_3d.png`
- Latest observed run:
  - `1000` steps generated
  - `read_adc` range `0..1022`

## Wiring index
- MCP23017 experiment wiring: `MCP23017_WIRING.md`
- Sine feedback wiring: `SINE_FEEDBACK_WIRING.md`
- RNG method intuition: `METHODS_EXPLANATION.md`
