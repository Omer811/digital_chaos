from __future__ import annotations

from typing import Any

import pandas as pd


def lag1_abs_correlation(samples_df: pd.DataFrame, feature_columns: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in feature_columns:
        prev = samples_df[col].shift(1).iloc[1:]
        curr = samples_df[col].iloc[1:]
        corr = curr.corr(prev)
        if pd.isna(corr):
            out[col] = 1.0
        else:
            out[col] = abs(float(corr))
    return out


def summarize_correlation(abs_corr_by_col: dict[str, float], threshold: float) -> dict[str, Any]:
    max_abs = max(abs_corr_by_col.values()) if abs_corr_by_col else 1.0
    return {
        "lag1_abs_corr_by_pin": abs_corr_by_col,
        "max_lag1_abs_corr": max_abs,
        "threshold": threshold,
        "passes_threshold": max_abs <= threshold,
    }
