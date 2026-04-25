"""MARL decision logger — writes one JSON line per trading day.

Every MARL trading decision gets a full audit trail: which action was selected,
what probabilities each action had, which agents contributed, what weights were
produced.  Written to marl_decisions.jsonl in the execution root.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

_LOG_PATH = Path(__file__).parent.parent / "marl_decisions.jsonl"


def log_marl_decision(
    *,
    date: str,
    action: int,
    action_name: str,
    action_probs: List[float],
    agent_weights: Dict[str, float],
    target_weights: Dict[str, float],
    obs_buffer_size: int,
    n_agents: int,
    extra: Dict[str, Any] | None = None,
) -> None:
    """Append one decision record to the JSONL log."""
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "trade_date": date,
        "action": action,
        "action_name": action_name,
        "action_probs": {
            name: round(p, 4)
            for name, p in zip(
                ["HOLD", "LONG_STRONG", "LONG_MILD", "SHORT_STRONG", "SHORT_MILD"],
                action_probs,
            )
        },
        "n_agents_in_ensemble": n_agents,
        "agent_weights": {k: round(v, 4) for k, v in agent_weights.items()},
        "target_weights": {k: round(v, 4) for k, v in target_weights.items()},
        "n_positions": len(target_weights),
        "gross_exposure": round(sum(abs(v) for v in target_weights.values()), 4),
        "obs_norm_buffer_size": obs_buffer_size,
    }
    if extra:
        record.update(extra)

    with open(_LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
