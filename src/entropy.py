from __future__ import annotations

import hashlib
import zlib
from typing import Any

import pandas as pd


def _extract_lsb_bits(
    samples_df: pd.DataFrame, feature_columns: list[str], bits_per_value: int
) -> list[int]:
    bits: list[int] = []
    for _, row in samples_df[feature_columns].iterrows():
        for col in feature_columns:
            v = int(row[col])
            for bit_idx in range(bits_per_value):
                bits.append((v >> bit_idx) & 1)
    return bits


def _xor_fold(bits: list[int], group_size: int) -> list[int]:
    if group_size <= 1:
        return bits[:]
    out: list[int] = []
    for i in range(0, len(bits), group_size):
        group = bits[i : i + group_size]
        if len(group) < group_size:
            break
        x = 0
        for b in group:
            x ^= b
        out.append(x)
    return out


def _von_neumann_corrector(bits: list[int]) -> list[int]:
    out: list[int] = []
    for i in range(0, len(bits) - 1, 2):
        b1 = bits[i]
        b2 = bits[i + 1]
        if b1 == 0 and b2 == 1:
            out.append(0)
        elif b1 == 1 and b2 == 0:
            out.append(1)
    return out


def _bits_to_bytes(bits: list[int]) -> bytes:
    if not bits:
        return b""
    out = bytearray()
    cur = 0
    count = 0
    for b in bits:
        cur = (cur << 1) | b
        count += 1
        if count == 8:
            out.append(cur)
            cur = 0
            count = 0
    return bytes(out)


def _crc_mix(input_bytes: bytes, block_size: int, seed: int = 0) -> bytes:
    if block_size <= 0:
        return input_bytes
    out = bytearray()
    state = seed & 0xFFFFFFFF
    for i in range(0, len(input_bytes), block_size):
        block = input_bytes[i : i + block_size]
        if not block:
            continue
        state = zlib.crc32(block, state) & 0xFFFFFFFF
        out.extend(state.to_bytes(4, byteorder="big", signed=False))
    return bytes(out)


def _hash_blocks(
    input_bytes: bytes, block_size: int, algorithm: str, hash_partial_block: bool
) -> bytes:
    if block_size <= 0:
        return b""
    out = bytearray()
    for i in range(0, len(input_bytes), block_size):
        block = input_bytes[i : i + block_size]
        if len(block) < block_size and not hash_partial_block:
            break
        if algorithm == "sha1":
            out.extend(hashlib.sha1(block).digest())
        elif algorithm == "sha256":
            out.extend(hashlib.sha256(block).digest())
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")
    return bytes(out)


def _bit_balance(data: bytes) -> dict[str, float]:
    total_bits = len(data) * 8
    if total_bits == 0:
        return {"ones_ratio": 0.0, "zeros_ratio": 0.0}
    ones = sum(bin(b).count("1") for b in data)
    zeros = total_bits - ones
    return {
        "ones_ratio": ones / total_bits,
        "zeros_ratio": zeros / total_bits,
    }


def condition_entropy(
    samples_df: pd.DataFrame,
    feature_columns: list[str],
    cfg: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    bits_per_value = int(cfg.get("bits_per_adc_value", 1))
    xor_group_size = int(cfg.get("xor_group_size", 8))
    use_von_neumann = bool(cfg.get("use_von_neumann", True))
    use_crc_mixing = bool(cfg.get("use_crc_mixing", True))
    crc_block_bytes = int(cfg.get("crc_block_bytes", 32))
    use_hash_blocks = bool(cfg.get("use_hash_blocks", True))
    hash_block_bytes = int(cfg.get("hash_block_bytes", 32))
    hash_algorithm = str(cfg.get("hash_algorithm", "sha256")).lower()
    hash_partial_block = bool(cfg.get("hash_partial_block", True))

    raw_bits = _extract_lsb_bits(samples_df, feature_columns, bits_per_value)
    xor_bits = _xor_fold(raw_bits, xor_group_size)
    vn_bits = _von_neumann_corrector(xor_bits) if use_von_neumann else xor_bits
    stream = _bits_to_bytes(vn_bits)

    if use_crc_mixing:
        stream = _crc_mix(stream, crc_block_bytes)

    if use_hash_blocks:
        stream = _hash_blocks(
            stream, hash_block_bytes, hash_algorithm, hash_partial_block
        )

    report = {
        "settings": {
            "bits_per_adc_value": bits_per_value,
            "xor_group_size": xor_group_size,
            "use_von_neumann": use_von_neumann,
            "use_crc_mixing": use_crc_mixing,
            "crc_block_bytes": crc_block_bytes,
            "use_hash_blocks": use_hash_blocks,
            "hash_block_bytes": hash_block_bytes,
            "hash_algorithm": hash_algorithm,
            "hash_partial_block": hash_partial_block,
        },
        "counts": {
            "raw_bits": len(raw_bits),
            "after_xor_bits": len(xor_bits),
            "after_von_neumann_bits": len(vn_bits),
            "final_bytes": len(stream),
        },
        "bit_balance": _bit_balance(stream),
    }
    return stream, report
