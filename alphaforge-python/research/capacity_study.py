"""Capacity curve + regime-conditional Sharpe + crowding diagnostics.

Given a factor long-short strategy, answers three questions:

1. **Capacity.** At what AUM does the square-root impact model eat all the
   alpha? We sweep AUM on a log grid and report net Sharpe, annualized
   return, and max-drawdown at each step — the "capacity curve".

2. **Regime dependency.** Conditional Sharpe within realized-vol regimes
   (low, mid, high) defined by the universe's rolling 21-day realized
   volatility on the equal-weight benchmark. Confidence intervals via
   stationary bootstrap within each regime.

3. **Crowding proxy (OHLCV-only).** Two diagnostics:
   - Sharpe decay: rolling 252-day Sharpe, plus its recent-vs-historical
     ratio. A crowded factor shows trailing Sharpe well below historical.
   - Own-return autocorrelation: strong negative AC(5) on the factor's
     own daily return suggests crowded-exit reversal.

Output:
   research/out/capacity_report.md
   research/out/capacity_results.json
   research/out/capacity_curve.csv
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from data.market.loader import MarketDataLoader
from data.market.universe import ALL_REAL_TICKERS
from research.cost_model import (
    HonestCostModel, SquareRootImpactModel, BorrowCostTable, corwin_schultz_spread,
)

OUT_DIR = THIS_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

STUDY_START = "2016-01-04"
STUDY_END = "2025-12-31"
HOLDING_PERIOD_DAYS = 21
N_QUINTILES = 5
ADV_WINDOW = 20
AUM_GRID = [1e6, 5e6, 1e7, 2.5e7, 5e7, 1e8, 2.5e8, 5e8, 1e9, 2.5e9, 1e10]
BOOT_REPS = 1000
BOOT_BLOCKS = 21


def load_panel() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (close, volume, high, low) DataFrames aligned on common index."""
    loader = MarketDataLoader()
    history: Dict[str, pd.DataFrame] = {}
    for tk in ALL_REAL_TICKERS:
        try:
            df = loader.load_ticker(tk, start_date=STUDY_START, end_date=STUDY_END)
        except Exception:
            continue
        if len(df) >= 252 * 3:
            history[tk] = df
    idx = None
    for df in history.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    for k in list(history):
        history[k] = history[k].loc[idx]
    close = pd.DataFrame({t: df["Adj Close"] for t, df in history.items()})
    volume = pd.DataFrame({t: df["Volume"] for t, df in history.items()})
    high = pd.DataFrame({t: df["High"] for t, df in history.items()})
    low = pd.DataFrame({t: df["Low"] for t, df in history.items()})
    close = close.dropna(axis=1, how="all").ffill(limit=2)
    for frame in (volume, high, low):
        frame.reindex_like(close).ffill(limit=2)
    volume = volume.reindex_like(close).ffill(limit=2)
    high = high.reindex_like(close).ffill(limit=2)
    low = low.reindex_like(close).ffill(limit=2)
    valid = close.notna().all(axis=0) & volume.notna().all(axis=0)
    close = close.loc[:, valid]
    volume = volume.loc[:, valid]
    high = high.loc[:, valid]
    low = low.loc[:, valid]
    return close, volume, high, low


def build_momentum_panel(close: pd.DataFrame) -> pd.DataFrame:
    """12-1 momentum (JS parity)."""
    return (close.shift(21) - close.shift(252)) / close.shift(252)


def ann_sharpe(r: pd.Series) -> float:
    if len(r) < 30 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(252))


def ann_return(r: pd.Series) -> float:
    nav = (1 + r).prod()
    if nav <= 0 or len(r) == 0:
        return 0.0
    return float(nav ** (252 / len(r)) - 1)


def max_drawdown(r: pd.Series) -> float:
    nav = (1 + r).cumprod()
    peak = nav.cummax()
    return float(((nav - peak) / peak).min())


def stationary_bootstrap_sharpe(r: np.ndarray, reps: int = BOOT_REPS,
                                mean_block: int = BOOT_BLOCKS, seed: int = 0) -> Dict[str, float]:
    rng = np.random.default_rng(seed)
    n = len(r)
    if n < 30:
        return {"mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}
    p = 1.0 / mean_block
    out = np.empty(reps)
    for b in range(reps):
        idxs = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        for k in range(n):
            if k > 0 and rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n if k > 0 else i
            idxs[k] = i
        sample = r[idxs]
        sd = sample.std(ddof=1)
        out[b] = (sample.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    return {
        "mean": float(out.mean()),
        "ci_lo": float(np.quantile(out, 0.025)),
        "ci_hi": float(np.quantile(out, 0.975)),
        "p_positive": float((out > 0).mean()),
    }


def run_backtest_with_aum(
    factor: pd.DataFrame,
    close: pd.DataFrame,
    volume: pd.DataFrame,
    spread_half_bps: pd.DataFrame,
    aum_dollar: float,
    cost_model: HonestCostModel,
) -> Dict[str, object]:
    """Long-short quintile backtest with honest AUM-dependent costs.

    Portfolio: long top quintile equal-weighted, short bottom quintile.
    Weights target ±100% gross leverage each side (net 0). AUM scales the
    dollar trades that feed into the square-root impact model.
    """
    f = factor.reindex_like(close)
    first_valid = f.dropna(how="all").index.min()
    dates = close.loc[first_valid:].index
    rebal_dates = dates[::HOLDING_PERIOD_DAYS]
    rebal_set = set(rebal_dates)

    cur_long = pd.Series(0.0, index=close.columns)
    cur_short = pd.Series(0.0, index=close.columns)

    adv_dollar = (close * volume).rolling(ADV_WINDOW).mean()

    daily_rets = close.pct_change().fillna(0.0)
    gross_ret_series = pd.Series(0.0, index=dates)
    cost_dollar_series = pd.Series(0.0, index=dates)
    borrow_dollar_series = pd.Series(0.0, index=dates)
    nav = aum_dollar  # track dollar NAV for borrow/cost accounting
    turnover_list: List[float] = []

    for i, dt in enumerate(dates):
        # Step 1: accrue today's gross return on yesterday's book
        if i > 0:
            gross_today = (cur_long * daily_rets.loc[dt]).sum() \
                        - (cur_short * daily_rets.loc[dt]).sum()
            gross_ret_series.loc[dt] = float(gross_today)
            short_notional = -cur_short * nav
            borrow_today = cost_model.holding_borrow_cost_dollars(short_notional, days=1)
            borrow_dollar_series.loc[dt] = float(borrow_today.sum())

        # Step 2: rebalance if scheduled (trade cost booked to today)
        if dt in rebal_set and dt in f.index and f.loc[dt].notna().sum() >= 2 * N_QUINTILES:
            scores = f.loc[dt].dropna()
            ranked = scores.sort_values()
            q_size = len(ranked) // N_QUINTILES
            bot = ranked.index[:q_size]
            top = ranked.index[-q_size:]
            new_long = pd.Series(0.0, index=close.columns)
            new_short = pd.Series(0.0, index=close.columns)
            new_long.loc[top] = 1.0 / len(top)
            new_short.loc[bot] = 1.0 / len(bot)

            # Turnover BEFORE updating cur_*
            turnover_list.append(float((new_long - cur_long).abs().sum()
                                       + (new_short - cur_short).abs().sum()))

            # Per-ticker dollar trade is |Δw_long| + |Δw_short| (legs net zero
            # notional so their trades stack when the same name flips sides).
            trade_total_dollar = ((new_long - cur_long).abs()
                                  + (new_short - cur_short).abs()) * nav

            adv_today = adv_dollar.loc[dt].fillna(1e9)
            spread_today = (spread_half_bps.loc[dt]
                            if dt in spread_half_bps.index else None)
            cost = cost_model.rebalance_cost_dollars(
                trade_total_dollar, adv_today, spread_today
            )
            cost_dollar_series.loc[dt] = float(cost.sum())
            cur_long, cur_short = new_long, new_short

        # Step 3: update NAV (compound and deduct today's cost bucket)
        today_cost = cost_dollar_series.loc[dt] + borrow_dollar_series.loc[dt]
        nav = max(nav * (1.0 + float(gross_ret_series.loc[dt])) - today_cost, 1.0)

    # Trim to post-first-rebal window
    if rebal_dates.empty:
        return {"net": pd.Series(dtype=float), "gross": pd.Series(dtype=float)}
    start = rebal_dates[0]
    gross = gross_ret_series.loc[start:]
    costs = (cost_dollar_series.loc[start:] + borrow_dollar_series.loc[start:]) / aum_dollar
    net = gross - costs
    return {
        "gross": gross,
        "net": net,
        "costs_pct_aum": costs,
        "turnover_list": turnover_list,
    }


def regime_conditional_sharpe(net: pd.Series, benchmark: pd.Series) -> Dict[str, Dict[str, float]]:
    """Three regimes by 21-day realized vol of the equal-weight benchmark."""
    vol = benchmark.rolling(21).std() * math.sqrt(252)
    low_thr = vol.quantile(0.33)
    hi_thr = vol.quantile(0.67)
    low = (vol <= low_thr)
    mid = (vol > low_thr) & (vol < hi_thr)
    high = (vol >= hi_thr)
    out: Dict[str, Dict[str, float]] = {}
    for label, mask in [("low_vol", low), ("mid_vol", mid), ("high_vol", high),
                         ("all", pd.Series(True, index=vol.index))]:
        r = net[mask.reindex(net.index, fill_value=False)]
        if len(r) >= 30:
            boot = stationary_bootstrap_sharpe(r.to_numpy(), seed=abs(hash(label)) % (2**31))
        else:
            boot = {"mean": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "p_positive": 0.0}
        out[label] = {
            "n_days": int(len(r)),
            "sharpe": ann_sharpe(r),
            "ann_return": ann_return(r),
            "max_dd": max_drawdown(r),
            "sharpe_ci_lo": boot["ci_lo"],
            "sharpe_ci_hi": boot["ci_hi"],
        }
    return out


def crowding_diagnostics(net: pd.Series) -> Dict[str, float]:
    """OHLCV-only crowding proxies.

    - Sharpe decay: ratio of trailing-2y Sharpe to earliest-2y Sharpe.
    - Return autocorrelation at lags 1, 5, 21: crowded factors show
      elevated negative AC from forced liquidation.
    """
    n = len(net)
    if n < 252 * 4:
        return {"sharpe_decay_ratio": float("nan"),
                "ac_lag1": float("nan"), "ac_lag5": float("nan"), "ac_lag21": float("nan"),
                "trailing_2y_sharpe": float("nan"),
                "first_2y_sharpe": float("nan")}
    early = net.iloc[:252 * 2]
    late = net.iloc[-252 * 2:]
    s_early = ann_sharpe(early)
    s_late = ann_sharpe(late)
    decay = s_late / s_early if abs(s_early) > 1e-6 else float("nan")
    x = net.dropna().to_numpy()
    def ac(lag):
        if len(x) <= lag + 5:
            return float("nan")
        a = x[:-lag]; b = x[lag:]
        if a.std() == 0 or b.std() == 0:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])
    return {
        "sharpe_decay_ratio": float(decay),
        "trailing_2y_sharpe": float(s_late),
        "first_2y_sharpe": float(s_early),
        "ac_lag1": ac(1),
        "ac_lag5": ac(5),
        "ac_lag21": ac(21),
    }


def main():
    t0 = time.time()
    print(f"[{time.time()-t0:5.1f}s] Loading parquet panel...")
    close, volume, high, low = load_panel()
    print(f"          universe: {close.shape[1]} tickers, {close.shape[0]} trading days")

    print(f"[{time.time()-t0:5.1f}s] Computing Corwin-Schultz spread panel...")
    spread_bps = corwin_schultz_spread(high, low, window=21)

    print(f"[{time.time()-t0:5.1f}s] Building momentum factor panel...")
    momentum = build_momentum_panel(close)

    cost_model = HonestCostModel(
        impact=SquareRootImpactModel(k_bps=15.0, floor_bps=0.5),
        borrow=BorrowCostTable(default_bps_per_year=25.0),
        commission_bps=0.5,
        spread_fallback_half_bps=2.0,
    )
    equal_weight = close.pct_change().fillna(0.0).mean(axis=1)

    curve = []
    for aum in AUM_GRID:
        print(f"[{time.time()-t0:5.1f}s] AUM=${aum:,.0f} …")
        bt = run_backtest_with_aum(momentum, close, volume, spread_bps,
                                   aum_dollar=aum, cost_model=cost_model)
        net = bt["net"]
        gross = bt["gross"]
        boot = stationary_bootstrap_sharpe(net.to_numpy(),
                                           seed=abs(hash(aum)) % (2**31))
        curve.append({
            "aum_dollar": float(aum),
            "gross_sharpe": ann_sharpe(gross),
            "net_sharpe": ann_sharpe(net),
            "net_ann_return": ann_return(net),
            "max_drawdown": max_drawdown(net),
            "avg_cost_bps_per_day": float(bt["costs_pct_aum"].mean() * 1e4),
            "net_sharpe_ci_lo": boot["ci_lo"],
            "net_sharpe_ci_hi": boot["ci_hi"],
        })

    capacity_df = pd.DataFrame(curve)
    capacity_df.to_csv(OUT_DIR / "capacity_curve.csv", index=False)

    # Regime study at a mid-size AUM
    print(f"[{time.time()-t0:5.1f}s] Regime-conditional Sharpe at AUM=$100M …")
    bt_ref = run_backtest_with_aum(momentum, close, volume, spread_bps,
                                   aum_dollar=1e8, cost_model=cost_model)
    regime = regime_conditional_sharpe(bt_ref["net"], equal_weight)
    crowd = crowding_diagnostics(bt_ref["net"])

    summary = {
        "config": {
            "start": STUDY_START, "end": STUDY_END,
            "universe_size": int(close.shape[1]),
            "aum_grid": AUM_GRID,
            "holding_period_days": HOLDING_PERIOD_DAYS,
            "impact_k_bps": cost_model.impact.k_bps,
            "borrow_bps_per_year": cost_model.borrow.default_bps_per_year,
        },
        "capacity_curve": curve,
        "regime_conditional_sharpe_at_100m": regime,
        "crowding_diagnostics_at_100m": crowd,
    }
    (OUT_DIR / "capacity_results.json").write_text(
        json.dumps(summary, indent=2, default=float)
    )

    # Markdown report
    lines = []
    A = lines.append
    A("# AlphaForge — Capacity, Regime, and Crowding Study")
    A("")
    A(f"_12-1 momentum long-short on {close.shape[1]} tickers, "
      f"{STUDY_START} → {STUDY_END}._")
    A("")
    A("## 1. Capacity Curve")
    A("")
    A("Square-root impact model (k = 15 bps per √participation) + 0.5 bp commission")
    A("+ Corwin-Schultz half-spread + 25 bp/yr general-collateral borrow on the short leg.")
    A("")
    A("| AUM | Gross SR | Net SR | Net CI | Net Ann Return | Max DD | Avg Cost (bps/day) |")
    A("|---:|---:|---:|---:|---:|---:|---:|")
    for row in curve:
        A(f"| ${row['aum_dollar']:>12,.0f} | {row['gross_sharpe']:+.2f} | {row['net_sharpe']:+.2f} | "
          f"[{row['net_sharpe_ci_lo']:+.2f}, {row['net_sharpe_ci_hi']:+.2f}] | "
          f"{row['net_ann_return']:+.2%} | {row['max_drawdown']:.2%} | "
          f"{row['avg_cost_bps_per_day']:.2f} |")
    A("")
    A("*Capacity* is the AUM at which the net Sharpe confidence interval no longer clears zero.")
    A("")
    A("## 2. Regime-Conditional Sharpe (AUM = $100M)")
    A("")
    A("| Regime | Days | Sharpe | 95% CI | Ann Return | Max DD |")
    A("|---|---:|---:|---:|---:|---:|")
    for k in ["all", "low_vol", "mid_vol", "high_vol"]:
        r = regime[k]
        A(f"| {k} | {r['n_days']} | {r['sharpe']:+.2f} | "
          f"[{r['sharpe_ci_lo']:+.2f}, {r['sharpe_ci_hi']:+.2f}] | "
          f"{r['ann_return']:+.2%} | {r['max_dd']:.2%} |")
    A("")
    A("Regimes defined by terciles of 21-day realized vol on the equal-weight benchmark.")
    A("")
    A("## 3. Crowding Diagnostics (OHLCV-only proxies)")
    A("")
    A("- **Sharpe decay ratio** (trailing-2y / first-2y): "
      f"**{crowd['sharpe_decay_ratio']:.2f}**  "
      f"(first 2y = {crowd['first_2y_sharpe']:+.2f}, last 2y = {crowd['trailing_2y_sharpe']:+.2f}).")
    A("- **Own-return autocorrelation** — elevated-negative values suggest crowded-exit reversal.")
    A(f"  - AC(1): {crowd['ac_lag1']:+.3f}")
    A(f"  - AC(5): {crowd['ac_lag5']:+.3f}")
    A(f"  - AC(21): {crowd['ac_lag21']:+.3f}")
    A("")
    A("*13F- or short-interest-based crowding proxies are not available in this OHLCV-only panel.*")
    A("*These return-based proxies are weaker but model-free.*")
    A("")
    (OUT_DIR / "capacity_report.md").write_text("\n".join(lines))
    print(f"[{time.time()-t0:5.1f}s] Done. Report → {OUT_DIR / 'capacity_report.md'}")


if __name__ == "__main__":
    main()
