"""Assumed-vs-realized transaction-cost calibration.

Closes the cost-model feedback loop. Every backtest in this project *assumes*
transaction costs (a flat `slippage_bps`, the square-root market-impact
coefficient `k` in `alphaforge-python/research/cost_model.py`, Corwin-Schultz
spreads, borrow). The live paper-trading loop *recorded* realized fills in the
`orders` SQLite table. This module measures the gap.

It produces a single load-bearing number — the **cost multiplier** =
realized_slippage_bps / assumed_slippage_bps — and, where the recorded fields
allow, an estimate of the realized square-root impact coefficient `k`. It is
explicit about identifiability: with only `slippage_bps` and no per-order
participation (trade_$ / ADV_$) recorded, `k` is NOT separately identifiable
from the flat-bps term, and the module says so rather than guessing.

DATA PROVENANCE (critical, read before trusting any number)
-----------------------------------------------------------
Two kinds of rows live in the `orders` table and they are NOT the same thing:

1. **Simulated paper-broker fills** (`execution/paper_broker.py`). The broker
   APPLIES the assumed slippage and then writes that same constant back to
   `slippage_bps` (see `paper_broker.py:83` — `order.slippage_bps =
   self._slippage_bps`). These rows are the ASSUMPTION echoed back; their
   realized slippage is identically the simulated bps. They are NOT realized
   market fills and calibrating against them is circular (multiplier ≡ 1.0 by
   construction). `backtest.db` and `replay_20d.db` are of this kind.

2. **Live broker fills** (`execution/alpaca_broker.py`). Here `slippage_bps` is
   MEASURED as `(fill_price - ref_price) / ref_price * 1e4` against the last
   price pushed to the broker (`alpaca_broker.py:151-161`). These are genuine
   realized fills. `live_trading.db` and `live_marl.db` are of this kind.

`classify_db()` labels each database `simulated` / `live` / `mixed` by whether
its filled-order slippage values are all pinned to a single constant. Only
`live`/`mixed` databases yield a meaningful multiplier; `simulated` databases
are reported with `multiplier == 1.0` and a circular-by-construction warning.

REF-PRICE STALENESS CAVEAT
--------------------------
The live `slippage_bps` is measured against `ref_price = self._prices.get(
ticker)` — the last close the engine pushed in. If that close is from the prior
session, the figure conflates overnight/intraday price DRIFT with execution
slippage. Per-order participation/volume is NOT recorded, so we cannot net out
drift or fit `k`. Treat large live multipliers as an UPPER BOUND on true
execution slippage. This is flagged in the output.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# Reuse the existing loader so the two reports read the orders table identically.
from research.slippage_reconciliation import load_orders

THIS_DIR = Path(__file__).resolve().parent
OUT_DIR = THIS_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

# Assumed cost parameters this project's backtests run with.
# slippage: configs/execution_config.yaml :: broker.slippage_bps (default 5)
# k_bps:    alphaforge-python/research/cost_model.py :: SquareRootImpactModel.k_bps
DEFAULT_ASSUMED_SLIPPAGE_BPS = 5.0
ASSUMED_IMPACT_K_BPS = 15.0


# ─── core math (pure; unit-tested in isolation) ──────────────────────────────

def slippage_distribution(realized_bps: np.ndarray) -> dict:
    """Median / mean / p90 / p10 / p99 / std of a realized-slippage array (bps)."""
    a = np.asarray(realized_bps, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return {"n": 0, "median": float("nan"), "mean": float("nan"),
                "p10": float("nan"), "p90": float("nan"), "p99": float("nan"),
                "std": float("nan"), "min": float("nan"), "max": float("nan")}
    return {
        "n": int(a.size),
        "median": float(np.median(a)),
        "mean": float(a.mean()),
        "p10": float(np.quantile(a, 0.10)),
        "p90": float(np.quantile(a, 0.90)),
        "p99": float(np.quantile(a, 0.99)),
        "std": float(a.std(ddof=1)) if a.size > 1 else 0.0,
        "min": float(a.min()),
        "max": float(a.max()),
    }


def cost_multiplier(realized_bps: np.ndarray, assumed_bps: float,
                    statistic: str = "median") -> float:
    """The headline calibration number: realized / assumed slippage ratio.

    `statistic` selects which central value of the realized distribution to use
    ("median" is robust to the handful of extreme live fills; "mean" matches the
    dollar-weighted drag). Returns NaN if assumed_bps is non-positive or no
    finite realized values exist.

    Sign convention: realized slippage is stored as bps of underperformance
    (positive = worse than reference). A multiplier of 2.0 means realized
    slippage was twice the backtest assumption; backtests under-charged by 2x.
    """
    a = np.asarray(realized_bps, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0 or assumed_bps <= 0:
        return float("nan")
    central = float(np.median(a)) if statistic == "median" else float(a.mean())
    return central / float(assumed_bps)


def implied_impact_k(realized_bps: np.ndarray,
                     participation: Optional[np.ndarray]) -> dict:
    """Estimate the square-root impact coefficient k from realized fills.

    The square-root model is impact_bps = k * sqrt(participation), so
    k = realized_bps / sqrt(participation). This is ONLY identifiable when
    per-order participation (trade_$ / ADV_$) is recorded. The `orders` table
    schema (storage/database.py) has no volume/ADV column, so in practice
    `participation` is None and k is NOT identifiable — we say so explicitly.
    """
    a = np.asarray(realized_bps, dtype=float)
    if participation is None:
        return {
            "identifiable": False,
            "k_bps": None,
            "reason": ("orders table records no per-order participation "
                       "(trade_$/ADV_$); k is not separable from the flat-bps "
                       "term. Fall back to the bps cost multiplier."),
        }
    p = np.asarray(participation, dtype=float)
    mask = np.isfinite(a) & np.isfinite(p) & (p > 0)
    if mask.sum() == 0:
        return {"identifiable": False, "k_bps": None,
                "reason": "no rows with positive participation"}
    k_each = a[mask] / np.sqrt(p[mask])
    return {
        "identifiable": True,
        "k_bps": float(np.median(k_each)),
        "k_bps_mean": float(k_each.mean()),
        "n": int(mask.sum()),
        "assumed_k_bps": ASSUMED_IMPACT_K_BPS,
        "k_multiplier": float(np.median(k_each)) / ASSUMED_IMPACT_K_BPS,
    }


# ─── database classification + loading ───────────────────────────────────────

def classify_db(orders: List[dict], tol: float = 1e-6) -> str:
    """Label a set of filled orders 'simulated', 'live', or 'empty'.

    The paper broker writes a single constant slippage_bps to every fill, so a
    database whose filled-order slippage values are all identical is simulated
    (the assumption echoed back, multiplier ≡ 1.0 by construction). Any spread
    in the values implies measured live fills.
    """
    vals = [o["slippage_bps"] for o in orders
            if o.get("status") == "FILLED" and o["slippage_bps"] is not None]
    if not vals:
        return "empty"
    arr = np.asarray(vals, dtype=float)
    return "simulated" if (arr.max() - arr.min()) <= tol else "live"


def by_ticker_distribution(orders: List[dict]) -> Dict[str, dict]:
    """Per-ticker realized-slippage distribution (only where n is non-trivial)."""
    buckets: Dict[str, List[float]] = defaultdict(list)
    for o in orders:
        if o.get("status") == "FILLED" and o["slippage_bps"] is not None:
            buckets[o["ticker"]].append(float(o["slippage_bps"]))
    return {tk: slippage_distribution(np.asarray(v)) for tk, v in buckets.items()}


# ─── calibration driver over one or more databases ──────────────────────────

def calibrate(db_paths: List[Path], assumed_bps: float) -> dict:
    """Calibrate realized-vs-assumed cost across one or more order databases.

    Returns a dict with per-database classification + stats, a pooled-live
    distribution, the cost multiplier (median and mean), and the k-identifiability
    verdict. Also writes JSON + markdown to research/out/.
    """
    per_db = []
    pooled_live: List[float] = []
    for p in db_paths:
        path = Path(p)
        if not path.exists():
            per_db.append({"db": str(path), "exists": False})
            continue
        orders = load_orders(path)
        kind = classify_db(orders)
        realized = np.asarray(
            [o["slippage_bps"] for o in orders if o["slippage_bps"] is not None],
            dtype=float,
        )
        entry = {
            "db": str(path),
            "exists": True,
            "kind": kind,
            "n_filled": int(len(orders)),
            "slippage_stats": slippage_distribution(realized),
            "multiplier_median": cost_multiplier(realized, assumed_bps, "median"),
            "multiplier_mean": cost_multiplier(realized, assumed_bps, "mean"),
        }
        if kind == "simulated":
            entry["warning"] = ("simulated paper-broker fills: slippage_bps is "
                                "the assumption echoed back; multiplier is 1.0 "
                                "by construction and not a calibration.")
        elif kind == "live":
            entry["by_ticker"] = by_ticker_distribution(orders)
            pooled_live.extend(realized.tolist())
        per_db.append(entry)

    pooled_arr = np.asarray(pooled_live, dtype=float)
    pooled_stats = slippage_distribution(pooled_arr)
    has_live = pooled_arr.size > 0

    summary = {
        "assumed_slippage_bps": float(assumed_bps),
        "assumed_impact_k_bps": ASSUMED_IMPACT_K_BPS,
        "databases": per_db,
        "live_fills_found": bool(has_live),
        "n_live_fills": int(pooled_arr.size),
        "pooled_live_slippage_stats": pooled_stats,
        "cost_multiplier": {
            "median": cost_multiplier(pooled_arr, assumed_bps, "median") if has_live else None,
            "mean": cost_multiplier(pooled_arr, assumed_bps, "mean") if has_live else None,
            "definition": "realized_slippage_bps / assumed_slippage_bps",
        },
        # k is structurally unidentifiable from the recorded fields.
        "impact_k_calibration": implied_impact_k(pooled_arr, participation=None),
        "ref_price_staleness_caveat": (
            "Live slippage_bps is measured vs the last close pushed to the "
            "broker, not the quote at submission. It conflates price drift with "
            "execution slippage and is an UPPER BOUND on true slippage."
        ),
    }
    (OUT_DIR / "cost_calibration.json").write_text(
        json.dumps(summary, indent=2, default=float)
    )
    _write_markdown(summary)
    return summary


# ─── markdown ────────────────────────────────────────────────────────────────

def _fmt(x, nd=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _write_markdown(s: dict) -> None:
    L: List[str] = []
    A = L.append
    A("# Execution — Assumed vs Realized Cost Calibration")
    A("")
    A("Closes the cost-model feedback loop: backtests across AlphaForge *assume* "
      "transaction costs; the live paper loop *recorded* fills. This report "
      "measures the gap and emits the headline **cost multiplier** "
      "(realized / assumed slippage).")
    A("")

    if not s["live_fills_found"]:
        A("> **NO LIVE FILLS FOUND.** All inspected databases are simulated "
          "paper-broker fills, where `slippage_bps` is the assumption echoed "
          "back (multiplier 1.0 by construction). The calibration MACHINERY is "
          "validated on fixtures; the multiplier below is "
          "**methodology-validated-on-fixtures, pending live fills.**")
        A("")

    A(f"Assumed slippage: **{_fmt(s['assumed_slippage_bps'],1)} bps** "
      f"(configs/execution_config.yaml). "
      f"Assumed impact k: **{_fmt(s['assumed_impact_k_bps'],1)} bps/√participation** "
      f"(cost_model.py).")
    A("")

    A("## Per-Database Provenance")
    A("")
    A("| Database | Kind | Filled | Median bps | Mean bps | p90 bps | Mult (median) |")
    A("|---|---|---|---|---|---|---|")
    for d in s["databases"]:
        if not d.get("exists"):
            A(f"| {Path(d['db']).name} | MISSING | – | – | – | – | – |")
            continue
        st = d["slippage_stats"]
        A(f"| {Path(d['db']).name} | {d['kind']} | {d['n_filled']} | "
          f"{_fmt(st['median'])} | {_fmt(st['mean'])} | {_fmt(st['p90'])} | "
          f"{_fmt(d['multiplier_median'])} |")
    A("")
    A("`simulated` = paper broker wrote the assumption back (circular; "
      "multiplier ≡ 1.0). `live` = Alpaca-measured realized fills (the only "
      "rows that calibrate anything).")
    A("")

    A("## Pooled Live-Fill Calibration")
    A("")
    if s["live_fills_found"]:
        ps = s["pooled_live_slippage_stats"]
        cm = s["cost_multiplier"]
        A(f"Pooled live fills: **{s['n_live_fills']}**.")
        A(f"- Realized slippage — median **{_fmt(ps['median'])} bps**, "
          f"mean **{_fmt(ps['mean'])} bps**, p90 {_fmt(ps['p90'])}, "
          f"range [{_fmt(ps['min'])}, {_fmt(ps['max'])}].")
        A(f"- **Cost multiplier (median): {_fmt(cm['median'])}×** · "
          f"(mean): {_fmt(cm['mean'])}×.")
        A("")
        A(f"> {s['ref_price_staleness_caveat']}")
    else:
        A("No live fills pooled. See fixtures-validation note above.")
    A("")

    A("## Square-Root Impact Coefficient (k)")
    A("")
    kc = s["impact_k_calibration"]
    if kc["identifiable"]:
        A(f"- Estimated k: **{_fmt(kc['k_bps'])} bps/√participation** "
          f"(assumed {ASSUMED_IMPACT_K_BPS}); k-multiplier {_fmt(kc['k_multiplier'])}×.")
    else:
        A(f"- **k is NOT identifiable.** {kc['reason']}")
    A("")

    A("## What This Implies")
    A("")
    A("- The headline number for re-stating verdicts is the **bps cost "
      "multiplier**, not k (k can't be separated from the recorded fields).")
    A("- A multiplier > 1 means backtests under-charged slippage; net Sharpes "
      "in those studies were optimistic and should be discounted accordingly.")
    A("- A multiplier ≈ 1 (or only simulated DBs present) means the assumption "
      "cannot be falsified from the recorded live evidence yet.")
    A("- This figure feeds the cost-boundedness re-statement in "
      "`COST_BOUNDEDNESS_RESTATEMENT.md`.")
    (OUT_DIR / "cost_calibration.md").write_text("\n".join(L))


def main():
    default_dbs = [
        THIS_DIR.parent / "live_trading.db",
        THIS_DIR.parent / "live_marl.db",
        THIS_DIR.parent / "backtest.db",
        THIS_DIR.parent / "replay_20d.db",
    ]
    ap = argparse.ArgumentParser(description="Assumed-vs-realized cost calibration.")
    ap.add_argument("--db", action="append", default=None,
                    help="Order DB path (repeatable). Defaults to all known DBs.")
    ap.add_argument("--assumed-bps", type=float, default=DEFAULT_ASSUMED_SLIPPAGE_BPS,
                    help="Backtest's assumed slippage bps (configs default: 5).")
    args = ap.parse_args()
    dbs = [Path(d) for d in (args.db or default_dbs)]
    out = calibrate(dbs, args.assumed_bps)
    print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
