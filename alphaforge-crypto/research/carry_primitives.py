"""Computation primitives for the carry study.

These are mechanical functions: given inputs, compute outputs deterministically.
No strategy decisions live here — that's `carry_study.py` (currently a stub
pending the pre-commit design doc).

Functions exposed:
- `compute_lookback_signal`: rolling median of past funding rates per symbol.
- `cross_sectional_rank`: cross-sectional rank-then-zscore at each event.
- `form_buckets`: split sorted symbols into top/bottom quintile baskets.
- `compute_period_pnl_bps`: per-period PnL in bps for a held position.
- `stationary_bootstrap_sharpe_ci`: stationary bootstrap CI for Sharpe.

The primitives are deliberately pure functions over pandas/numpy structures
so they're cheap to unit-test and reusable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


# ---- signal construction ---------------------------------------------------

def compute_lookback_signal(
    funding_panel_long: pd.DataFrame,
    lookback_K: int,
    *,
    method: str = "median",
) -> pd.DataFrame:
    """Compute the per-symbol lookback signal from the long-format funding panel.

    The lookback window uses ONLY past funding events for each symbol — the
    funding event at time t is NOT included in the signal evaluated for t.
    This enforces no-look-ahead at the primitive level.

    Args:
        funding_panel_long: long-format DataFrame with columns
            ['symbol', 'funding_time', 'funding_rate'] (as produced by
            `data.loader.load_funding_panel`).
        lookback_K: number of past funding events to include in the rolling window.
        method: 'median' (robust, default) or 'mean'.

    Returns:
        Long-format DataFrame with ['symbol', 'funding_time', 'signal'].
        Rows where the lookback window isn't filled have signal=NaN.
    """
    if lookback_K < 1:
        raise ValueError("lookback_K must be >= 1")
    if method not in ("median", "mean"):
        raise ValueError(f"unknown method {method!r}")

    def _apply(group: pd.DataFrame) -> pd.DataFrame:
        g = group.sort_values("funding_time").reset_index(drop=True)
        # shift(1) excludes the current event from the lookback — no look-ahead.
        roll = g["funding_rate"].shift(1).rolling(window=lookback_K, min_periods=lookback_K)
        g["signal"] = roll.median() if method == "median" else roll.mean()
        return g[["symbol", "funding_time", "signal"]]

    return (
        funding_panel_long.groupby("symbol", group_keys=False, sort=False)
        .apply(_apply)
        .reset_index(drop=True)
    )


def cross_sectional_rank(
    signal_long: pd.DataFrame,
    *,
    method: str = "zscore",
) -> pd.DataFrame:
    """Convert per-symbol signals to a cross-sectionally-normalized score.

    At each funding_time, ranks the eligible symbols. Useful when raw funding
    levels differ wildly across regimes (high-vol vs low-vol funding eras).

    Args:
        signal_long: output of `compute_lookback_signal`.
        method: 'zscore' (default; subtract cross-section mean, divide by std)
                or 'rank_pct' (percentile rank ∈ [0, 1]).

    Returns:
        Long-format DataFrame with ['symbol', 'funding_time', 'cs_score'].
    """
    df = signal_long.copy()
    if method == "zscore":
        grouped = df.groupby("funding_time")["signal"]
        df["cs_score"] = (df["signal"] - grouped.transform("mean")) / grouped.transform("std").replace(0, np.nan)
    elif method == "rank_pct":
        df["cs_score"] = df.groupby("funding_time")["signal"].rank(pct=True)
    else:
        raise ValueError(f"unknown method {method!r}")
    return df[["symbol", "funding_time", "cs_score"]]


# ---- portfolio construction -----------------------------------------------

@dataclass(frozen=True)
class BasketSelection:
    funding_time: int
    long_symbols: tuple[str, ...]
    short_symbols: tuple[str, ...]


def form_buckets(
    cs_score_long: pd.DataFrame,
    *,
    n_buckets: int = 5,
    direction: str,
    min_eligible: int = 10,
) -> list[BasketSelection]:
    """Sort symbols by cross-sectional score at each funding time and form
    long/short baskets from the top/bottom buckets.

    Args:
        cs_score_long: output of `cross_sectional_rank`.
        n_buckets: number of quantile buckets (5 = quintiles).
        direction: must be 'short_high_funding' (the H1 hypothesis: short the
            highest-funding basket, long the lowest) or 'long_high_funding'
            (the opposite). The choice MUST be made in the pre-commit doc, not
            here.
        min_eligible: minimum eligible symbols at a timestamp; below this,
            no basket is formed for that event (returns empty selection).

    Returns:
        Ordered list of BasketSelections, one per funding event.
    """
    if direction not in ("short_high_funding", "long_high_funding"):
        raise ValueError(f"direction must be specified; got {direction!r}")

    selections: list[BasketSelection] = []
    for funding_time, group in cs_score_long.groupby("funding_time", sort=True):
        eligible = group.dropna(subset=["cs_score"])
        n = len(eligible)
        if n < min_eligible:
            selections.append(BasketSelection(int(funding_time), (), ()))
            continue
        bucket_size = max(1, n // n_buckets)
        ranked = eligible.sort_values("cs_score", ascending=False)
        top = tuple(ranked.iloc[:bucket_size]["symbol"].tolist())
        bottom = tuple(ranked.iloc[-bucket_size:]["symbol"].tolist())
        if direction == "short_high_funding":
            selections.append(BasketSelection(int(funding_time), long_symbols=bottom, short_symbols=top))
        else:
            selections.append(BasketSelection(int(funding_time), long_symbols=top, short_symbols=bottom))
    return selections


# ---- PnL accounting -------------------------------------------------------

def compute_period_pnl_bps(
    *,
    perp_side: str,
    funding_rate: float,
    spot_return_pct: float,
    perp_return_pct: float,
    spot_borrow_bps_period: float = 0.0,
) -> float:
    """Per-period PnL in bps for one symbol held over one funding interval.

    The position is dollar-neutral: one leg short, one leg long, same notional.

    PnL components:
    - funding: short-perp earns +rate, long-perp pays -rate
    - basis drift: (spot_return - perp_return) shows up because the spot and perp
      legs don't move identically.
    - spot short borrow: only for the long-perp / short-spot leg
    """
    if perp_side == "short":
        # short perp + long spot: receive funding, long spot return, short perp return
        funding_bps = funding_rate * 1e4
        spot_pnl_bps = spot_return_pct * 1e4
        perp_pnl_bps = -perp_return_pct * 1e4
        borrow_bps = 0.0
    elif perp_side == "long":
        # long perp + short spot: pay funding, long perp return, short spot return, pay borrow
        funding_bps = -funding_rate * 1e4
        spot_pnl_bps = -spot_return_pct * 1e4
        perp_pnl_bps = perp_return_pct * 1e4
        borrow_bps = -spot_borrow_bps_period
    else:
        raise ValueError(f"perp_side must be 'long' or 'short', got {perp_side!r}")
    return funding_bps + spot_pnl_bps + perp_pnl_bps + borrow_bps


def compute_round_trip_cost_bps(
    *,
    perp_taker_bps: float,
    spot_taker_bps: float,
    slippage_bps_per_leg: float,
) -> float:
    """Total round-trip cost in bps for entering and exiting one symbol's
    paired position. Charged at rebalance, not amortized.
    """
    return 2 * (perp_taker_bps + slippage_bps_per_leg) + 2 * (spot_taker_bps + slippage_bps_per_leg)


# ---- statistical hygiene --------------------------------------------------

def stationary_bootstrap_sharpe_ci(
    returns: np.ndarray | pd.Series,
    *,
    n_resamples: int = 2000,
    mean_block_length: float | None = None,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Stationary bootstrap (Politis-Romano 1994) confidence interval for Sharpe.

    Returns (sharpe_point, sharpe_low, sharpe_high).

    Args:
        returns: per-period returns (any cadence; Sharpe will be computed at
            the same cadence — caller is responsible for annualization).
        n_resamples: number of bootstrap resamples.
        mean_block_length: expected geometric block length. If None, uses
            `max(1, T^{1/3})` as a default (rule of thumb for serially
            dependent series).
        confidence: e.g. 0.95 for a two-sided 95% CI.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    T = len(r)
    if T < 30:
        return _sharpe_point(r), float("nan"), float("nan")
    if mean_block_length is None:
        mean_block_length = max(1.0, T ** (1.0 / 3))
    p_continue = 1.0 - 1.0 / mean_block_length

    rng = np.random.default_rng(seed)
    sharpes = np.empty(n_resamples)
    for b in range(n_resamples):
        idx = np.empty(T, dtype=np.int64)
        cur = rng.integers(0, T)
        for i in range(T):
            idx[i] = cur
            if rng.random() < p_continue:
                cur = (cur + 1) % T
            else:
                cur = rng.integers(0, T)
        sample = r[idx]
        sharpes[b] = _sharpe_point(sample)

    alpha = 1.0 - confidence
    low = float(np.quantile(sharpes, alpha / 2))
    high = float(np.quantile(sharpes, 1 - alpha / 2))
    return _sharpe_point(r), low, high


def _sharpe_point(r: np.ndarray) -> float:
    if r.size == 0:
        return float("nan")
    sd = r.std(ddof=1) if r.size > 1 else 0.0
    if sd <= 0 or not np.isfinite(sd):
        return float("nan")
    return float(r.mean() / sd)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    *,
    n_trials: int,
    skewness: float,
    kurtosis: float,
    n_observations: int,
) -> float:
    """Deflated Sharpe Ratio (López de Prado, 2018).

    DSR adjusts the raw Sharpe for the number of independent backtest trials,
    the higher-moment shape of the returns distribution, and the sample size.
    A common threshold is DSR > 0.95 ("statistically significant after
    accounting for multiple testing").

    Args:
        observed_sharpe: the Sharpe of the best-of-trials strategy, same
            cadence as the underlying returns.
        n_trials: total number of strategies / parameter combinations
            evaluated. Must include every K, every rebalance interval, etc.
        skewness: skew of the returns distribution.
        kurtosis: kurtosis (NOT excess kurtosis — use 3.0 for normal).
        n_observations: sample length used to compute the Sharpe.

    Returns:
        DSR ∈ [0, 1]. Higher is more confident the Sharpe is not a fluke.
    """
    from math import sqrt, log
    from statistics import NormalDist

    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    nd = NormalDist()
    euler_mascheroni = 0.5772156649
    e = 2.718281828

    # Expected max Sharpe under the null with N independent trials.
    if n_trials == 1:
        expected_max = 0.0
    else:
        z_alpha = nd.inv_cdf(1.0 - 1.0 / n_trials)
        z_beta = nd.inv_cdf(1.0 - 1.0 / (n_trials * e))
        expected_max = (1 - euler_mascheroni) * z_alpha + euler_mascheroni * z_beta

    # Variance shrinkage from skew/kurt.
    var_factor = 1.0 - skewness * observed_sharpe + ((kurtosis - 1.0) / 4.0) * observed_sharpe ** 2
    if var_factor <= 0:
        return 0.0
    denom = sqrt(var_factor) / sqrt(max(1, n_observations - 1))
    if denom <= 0:
        return 0.0
    z = (observed_sharpe - expected_max) / denom
    return nd.cdf(z)
