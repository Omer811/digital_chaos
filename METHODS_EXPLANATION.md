# Method 3 and Method 4 (Intuitive)

## 3) Clock Jitter Method (`jitter_rng`)
Idea in plain words:
- The Arduino has clocks that are never perfectly stable.
- The watchdog timer and the CPU timer do not line up exactly the same way forever.
- Tiny timing drift and electrical noise cause small unpredictable shifts.

How we use that:
- Timer1 runs very fast continuously.
- Every watchdog interrupt, we snapshot Timer1.
- We compare snapshots and extract a low bit from the timing differences.
- 8 bits become one byte, repeated many times.

Why this can work:
- We are not using ADC value randomness.
- We are using phase/timing uncertainty (jitter), which is a different physical source.

## 4) Race / Metastability-Style Method (`race_rng`)
Idea in plain words:
- We set up two timer overflow events to happen almost at the same time.
- They "race" each other.
- The first observed winner gives one output bit (Timer1 wins = 1, Timer2 wins = 0).

How we use that:
- Before each bit, both timers are preloaded near overflow.
- Their deadlines are intentionally very close.
- The code polls overflow flags and emits the winner as the bit.
- A small tie-break uses Timer0 jitter when both appear together.

Why this can work:
- Near-simultaneous races are sensitive to tiny timing perturbations.
- Small clock/interrupt/supply noise can flip the observed winner.

## Important caveat
These methods improve diversity vs plain ADC reads, but they are still experimental.
For serious cryptographic use, always post-process (Von Neumann + hashing) and validate with statistical test suites (NIST SP 800-22 / Dieharder / PractRand).

## Run commands
- Jitter method:
  - `python3 run_rng_method.py --config jitter_rng_config.json`
- Race method:
  - `python3 run_rng_method.py --config race_rng_config.json`
