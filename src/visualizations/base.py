from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class VisualizationContext:
    output_dir: Path


class BaseVisualizer:
    name: str = "base"

    def render(self, data: pd.DataFrame, ctx: VisualizationContext) -> list[Path]:
        raise NotImplementedError
