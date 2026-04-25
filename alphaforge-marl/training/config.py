"""Load MARL config from YAML with attribute access."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml


@dataclass
class Config:
    """Flat config object built from YAML with dotted section access."""

    _data: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            return super().__getattribute__(key)
        d = self._data
        if key in d:
            v = d[key]
            return Config(_data=v) if isinstance(v, dict) else v
        raise AttributeError(f"Config has no key '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)


def load_config(path: str | None = None) -> Config:
    """Load config from YAML. Falls back to default_config.yaml."""
    if path is None:
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "configs",
            "default_config.yaml",
        )
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config(_data=data)
