"""Training logger: records generation stats to JSON Lines file."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from evolution.evolutionary_engine import GenerationStats


class TrainingLogger:
    """Logs training metrics to a JSONL file and keeps in-memory history."""

    def __init__(self, log_path: str | None = None):
        self.log_path = log_path
        self.entries: List[Dict[str, Any]] = []

        if log_path:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    def log_generation(self, stats: GenerationStats, extra: Dict[str, Any] | None = None) -> None:
        """Log a generation's stats."""
        entry = {
            "timestamp": time.time(),
            "generation": stats.generation,
            "best_fitness": stats.best_fitness,
            "mean_fitness": stats.mean_fitness,
            "fitness_std": stats.fitness_std,
            "sigma": stats.sigma,
            "best_agent_id": stats.best_agent_id,
        }
        if extra:
            entry.update(extra)

        self.entries.append(entry)

        if self.log_path:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self.entries)

    def latest(self) -> Dict[str, Any] | None:
        return self.entries[-1] if self.entries else None
