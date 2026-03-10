from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px

from .base import BaseVisualizer, VisualizationContext


class Plotly3DScatterVisualizer(BaseVisualizer):
    name = "plotly_3d_scatter"

    def __init__(self, png_name: str, html_name: str) -> None:
        self.png_name = png_name
        self.html_name = html_name

    def render(self, data: pd.DataFrame, ctx: VisualizationContext) -> list[Path]:
        fig = px.scatter_3d(
            data,
            x="PC1",
            y="PC2",
            z="PC3",
            color="sample_index",
            color_continuous_scale="Viridis",
            opacity=0.8,
            title="Random Noise PCA Projection (3D)",
        )
        fig.update_traces(marker={"size": 4})

        png_path = ctx.output_dir / self.png_name
        html_path = ctx.output_dir / self.html_name

        fig.write_image(str(png_path), scale=2, width=1400, height=1000)
        fig.write_html(str(html_path), include_plotlyjs="cdn")

        return [png_path, html_path]
