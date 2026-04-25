"""Load execution config from YAML."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml


_DEFAULT_CONFIG = Path(__file__).parent / "configs" / "execution_config.yaml"


def load_config(path: str | None = None) -> Dict[str, Any]:
    p = Path(path) if path else _DEFAULT_CONFIG
    with open(p) as f:
        return yaml.safe_load(f)


def get_tickers(cfg: Dict[str, Any]) -> List[str]:
    return cfg["universe"]["tickers"]
