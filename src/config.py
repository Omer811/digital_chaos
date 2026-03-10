from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    pass


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    required_top = ["arduino", "sampling", "processing", "output"]
    for key in required_top:
        if key not in cfg:
            raise ConfigError(f"Missing top-level config section: {key}")

    return cfg
