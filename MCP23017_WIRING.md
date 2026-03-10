# MCP23017 + Arduino UNO Wiring (Floating-Pin Noise Experiment)

## Goal
Sample all 16 MCP23017 GPIO pins while they are floating, then plot pin states and compute correlation.

## Required connections
Use an MCP23017 breakout (or bare IC with proper decoupling).

- `UNO 5V` -> `MCP23017 VDD`
- `UNO GND` -> `MCP23017 VSS`
- `UNO A4 (SDA)` -> `MCP23017 SDA`
- `UNO A5 (SCL)` -> `MCP23017 SCL`
- `MCP23017 RESET` -> `VDD` (or to UNO pin with pull-up; simplest is tie high)
- `MCP23017 A0` -> `GND`
- `MCP23017 A1` -> `GND`
- `MCP23017 A2` -> `GND`

With `A2=A1=A0=0`, I2C address is `0x20` (default in config).

## I2C pull-ups
- Most MCP23017 modules already include pull-ups on SDA/SCL.
- If using bare chip, add pull-ups (typically `4.7k`) from SDA to VDD and SCL to VDD.

## Floating pins setup
- Leave all GPIO pins unconnected:
  - `GPA0..GPA7` floating
  - `GPB0..GPB7` floating
- This is intentionally noisy and environment-sensitive.

## Optional stability parts (recommended)
- Add a `0.1uF` ceramic capacitor between `VDD` and `VSS` close to MCP23017.

## Run
1. Wire as above.
2. Verify the board port in `mcp23017_config.json`.
3. Run:
   - `python3 run_mcp23017_experiment.py --config mcp23017_config.json`

## Outputs
- `output/mcp23017/mcp23017_raw_bytes.csv`
- `output/mcp23017/mcp23017_pin_bits.csv`
- `output/mcp23017/mcp23017_corr_matrix.csv`
- `output/mcp23017/mcp23017_corr_report.json`
- `output/mcp23017/mcp23017_pin_states.png`
- `output/mcp23017/mcp23017_corr_heatmap.png`

## Notes
- Floating pins can show strong cross-correlation due to shared environment and coupling.
- Touching wires, changing cable placement, or power noise will change behavior.
