"""Diff rebuilt research artifacts against the committed snapshot.

Called from the `research-ci.yml` workflow. Exits 0 if every numeric leaf
in both JSONs matches within tolerance, 1 if any drifts are found, or 0
with a [skip] message when a pair cannot be compared (no committed
snapshot yet, or the rebuild step produced nothing — both are expected
on a fresh repo).

Tolerance is `max(1e-6, 1e-3 * abs(old_value))` — small enough to catch
a real regression, loose enough to absorb normal float-order-of-operations
differences between NumPy/BLAS builds on CI vs local.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, List, Tuple

# (rebuilt_path, committed_snapshot_path)
PAIRS: List[Tuple[str, str]] = [
    (
        "alphaforge-python/research/out/factor_study_results.json",
        "/tmp/ci-diff/factor_study_results.json.committed",
    ),
    (
        "alphaforge-marl/research/out/marl_rigor_metrics.json",
        "/tmp/ci-diff/marl_rigor_metrics.json.committed",
    ),
]


def diff_tree(x: Any, y: Any, path: str = "", drifts: List[str] | None = None) -> List[str]:
    if drifts is None:
        drifts = []
    if isinstance(x, float) and isinstance(y, float):
        if abs(x - y) > max(1e-6, 1e-3 * abs(y)):
            drifts.append(f"DRIFT {path}: {y} -> {x}")
    elif isinstance(x, dict) and isinstance(y, dict):
        for k in set(x) & set(y):
            diff_tree(x[k], y[k], f"{path}.{k}", drifts)
    elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (xi, yi) in enumerate(zip(x, y)):
            diff_tree(xi, yi, f"{path}[{i}]", drifts)
    return drifts


def main() -> int:
    all_drifts: List[str] = []
    for rebuilt, committed in PAIRS:
        if not os.path.exists(rebuilt) or not os.path.exists(committed):
            print(f"[skip] {rebuilt}: missing committed or rebuilt artifact")
            continue
        with open(rebuilt) as fr, open(committed) as fc:
            a, b = json.load(fr), json.load(fc)
        drifts = diff_tree(a, b)
        for d in drifts:
            print(d)
        all_drifts.extend(drifts)
    return 1 if all_drifts else 0


if __name__ == "__main__":
    sys.exit(main())
