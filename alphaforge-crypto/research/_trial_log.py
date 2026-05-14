"""Trial-log appender for the carry study pre-commit discipline.

Every IS evaluation, AND every parameter considered-but-not-run, appends an
entry here. The trial_log.json SHA at IS completion becomes the second
pre-commit anchor (alongside the design-doc SHA).

Append-only. No edits-after-OOS. The git commit is what freezes the count.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def trial_log_path() -> Path:
    here = Path(__file__).resolve().parent
    p = here / "out" / "carry_study" / "trial_log.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_existing() -> list[dict]:
    path = trial_log_path()
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _save(entries: list[dict]) -> None:
    trial_log_path().write_text(json.dumps(entries, indent=2))


def log_trial(
    parameter: str,
    value: Any,
    *,
    rationale: str,
    scope: str = "IS-only",
    is_metric: dict | None = None,
    considered_alternatives: list[Any] | None = None,
) -> int:
    """Append a trial entry. Returns the trial_id.

    Args:
        parameter: name of the parameter being committed/varied
            (e.g. "lookback_K", "bucket_count", "embargo_events").
        value: the value being recorded for this trial.
        rationale: why this value, or why this parameter was considered.
        scope: "IS-only" (default) or "design-locked-no-sweep".
        is_metric: optional dict of IS-level metrics measured under this trial.
            None = not run, just considered.
        considered_alternatives: optional list of alternative values that were
            on the table. Each alternative gets its own trial entry too (the
            caller is responsible for logging them separately if they want
            them in the count).
    """
    entries = _load_existing()
    entry = {
        "trial_id": len(entries) + 1,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "parameter": parameter,
        "value": value,
        "rationale": rationale,
        "scope": scope,
        "is_metric": is_metric,
    }
    if considered_alternatives is not None:
        entry["considered_alternatives"] = considered_alternatives
    entries.append(entry)
    _save(entries)
    return entry["trial_id"]


def trial_count() -> int:
    return len(_load_existing())


def all_trials() -> list[dict]:
    return _load_existing()
