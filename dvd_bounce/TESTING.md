# DVD Bounce Terminal Tests

Run from project root:

```bash
perl dvd_bounce/bounce_terminal_tests.pl
```

Python test suite (recommended):

```bash
cd dvd_bounce
python3 -m unittest test_bounce_physics.py -v
```

What it checks:

- Core geometry/reflection unit checks.
- Angle sweep regression over multiple boundary shapes.
- Detects:
  - freeze/stuck movement,
  - speed drift (should be constant speed),
  - escaping far outside boundary.

Exit code:

- `0` = pass
- non-zero = failures detected

Notes:

- The Perl harness remains as a zero-dependency fallback.
- The Python suite includes fade-function tests in addition to bounce regression tests.
