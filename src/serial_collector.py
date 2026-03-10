from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import serial


class SerialCollectionError(RuntimeError):
    pass


@dataclass
class SamplingRequest:
    sample_count: int
    pins: list[int]
    delay_us: int
    channel_settle_us: int
    throwaway_reads_after_switch: int
    progress_every_samples: int
    baud_rate: int
    port: str
    serial_timeout_seconds: float
    handshake_timeout_seconds: float


def _wait_for_ready(ser: serial.Serial, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        raw = ser.readline().decode("utf-8", errors="replace").strip()
        if not raw:
            continue
        if raw == "READY":
            return True
    return False


def _build_start_command(req: SamplingRequest) -> str:
    pin_csv = ",".join(str(p) for p in req.pins)
    return (
        f"START,{req.sample_count},{len(req.pins)},{pin_csv},"
        f"{req.delay_us},{req.channel_settle_us},{req.throwaway_reads_after_switch},"
        f"{req.progress_every_samples}\n"
    )


def collect_samples(req: SamplingRequest) -> pd.DataFrame:
    rows: list[dict[str, int]] = []
    print(
        f"[collector] Opening {req.port} @ {req.baud_rate} baud "
        f"(samples={req.sample_count}, pins={req.pins}, delay_us={req.delay_us})",
        flush=True,
    )

    with serial.Serial(req.port, req.baud_rate, timeout=req.serial_timeout_seconds) as ser:
        # Reset sequence after opening serial is normal on UNO.
        time.sleep(2.0)
        ser.reset_input_buffer()

        got_ready = _wait_for_ready(ser, req.handshake_timeout_seconds)
        if got_ready:
            print("[collector] Arduino READY received", flush=True)
        else:
            print("[collector] READY timeout, continuing anyway", flush=True)

        print("[collector] Sending START command", flush=True)
        ser.write(_build_start_command(req).encode("ascii"))
        ser.flush()

        got_begin = False
        deadline = time.time() + req.serial_timeout_seconds

        while True:
            if time.time() > deadline:
                raise SerialCollectionError("Timed out while receiving sample stream")

            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith("ERROR"):
                raise SerialCollectionError(f"Arduino error: {line}")

            if line.startswith("BEGIN,"):
                got_begin = True
                print(f"[collector] {line}", flush=True)
                continue

            if line.startswith("PROGRESS,"):
                parts = line.split(",")
                if len(parts) == 3:
                    try:
                        done = int(parts[1])
                        total = int(parts[2])
                        pct = (100.0 * done / total) if total > 0 else 0.0
                        print(
                            f"[collector] progress {done}/{total} ({pct:.1f}%)",
                            flush=True,
                        )
                    except ValueError:
                        print(f"[collector] {line}", flush=True)
                continue

            if line == "END":
                print("[collector] END received", flush=True)
                break

            if line.startswith("DATA,"):
                parts = line.split(",")
                if len(parts) != (2 + len(req.pins)):
                    raise SerialCollectionError(f"Malformed DATA line: {line}")

                sample_idx = int(parts[1])
                pin_values = [int(v) for v in parts[2:]]

                row = {"sample_index": sample_idx}
                for pin_num, value in zip(req.pins, pin_values):
                    row[f"A{pin_num}"] = value
                rows.append(row)

                # Extend deadline as long as data keeps arriving.
                deadline = time.time() + req.serial_timeout_seconds

        if not got_begin:
            raise SerialCollectionError("Did not receive BEGIN from Arduino")

    if len(rows) != req.sample_count:
        raise SerialCollectionError(
            f"Expected {req.sample_count} samples, got {len(rows)}"
        )

    print(f"[collector] Collected {len(rows)} samples successfully", flush=True)
    return pd.DataFrame(rows).sort_values("sample_index").reset_index(drop=True)
