# PWM Sine Feedback Wiring (Arduino UNO)

## Goal
Generate a PWM sine approximation, read it on an analog pin, and compute the next PWM step on the host computer from the measured feedback (default run: 1000 steps per cycle).

## Pins
- PWM output pin: `D9` (default)
- Analog input pin: `A0` (default)
- GND: common reference

## Recommended wiring (with low-pass filter)
To read PWM as an analog-like voltage, use a simple RC filter:

- `D9` -> `1k resistor` -> node `Vsig`
- `Vsig` -> `A0`
- `Vsig` -> `0.1uF capacitor` -> `GND`
- `UNO GND` shared with capacitor ground

This smooths PWM into a voltage that `analogRead(A0)` can track.

## Minimal wiring (no filter)
- `D9` directly to `A0`
- `GND` common

This works electrically but `analogRead` will mostly see pulsed/highly quantized behavior (less useful waveform).

## Run
1. Wire as above (RC filter recommended).
2. Run:
   - `python3 run_sine_feedback.py --config sine_feedback_config.json`

The runner sends one step at a time to Arduino, but feedback is computed at waveform level:
- Transmit full 1000-sample waveform for a time slice.
- Receive full measured 1000-sample waveform.
- Compute next 1000-sample waveform on the computer.

## Output files
- `output/sine_feedback/sine_feedback_steps.csv`
- `output/sine_feedback/sine_feedback_2d.png`
- `output/sine_feedback/sine_feedback_2d.html`
- `output/sine_feedback/sine_feedback_3d.png`
- `output/sine_feedback/sine_feedback_3d.html`

## Tuning tips
- Increase `settle_us` if output lags/noisy.
- Increase `oversample_count` for smoother measurements.
- Increase `oversample_delay_us` if consecutive ADC reads are too correlated.
- New stop mode options:
  - `stop_when_decay`: stop early when output amplitude decays below threshold.
  - `decay_metric`: `peak_to_peak` (default) or `std`.
  - `decay_threshold_norm`: threshold in normalized output units (`0..1`).
  - `min_slices_before_decay_check`: avoid stopping too early.
  - `max_samples`: hard cap on collected samples; run stops when reached.
- Adjust `alpha_permille`:
  - Higher: follows target sine more strongly.
  - Lower: follows measured feedback more strongly.
