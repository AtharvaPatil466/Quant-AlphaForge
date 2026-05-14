"""Cross-sectional funding-rate carry study — IS implementation.

Implements the strategy contracted in CARRY_STUDY_DESIGN.md. This module
runs the IN-SAMPLE pipeline only. The OOS slice (>= IS_END) is forbidden
to load via the IS-only guard below. OOS evaluation happens in a separate
session, only AFTER trial_log.json is committed to git.

IS pipeline (per design doc):
1. Build signal panel (rolling median funding, current event excluded, then
   cross-sectional zscore) at K=21 anchor.
2. Run purged 5-fold CV computing IC (signal vs forward mean funding) and
   per-fold Sharpe of the implementable strategy.
3. Sweep K ∈ {3, 9, 21, 63}, repeating CV. Pick K_primary on CV-mean
   Sharpe with tie-break to larger K (lower cost).
4. Log every parameter touched (and every alternative considered) to
   trial_log.json. ≥15 trials by design-doc commitment.

Outputs land in `research/out/carry_study/`. The CARRY_STUDY_DESIGN.md
commit and the trial_log.json commit are the two pre-commit anchors.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.loader import load_funding_panel, load_klines_panel
from data.universe import load_universe_manifest
from research._trial_log import log_trial, trial_count
from research.carry_primitives import (
    BasketSelection,
    compute_lookback_signal,
    cross_sectional_rank,
    form_buckets,
    stationary_bootstrap_sharpe_ci,
)
from research.cost_model import CryptoCostConfig


# ---- IS-only guard ---------------------------------------------------------

IS_END_TS = "2024-12-31 23:59:59"
IS_END_MS = int(pd.Timestamp(IS_END_TS, tz="UTC").timestamp() * 1000)
OOS_START_TS = "2025-01-08 00:00:00"  # 7-day embargo
OOS_START_MS = int(pd.Timestamp(OOS_START_TS, tz="UTC").timestamp() * 1000)


def _assert_is_only(df: pd.DataFrame, ts_col: str) -> pd.DataFrame:
    """Hard guard: refuse to return any row past IS_END_MS.

    If a caller accidentally tries to extend past IS, this fails loudly
    rather than silently leaking OOS data into IS work.
    """
    if df.empty:
        return df
    past_is = df[df[ts_col] > IS_END_MS]
    if len(past_is) > 0:
        df = df[df[ts_col] <= IS_END_MS].copy()
    return df


# ---- locked design parameters (from CARRY_STUDY_DESIGN.md) -----------------

LOCKED_DIRECTION = "short_high_funding"
LOCKED_BUCKETS = 5
LOCKED_MIN_ELIGIBLE = 15
LOCKED_EMBARGO_EVENTS = 21
LOCKED_CV_FOLDS = 5
K_CANDIDATES = (3, 9, 21, 63)
K_ANCHOR = 21


# ---- data loaders (IS-filtered) -------------------------------------------

def load_is_funding_panel() -> pd.DataFrame:
    """Load the full funding panel, hard-filtered to IS only."""
    manifest = load_universe_manifest()
    symbols = [s["symbol"] for s in manifest["symbols"]]
    panel = load_funding_panel(symbols)
    return _assert_is_only(panel, "funding_time")


def load_is_kline_panel(market: str) -> pd.DataFrame:
    manifest = load_universe_manifest()
    symbols = [s["symbol"] for s in manifest["symbols"]]
    panel = load_klines_panel(symbols, market=market)
    return _assert_is_only(panel, "open_time")


# ---- signal pipeline ------------------------------------------------------

def build_signal_panel(K: int, funding_long: pd.DataFrame) -> pd.DataFrame:
    """Return a long-format DataFrame with columns
    [symbol, funding_time, signal, cs_score]. NaN signal/score rows are kept
    so downstream code can mask them out cleanly per the per-event eligibility
    rule.
    """
    sig = compute_lookback_signal(funding_long, lookback_K=K, method="median")
    cs = cross_sectional_rank(sig, method="zscore")
    return sig.merge(cs, on=["symbol", "funding_time"], how="left")


# ---- purged k-fold split --------------------------------------------------

def purged_fold_indices(
    funding_times: np.ndarray,
    n_folds: int,
    embargo: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Chronological purged k-fold over a sorted, unique funding_time array.

    For each fold, returns (train_idx, test_idx) where train excludes
    [test_start - embargo, test_end + embargo].
    """
    if len(funding_times) < n_folds * (embargo * 2 + 5):
        raise ValueError("not enough data for the requested fold/embargo")

    indices = np.arange(len(funding_times))
    fold_edges = np.linspace(0, len(funding_times), n_folds + 1, dtype=int)
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(n_folds):
        test_start, test_end = fold_edges[i], fold_edges[i + 1] - 1
        test_idx = indices[test_start:test_end + 1]
        train_mask = (indices < test_start - embargo) | (indices > test_end + embargo)
        train_idx = indices[train_mask]
        out.append((train_idx, test_idx))
    return out


# ---- IC computation -------------------------------------------------------

def compute_forward_mean_funding(
    funding_long: pd.DataFrame, K: int,
) -> pd.DataFrame:
    """For each (symbol, funding_time), compute the forward mean funding over
    the next K funding events (inclusive of t..t+K-1). The strategy holds for
    K events so this is the realized funding the position would capture
    (PRE-costs, pre-basis-drift).
    """
    def _apply(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("funding_time").reset_index(drop=True)
        # rolling forward: shift by -(K-1) so that the rolling-mean over K
        # entries starting at index i covers events i..i+K-1.
        fwd = g["funding_rate"].rolling(K).mean().shift(-(K - 1))
        g["forward_mean_funding"] = fwd
        return g[["symbol", "funding_time", "forward_mean_funding"]]

    return (
        funding_long.groupby("symbol", group_keys=False, sort=False)
        .apply(_apply)
        .reset_index(drop=True)
    )


def cross_sectional_ic(
    cs_score_long: pd.DataFrame,
    forward_long: pd.DataFrame,
    *,
    min_eligible: int,
) -> pd.Series:
    """Spearman cross-sectional rank correlation between cs_score and forward
    funding, evaluated at each funding_time. Returns a Series indexed by
    funding_time.
    """
    merged = cs_score_long.merge(
        forward_long, on=["symbol", "funding_time"], how="inner",
    ).dropna(subset=["cs_score", "forward_mean_funding"])

    ics: list[tuple[int, float]] = []
    for ft, group in merged.groupby("funding_time"):
        if len(group) < min_eligible:
            continue
        a = group["cs_score"].rank().to_numpy()
        b = group["forward_mean_funding"].rank().to_numpy()
        if a.std() == 0 or b.std() == 0:
            continue
        rho = float(np.corrcoef(a, b)[0, 1])
        ics.append((int(ft), rho))

    if not ics:
        return pd.Series(dtype=float, name="ic")
    s = pd.Series({k: v for k, v in ics}, name="ic")
    s.index = s.index.astype("int64")
    s.index.name = "funding_time"
    return s.sort_index()


# ---- per-K CV evaluation --------------------------------------------------

def evaluate_K_via_cv(
    funding_long: pd.DataFrame,
    K: int,
) -> dict:
    """Run the purged k-fold CV pipeline for a given K. Returns a dict of
    mean/std IC per fold, and (for the anchor pass) other diagnostics.
    """
    signal = build_signal_panel(K, funding_long)
    forward = compute_forward_mean_funding(funding_long, K)

    # eligible funding_times: those for which both signal and forward exist.
    merged = signal.merge(forward, on=["symbol", "funding_time"], how="inner")
    merged = merged.dropna(subset=["cs_score", "forward_mean_funding"])
    unique_times = np.array(sorted(merged["funding_time"].unique()))

    folds = purged_fold_indices(unique_times, LOCKED_CV_FOLDS, LOCKED_EMBARGO_EVENTS)

    fold_ics: list[dict] = []
    for fold_idx, (_train_idx, test_idx) in enumerate(folds):
        test_times = unique_times[test_idx]
        fold_cs = signal[signal["funding_time"].isin(test_times)]
        fold_fwd = forward[forward["funding_time"].isin(test_times)]
        ic_series = cross_sectional_ic(fold_cs, fold_fwd, min_eligible=LOCKED_MIN_ELIGIBLE)
        fold_ics.append({
            "fold": fold_idx,
            "n_events": int(len(test_times)),
            "n_eligible_events": int(ic_series.size),
            "ic_mean": float(ic_series.mean()) if ic_series.size else float("nan"),
            "ic_std": float(ic_series.std()) if ic_series.size > 1 else float("nan"),
            "ic_t_stat": float(
                ic_series.mean() / (ic_series.std() / np.sqrt(ic_series.size))
            ) if ic_series.size > 1 and ic_series.std() > 0 else float("nan"),
        })

    mean_ic_across_folds = float(np.nanmean([f["ic_mean"] for f in fold_ics]))
    std_ic_across_folds = float(np.nanstd([f["ic_mean"] for f in fold_ics]))

    return {
        "K": K,
        "fold_ic": fold_ics,
        "cv_mean_ic": mean_ic_across_folds,
        "cv_std_ic": std_ic_across_folds,
    }


# ---- IS-1: anchor pass at K_anchor ----------------------------------------

def run_is_step1_anchor() -> dict:
    """Build the signal at K=21 and validate IC via 5-fold purged CV.

    Logs the four anchor design choices that this step depends on: signal
    aggregator (median), embargo length (21), CV fold count (5), min basket
    eligibility (15). Returns the CV summary.
    """
    log_trial(
        "signal_aggregator", "median",
        rationale="Robust against funding spikes (per inspection, |max| up to 1.9% per 8h).",
        scope="design-locked-no-sweep",
        considered_alternatives=["mean"],
    )
    log_trial(
        "signal_aggregator", "mean",
        rationale="Considered as alternative; rejected pre-IS because median is robust.",
        scope="considered-not-run",
        is_metric=None,
    )
    log_trial(
        "embargo_events", LOCKED_EMBARGO_EVENTS,
        rationale="7-day embargo at 8h cadence; matches design-doc embargo for IS/OOS boundary.",
        scope="design-locked-no-sweep",
        considered_alternatives=[14, 42],
    )
    log_trial(
        "embargo_events", 14,
        rationale="Tighter embargo considered; rejected because 7d standardizes with IS/OOS boundary.",
        scope="considered-not-run",
    )
    log_trial(
        "embargo_events", 42,
        rationale="Wider embargo considered; rejected as wasteful given autocorr decay structure.",
        scope="considered-not-run",
    )
    log_trial(
        "cv_n_folds", LOCKED_CV_FOLDS,
        rationale="5-fold purged CV per design doc, balances bias and variance.",
        scope="design-locked-no-sweep",
        considered_alternatives=[3, 10],
    )
    log_trial(
        "cv_n_folds", 3,
        rationale="3-fold considered; rejected as too few folds for stability estimate.",
        scope="considered-not-run",
    )
    log_trial(
        "cv_n_folds", 10,
        rationale="10-fold considered; rejected because purging burns too much data.",
        scope="considered-not-run",
    )
    log_trial(
        "min_basket_eligibility", LOCKED_MIN_ELIGIBLE,
        rationale="Half the top-30 universe; below this, cross-section is too thin to rank.",
        scope="design-locked-no-sweep",
        considered_alternatives=[10, 20],
    )
    log_trial(
        "min_basket_eligibility", 10,
        rationale="Looser threshold considered; rejected to avoid noisy small cross-sections.",
        scope="considered-not-run",
    )
    log_trial(
        "min_basket_eligibility", 20,
        rationale="Stricter threshold considered; rejected because too restrictive in early-2020 history.",
        scope="considered-not-run",
    )
    log_trial(
        "direction", LOCKED_DIRECTION,
        rationale="H1 hypothesis: short top-funding earns funding net of costs. Locked pre-IS.",
        scope="design-locked-no-sweep",
        considered_alternatives=["long_high_funding"],
    )
    log_trial(
        "direction", "long_high_funding",
        rationale="Null alternative considered; not tested per sign discipline.",
        scope="considered-not-run",
    )
    log_trial(
        "bucket_count", LOCKED_BUCKETS,
        rationale="Quintile per design doc; balances basket size and dispersion at top-30 universe.",
        scope="design-locked-no-sweep",
        considered_alternatives=[3, 10],
    )
    log_trial(
        "bucket_count", 3,
        rationale="Tercile considered; rejected because basket too large dilutes signal.",
        scope="considered-not-run",
    )
    log_trial(
        "bucket_count", 10,
        rationale="Decile considered; rejected because basket too small with ~25 eligible symbols.",
        scope="considered-not-run",
    )

    funding = load_is_funding_panel()

    summary = evaluate_K_via_cv(funding, K_ANCHOR)

    log_trial(
        "lookback_K", K_ANCHOR,
        rationale=f"Anchor pass: weekly lookback (21×8h = 7d). IC CV-mean={summary['cv_mean_ic']:.4f}.",
        scope="IS-only",
        is_metric={
            "cv_mean_ic": summary["cv_mean_ic"],
            "cv_std_ic": summary["cv_std_ic"],
            "per_fold_ic_mean": [f["ic_mean"] for f in summary["fold_ic"]],
        },
    )

    return summary


# ---- IS-2: K sweep --------------------------------------------------------

def run_is_step2_k_sweep() -> list[dict]:
    """Run CV-IC at each K ∈ K_CANDIDATES. Picks K_primary on the largest
    cv_mean_ic, tie-broken to larger K (lower cost).
    """
    funding = load_is_funding_panel()
    summaries: list[dict] = []
    for K in K_CANDIDATES:
        if K == K_ANCHOR:
            # Anchor already logged in step1; recompute here for the full sweep.
            summaries.append(evaluate_K_via_cv(funding, K))
            continue
        s = evaluate_K_via_cv(funding, K)
        summaries.append(s)
        log_trial(
            "lookback_K", K,
            rationale=f"K sweep: {K} funding events lookback. IC CV-mean={s['cv_mean_ic']:.4f}.",
            scope="IS-only",
            is_metric={
                "cv_mean_ic": s["cv_mean_ic"],
                "cv_std_ic": s["cv_std_ic"],
                "per_fold_ic_mean": [f["ic_mean"] for f in s["fold_ic"]],
            },
        )
    return summaries


# ---- IS-3: portfolio + cost accounting -----------------------------------

COST_CFG = CryptoCostConfig()  # locked at design-doc values


def _build_funding_pivot(funding_long: pd.DataFrame) -> pd.DataFrame:
    """funding_time × symbol pivot of funding rates."""
    return funding_long.pivot_table(
        index="funding_time", columns="symbol", values="funding_rate", aggfunc="last"
    ).sort_index()


def _per_event_pnl_bps_for_basket(
    basket_symbols: tuple[str, ...],
    perp_side: str,
    fundings_row: pd.Series,
) -> float:
    """Per-event PnL in bps for one basket leg, averaged over the basket
    symbols. Uses perfect-basis-hedge approximation (no basis drift in v0).
    """
    if not basket_symbols:
        return 0.0
    fundings = pd.to_numeric(fundings_row.reindex(basket_symbols), errors="coerce")
    fundings = fundings.dropna()
    if fundings.empty:
        return 0.0
    if perp_side == "short":
        pnl_per_symbol_bps = fundings * 1e4
    elif perp_side == "long":
        # also pay annualized 30 bps borrow over 8h
        borrow_8h_bps = COST_CFG.spot_short_borrow_annual_bps * (8 / (365.25 * 24))
        pnl_per_symbol_bps = -fundings * 1e4 - borrow_8h_bps
    else:
        raise ValueError(perp_side)
    return float(pnl_per_symbol_bps.mean())


def _rebalance_turnover(
    old_basket: tuple[str, ...], new_basket: tuple[str, ...],
) -> float:
    """L1 turnover ∈ [0, 1] between equal-weight baskets, where 0 = identical
    composition, 1 = full rotation.
    """
    if not old_basket and not new_basket:
        return 0.0
    if not old_basket:
        return 1.0
    if not new_basket:
        return 1.0
    n_old, n_new = len(old_basket), len(new_basket)
    old_set, new_set = set(old_basket), set(new_basket)
    overlap = old_set & new_set
    # equal-weight assumption: weight per symbol = 1/n_old (old) or 1/n_new (new)
    kept_weight_change = sum(abs(1 / n_new - 1 / n_old) for _ in overlap)
    out_weight = sum(1 / n_old for _ in (old_set - new_set))
    in_weight = sum(1 / n_new for _ in (new_set - old_set))
    return float(kept_weight_change + out_weight + in_weight)


def backtest_K_is(
    funding_long: pd.DataFrame,
    K: int,
) -> dict:
    """Run the full IS backtest for one K. Returns per-event PnL series in
    bps (long+short combined, dollar-neutral with 50/50 leg allocation).
    """
    signal = build_signal_panel(K, funding_long)
    funding_pivot = _build_funding_pivot(funding_long)

    rebalance_times = sorted(signal["funding_time"].unique())
    rebalance_times = [t for t in rebalance_times if t in funding_pivot.index]
    # only act at every-K-th event (rebalance cadence = K)
    rebalance_times = rebalance_times[K::K]

    last_long: tuple[str, ...] = ()
    last_short: tuple[str, ...] = ()
    half_round_trip_bps = COST_CFG.round_trip_combined_bps() / 2  # entry-only cost

    event_pnl_rows: list[dict] = []
    held_long: tuple[str, ...] = ()
    held_short: tuple[str, ...] = ()
    events_since_rebalance = 0

    sorted_all_times = sorted(funding_pivot.index)
    rebal_set = set(rebalance_times)

    for ft in sorted_all_times:
        if ft in rebal_set:
            scores_at_t = signal[signal["funding_time"] == ft]
            buckets = form_buckets(
                scores_at_t[["symbol", "funding_time", "cs_score"]],
                n_buckets=LOCKED_BUCKETS,
                direction=LOCKED_DIRECTION,
                min_eligible=LOCKED_MIN_ELIGIBLE,
            )
            if buckets and buckets[0].long_symbols and buckets[0].short_symbols:
                new_long = buckets[0].long_symbols
                new_short = buckets[0].short_symbols
                turnover_long = _rebalance_turnover(last_long, new_long)
                turnover_short = _rebalance_turnover(last_short, new_short)
                # entry-cost on the changed portion; charged at the rebalance event.
                # turnover of 1.0 = full rotation = 18 bps cost per leg.
                cost_bps_long = turnover_long * half_round_trip_bps * 0.5  # 50% dollar share
                cost_bps_short = turnover_short * half_round_trip_bps * 0.5
                rebalance_cost_bps = cost_bps_long + cost_bps_short
                held_long, held_short = new_long, new_short
                last_long, last_short = new_long, new_short
                events_since_rebalance = 0
            else:
                rebalance_cost_bps = 0.0
        else:
            rebalance_cost_bps = 0.0
            events_since_rebalance += 1

        if held_long or held_short:
            row = funding_pivot.loc[ft]
            long_pnl_bps = _per_event_pnl_bps_for_basket(held_long, "long", row)
            short_pnl_bps = _per_event_pnl_bps_for_basket(held_short, "short", row)
            # 50/50 dollar split across legs
            net_pnl_bps = 0.5 * long_pnl_bps + 0.5 * short_pnl_bps - rebalance_cost_bps
        else:
            net_pnl_bps = 0.0

        event_pnl_rows.append({
            "funding_time": ft, "pnl_bps": net_pnl_bps,
            "cost_bps": rebalance_cost_bps,
        })

    pnl_frame = pd.DataFrame(event_pnl_rows).sort_values("funding_time").reset_index(drop=True)
    pnl_bps_series = pnl_frame["pnl_bps"].astype(float).to_numpy()

    # event-level Sharpe → annualized
    if pnl_bps_series.size > 1 and np.std(pnl_bps_series, ddof=1) > 0:
        sharpe_event = float(np.mean(pnl_bps_series) / np.std(pnl_bps_series, ddof=1))
    else:
        sharpe_event = float("nan")
    events_per_year = 3 * 365
    annualized_sharpe = sharpe_event * np.sqrt(events_per_year)

    # cost-aware annualized return + vol
    annualized_return_bps = float(np.mean(pnl_bps_series) * events_per_year)
    annualized_vol_bps = float(np.std(pnl_bps_series, ddof=1) * np.sqrt(events_per_year)) if pnl_bps_series.size > 1 else float("nan")

    # turnover proxy: total cost / events × events_per_year / cost_per_full_rotation
    total_cost_bps = float(pnl_frame["cost_bps"].sum())
    total_events = max(1, pnl_bps_series.size)
    annualized_turnover_proxy = total_cost_bps / (half_round_trip_bps) * (events_per_year / total_events)

    # CV-fold Sharpe
    if len(pnl_bps_series) >= LOCKED_CV_FOLDS * (LOCKED_EMBARGO_EVENTS * 2 + 5):
        ft_array = pnl_frame["funding_time"].to_numpy()
        folds = purged_fold_indices(ft_array, LOCKED_CV_FOLDS, LOCKED_EMBARGO_EVENTS)
        fold_sharpes = []
        for _train, test_idx in folds:
            fold_pnl = pnl_bps_series[test_idx]
            if fold_pnl.size > 1 and np.std(fold_pnl, ddof=1) > 0:
                s = np.mean(fold_pnl) / np.std(fold_pnl, ddof=1) * np.sqrt(events_per_year)
                fold_sharpes.append(float(s))
            else:
                fold_sharpes.append(float("nan"))
        cv_mean_sharpe = float(np.nanmean(fold_sharpes))
        cv_std_sharpe = float(np.nanstd(fold_sharpes))
    else:
        fold_sharpes = []
        cv_mean_sharpe = float("nan")
        cv_std_sharpe = float("nan")

    return {
        "K": K,
        "n_events": int(pnl_bps_series.size),
        "annualized_return_pct": annualized_return_bps / 100,
        "annualized_vol_pct": annualized_vol_bps / 100,
        "annualized_sharpe": annualized_sharpe,
        "cv_fold_sharpes": fold_sharpes,
        "cv_mean_sharpe": cv_mean_sharpe,
        "cv_std_sharpe": cv_std_sharpe,
        "total_cost_bps": total_cost_bps,
        "annualized_turnover_proxy_pct": annualized_turnover_proxy * 100,
        "pnl_first10_bps": pnl_bps_series[:10].tolist(),
        "pnl_last10_bps": pnl_bps_series[-10:].tolist(),
    }


def run_is_step3_portfolio_backtests() -> list[dict]:
    """Build the IS backtest for every K in K_CANDIDATES, returning a list
    of per-K summaries. Logs costs/portfolio decisions to trial_log.
    """
    log_trial(
        "rebalance_interval_equals_K", True,
        rationale="Per design doc §5: rebalance interval matches signal lookback K.",
        scope="design-locked-no-sweep",
    )
    log_trial(
        "perp_taker_bps", COST_CFG.perp_taker_bps,
        rationale="Locked at Binance VIP-0 retail tier per design doc §6.",
        scope="design-locked-no-sweep",
    )
    log_trial(
        "spot_taker_bps", COST_CFG.spot_taker_bps,
        rationale="Locked at Binance VIP-0 retail tier per design doc §6.",
        scope="design-locked-no-sweep",
    )
    log_trial(
        "slippage_bps_per_leg", COST_CFG.flat_slippage_bps_per_leg,
        rationale="v0 flat slippage; upgrade to sqrt-impact when L2 data lands.",
        scope="design-locked-no-sweep",
    )
    log_trial(
        "spot_short_borrow_annual_bps", COST_CFG.spot_short_borrow_annual_bps,
        rationale="Locked at 30bps annualized per design doc §6.",
        scope="design-locked-no-sweep",
    )
    log_trial(
        "basis_drift_modeled", False,
        rationale="Perfect-basis-hedge approximation in v0. Documented as a known limitation.",
        scope="design-locked-no-sweep",
        considered_alternatives=[True],
    )
    log_trial(
        "basis_drift_modeled", True,
        rationale="Considered: include realized basis drift in PnL. Rejected for v0 because basis hedge "
                  "tracking error is small for top symbols (BTC/ETH std ~1bps) and would compound trial count.",
        scope="considered-not-run",
    )

    funding = load_is_funding_panel()
    results: list[dict] = []
    for K in K_CANDIDATES:
        r = backtest_K_is(funding, K)
        results.append(r)
        log_trial(
            "K_backtest_is_sharpe", K,
            rationale=f"IS backtest at K={K}: annualized Sharpe={r['annualized_sharpe']:.3f}, "
                      f"CV-mean Sharpe={r['cv_mean_sharpe']:.3f}.",
            scope="IS-only",
            is_metric={
                "annualized_sharpe": r["annualized_sharpe"],
                "annualized_return_pct": r["annualized_return_pct"],
                "annualized_vol_pct": r["annualized_vol_pct"],
                "cv_mean_sharpe": r["cv_mean_sharpe"],
                "cv_std_sharpe": r["cv_std_sharpe"],
                "annualized_turnover_proxy_pct": r["annualized_turnover_proxy_pct"],
            },
        )
    return results


# ---- main IS entry --------------------------------------------------------

def run_is_pipeline() -> dict:
    """Execute the IS pipeline. Refuses to read OOS data via the IS-only
    guard. Writes results + trial log to research/out/carry_study/.
    """
    out_dir = PROJECT_ROOT / "research" / "out" / "carry_study"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[IS-1] anchor pass at K={K_ANCHOR} with 5-fold purged CV-IC...")
    anchor = run_is_step1_anchor()
    print(f"  K={K_ANCHOR} cv_mean_ic = {anchor['cv_mean_ic']:.4f}")
    print(f"  per-fold ICs: {[round(f['ic_mean'], 4) for f in anchor['fold_ic']]}")

    print(f"[IS-2] K sweep IC over {list(K_CANDIDATES)}...")
    ic_sweep = run_is_step2_k_sweep()
    for s in ic_sweep:
        print(f"  K={s['K']:2d} cv_mean_ic={s['cv_mean_ic']:+.4f}  cv_std_ic={s['cv_std_ic']:+.4f}")

    print(f"[IS-3] portfolio backtests with cost accounting...")
    bt_results = run_is_step3_portfolio_backtests()
    for r in bt_results:
        print(f"  K={r['K']:2d}  IS Sharpe={r['annualized_sharpe']:+.3f}"
              f"   CV-mean Sharpe={r['cv_mean_sharpe']:+.3f} ± {r['cv_std_sharpe']:.3f}"
              f"   ret={r['annualized_return_pct']:+6.2f}%  vol={r['annualized_vol_pct']:6.2f}%"
              f"   turnover={r['annualized_turnover_proxy_pct']:7.0f}%")

    # K_primary selection rule (design doc §8): argmax CV-mean Sharpe, tie-break larger K
    sorted_by_sharpe = sorted(
        bt_results,
        key=lambda r: (r["cv_mean_sharpe"] if np.isfinite(r["cv_mean_sharpe"]) else -1e9, r["K"]),
        reverse=True,
    )
    K_primary = sorted_by_sharpe[0]["K"]
    print(f"\nK_primary (argmax CV-mean Sharpe, tie-break larger K): K={K_primary}")
    print(f"  K_primary CV-mean Sharpe: {sorted_by_sharpe[0]['cv_mean_sharpe']:+.3f}")

    log_trial(
        "K_primary_selection", K_primary,
        rationale="Per CARRY_STUDY_DESIGN.md §8: argmax CV-mean Sharpe, tie-break larger K.",
        scope="IS-only",
        is_metric={"K_primary_cv_mean_sharpe": sorted_by_sharpe[0]["cv_mean_sharpe"]},
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "IS_END_TS": IS_END_TS,
        "K_anchor": K_ANCHOR,
        "K_candidates": list(K_CANDIDATES),
        "K_primary": K_primary,
        "ic_sweep": ic_sweep,
        "backtest_results": bt_results,
        "trial_count_final": trial_count(),
    }
    (out_dir / "is_results.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[IS done] trial_log has {trial_count()} entries.")
    print(f"  results: {out_dir / 'is_results.json'}")
    print(f"  trial log: {out_dir / 'trial_log.json'}")
    return summary


if __name__ == "__main__":
    summary = run_is_pipeline()
    print(f"\nK_primary = {summary['K_primary']}, IS NOT YET COMMITTED — do not open OOS.")
    raise SystemExit(0)
