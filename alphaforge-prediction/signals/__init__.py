"""Phase 1 signal layer for substrate #10 (Kalshi favorite-longshot bias).

`flb.py` enumerates the pre-committed trial set
(`research/PREDICTION_MARKETS_DESIGN.md` §4) and provides the calendar-midpoint
IS/OOS split. It computes NO calibration statistic of its own — those come from
the canonical `afgauntlet.binary` module, consumed by `research/run_phase1.py`.

`strategy.py` is the Phase 2 rule layer (`§9`): a frozen-able `RuleSpec` plus the
pure `select_orders` function that turns a snapshot of currently-open Kalshi
markets into intended paper entries for the forward paper-trade harness.
"""
from __future__ import annotations

from .strategy import (  # noqa: E402,F401
    DEFAULT_RULE_SPEC,
    BucketRule,
    PaperOrder,
    RuleSpec,
    extract_open_market,
    fee_dollars,
    select_orders,
)

__all__ = [
    "BucketRule",
    "RuleSpec",
    "PaperOrder",
    "DEFAULT_RULE_SPEC",
    "select_orders",
    "extract_open_market",
    "fee_dollars",
]
