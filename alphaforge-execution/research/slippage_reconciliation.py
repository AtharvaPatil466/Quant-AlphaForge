"""Realized-vs-simulated slippage reconciliation.

Reads the `orders` table from the execution SQLite database and compares
realized fill slippage (fill_price vs ref_price at submission) to what the
backtest cost model *predicted* for the same trade. Emits a report with:

- per-order realized slippage (bps) and simulated slippage (bps)
- distribution of fill-error = realized − simulated (bps)
- Kolmogorov-Smirnov test between the two distributions
- a daily-rollup chart of realized − simulated NAV impact

A live strategy whose realized-simulated fill error has a non-zero mean
is burning assumed alpha in execution. This report is the minimum
reconciliation a production quant signal needs.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path
from typing import List, Optional

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
OUT_DIR = THIS_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)


def load_orders(db_path: Path) -> List[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT order_id, date, ticker, side, quantity, fill_price,
                  fill_quantity, status, slippage_bps, tx_cost,
                  submitted_at, filled_at
           FROM orders
           WHERE status = 'FILLED'
           ORDER BY date ASC, submitted_at ASC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _percentile(a: np.ndarray, q: float) -> float:
    if len(a) == 0:
        return float("nan")
    return float(np.quantile(a, q))


def reconcile(db_path: Path, simulated_bps: float) -> dict:
    """Compare realized to simulated slippage.

    Args:
        db_path:       path to execution SQLite database.
        simulated_bps: the backtest's assumed slippage in bps. Typically
                       configs/execution_config.yaml :: broker.slippage_bps.

    Returns a summary dict; also writes JSON + markdown.
    """
    orders = load_orders(db_path)
    if not orders:
        return {"n_orders": 0, "note": "no filled orders found"}

    realized = np.array([(o["slippage_bps"] or 0.0) for o in orders], dtype=float)
    simulated = np.full_like(realized, simulated_bps)
    fill_error = realized - simulated

    ks_stat, ks_p = _ks_two_sample(realized, simulated)

    # Daily NAV impact from fill error
    by_date: dict[str, float] = {}
    for o, err in zip(orders, fill_error):
        gross_dollars = (o["fill_price"] or 0.0) * (o["fill_quantity"] or 0.0)
        by_date.setdefault(o["date"], 0.0)
        # err is bps of underperformance; convert to $ drag
        by_date[o["date"]] += gross_dollars * err * 1e-4

    daily_drag = sorted(by_date.items())
    cum_drag = 0.0
    drag_rows: List[dict] = []
    for d, drag in daily_drag:
        cum_drag += drag
        drag_rows.append({"date": d, "daily_drag_usd": drag, "cum_drag_usd": cum_drag})

    summary = {
        "n_orders": int(len(orders)),
        "simulated_bps": float(simulated_bps),
        "realized_bps_stats": {
            "mean": float(realized.mean()),
            "median": _percentile(realized, 0.5),
            "p95": _percentile(realized, 0.95),
            "p99": _percentile(realized, 0.99),
        },
        "fill_error_bps_stats": {
            "mean": float(fill_error.mean()),
            "median": _percentile(fill_error, 0.5),
            "std": float(fill_error.std(ddof=1)) if len(fill_error) > 1 else 0.0,
            "p05": _percentile(fill_error, 0.05),
            "p95": _percentile(fill_error, 0.95),
        },
        "ks_two_sample": {"statistic": ks_stat, "p_value": ks_p},
        "daily_drag": drag_rows,
        "cumulative_drag_usd": float(cum_drag),
    }
    (OUT_DIR / "slippage_reconciliation.json").write_text(
        json.dumps(summary, indent=2, default=float)
    )
    _write_markdown(summary)
    return summary


def _ks_two_sample(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov with a normal-approx p-value.
    Self-contained to avoid a scipy dependency in the execution system.
    """
    if len(a) < 5 or len(b) < 5:
        return 0.0, 1.0
    combined = np.concatenate([a, b])
    cdf_a = np.searchsorted(np.sort(a), combined, side="right") / len(a)
    cdf_b = np.searchsorted(np.sort(b), combined, side="right") / len(b)
    d = float(np.max(np.abs(cdf_a - cdf_b)))
    n_e = (len(a) * len(b)) / (len(a) + len(b))
    # Asymptotic Kolmogorov distribution: p ≈ 2 * sum_{k=1..∞} (-1)^{k-1} e^{-2 k² λ²}
    # with λ = (√n_e + 0.12 + 0.11/√n_e) * d (Stephens 1970 correction).
    lam = (math.sqrt(n_e) + 0.12 + 0.11 / math.sqrt(n_e)) * d
    p = 2.0 * sum((-1) ** (k - 1) * math.exp(-2 * k * k * lam * lam) for k in range(1, 101))
    p = max(0.0, min(1.0, p))
    return d, p


def _write_markdown(s: dict) -> None:
    lines = []
    A = lines.append
    A("# Execution — Realized vs Simulated Slippage Reconciliation")
    A("")
    A(f"Filled orders analyzed: **{s['n_orders']:,}**. "
      f"Backtest assumption: **{s['simulated_bps']:.1f} bps**.")
    A("")
    A("## Realized Slippage Distribution")
    A("")
    r = s["realized_bps_stats"]
    A(f"- Mean: **{r['mean']:.2f} bps** · Median: {r['median']:.2f} · "
      f"p95: {r['p95']:.2f} · p99: {r['p99']:.2f}.")
    A("")
    A("## Fill Error = Realized − Simulated (bps)")
    A("")
    e = s["fill_error_bps_stats"]
    A(f"- Mean: **{e['mean']:.2f} bps**  "
      f"(positive = realized *worse* than simulated; negative = you got the better price)")
    A(f"- Median: {e['median']:.2f} · SD: {e['std']:.2f}")
    A(f"- 5th–95th percentile: [{e['p05']:.2f}, {e['p95']:.2f}]")
    A("")
    ks = s["ks_two_sample"]
    A(f"Kolmogorov-Smirnov two-sample test (realized vs simulated constant): "
      f"D = {ks['statistic']:.3f}, p = {ks['p_value']:.3g}. "
      "p < 0.05 means the live slippage distribution does not match the backtest assumption.")
    A("")
    A(f"## Cumulative NAV Drag From Fill Error: **${s['cumulative_drag_usd']:,.2f}**")
    A("")
    A("A non-zero, persistent drag means your backtest P&L is systematically "
      "over-reported. Feed the realized distribution back into the cost model "
      "(e.g., set `broker.slippage_bps` to the realized median).")
    (OUT_DIR / "slippage_reconciliation.md").write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="Slippage reconciliation report.")
    ap.add_argument("--db", default=str(THIS_DIR.parent / "alphaforge_execution.db"))
    ap.add_argument("--simulated-bps", type=float, default=5.0,
                    help="Backtest's assumed slippage bps (configs default: 5).")
    args = ap.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found at {db_path}. Run a backtest or paper-trading loop first.")
        return
    out = reconcile(db_path, args.simulated_bps)
    print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
