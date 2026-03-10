from __future__ import annotations

import argparse
import json

from src.config import load_config
from src.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Arduino analog noise, run PCA, and save 3D Plotly visualization"
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to JSON config file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    results = run_pipeline(cfg)

    print("Pipeline complete")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
