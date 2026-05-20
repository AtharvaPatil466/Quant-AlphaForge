"""Delivery percentage signal — INDIA_DESIGN.md §4.1 + §8.1.

The delivery percentage signal exploits NSE-published daily delivery data:
the fraction of a stock's traded volume that results in physical settlement.
High delivery % indicates conviction-based accumulation; low delivery %
indicates speculative position-taking.

Trial grid (18 = 3 × 2 × 3):
    lookback:  10, 20, 60 days
    bucket:    quintile (top/bottom 20%), decile (top/bottom 10%)
    holding:   5, 10, 21 days

Public API
----------
- ``DeliveryPctSignal``   — single trial specification + compute methods.
- ``enumerate_trials()``  — returns all 18 pre-committed trials.
- ``compute_forward_returns(close_df, holding_period)`` — helper.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

log = logging.getLogger("india.signals.delivery_pct")

# ---------------------------------------------------------------------------
# Pre-committed parameter grid (§4.1)
# ---------------------------------------------------------------------------

LOOKBACKS: tuple[int, ...] = (10, 20, 60)
BUCKETS: tuple[str, ...] = ("quintile", "decile")
HOLDING_PERIODS: tuple[int, ...] = (5, 10, 21)

_BUCKET_FRAC: dict[str, float] = {
    "quintile": 0.20,
    "decile":   0.10,
}


# ---------------------------------------------------------------------------
# Forward-return helper
# ---------------------------------------------------------------------------

def compute_forward_returns(
    close_df: pd.DataFrame,
    holding_period: int,
) -> pd.DataFrame:
    """Compute *holding_period*-day forward returns from a close-price panel.

    Parameters
    ----------
    close_df : pd.DataFrame
        Date-indexed, columns = symbols, values = adjusted close prices.
    holding_period : int
        Number of trading days to look forward.

    Returns
    -------
    pd.DataFrame
        Same shape as *close_df*, ``(close[t+h] / close[t]) - 1``.
        Trailing rows that cannot form a full look-forward window are NaN.
    """
    if holding_period < 1:
        raise ValueError(f"holding_period must be ≥ 1, got {holding_period}")

    fwd = close_df.shift(-holding_period)
    # Defensive: avoid division by zero (safeDiv pattern)
    denom = close_df.replace(0.0, np.nan)
    return (fwd / denom) - 1.0


# ---------------------------------------------------------------------------
# DeliveryPctSignal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeliveryPctSignal:
    """A single delivery-percentage trial specification.

    Parameters
    ----------
    lookback : int
        Rolling window (trading days) for the mean delivery-pct estimate.
    bucket : str
        ``"quintile"`` (top/bottom 20 %) or ``"decile"`` (top/bottom 10 %).
    holding_period : int
        Number of trading days between rebalances / IC evaluation.
    """

    lookback: int
    bucket: Literal["quintile", "decile"]
    holding_period: int

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ValueError(f"lookback must be ≥ 1, got {self.lookback}")
        if self.bucket not in _BUCKET_FRAC:
            raise ValueError(
                f"bucket must be one of {list(_BUCKET_FRAC)}, got {self.bucket!r}"
            )
        if self.holding_period < 1:
            raise ValueError(
                f"holding_period must be ≥ 1, got {self.holding_period}"
            )

    # ---- naming convention --------------------------------------------------

    @property
    def trial_name(self) -> str:
        """Canonical trial identifier.

        Format: ``deliv_pct_L{lookback}_Q{quintile_denom}_H{holding_period}``

        Examples
        --------
        >>> DeliveryPctSignal(10, "quintile", 5).trial_name
        'deliv_pct_L10_Q5_H5'
        >>> DeliveryPctSignal(20, "decile", 21).trial_name
        'deliv_pct_L20_Q10_H21'
        """
        q = {"quintile": 5, "decile": 10}[self.bucket]
        return f"deliv_pct_L{self.lookback}_Q{q}_H{self.holding_period}"

    # ---- signal computation -------------------------------------------------

    def compute_signal(
        self,
        prices_df: pd.DataFrame,
        deliv_pct_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute the cross-sectional delivery-pct signal.

        Steps (per §1.1 + §8.1):
        1. Rolling mean of ``deliv_pct`` over the lookback window.
        2. Cross-sectional z-score (mean=0, std=1 across stocks on each date).

        Parameters
        ----------
        prices_df : pd.DataFrame
            Date-indexed panel (columns = symbols) of close prices.  Not
            consumed for signal values but used to restrict the universe
            to stocks with tradeable prices (non-NaN close).
        deliv_pct_df : pd.DataFrame
            Date-indexed panel (columns = symbols) of delivery percentages
            on the 0-100 scale.  Same date index as *prices_df*.

        Returns
        -------
        pd.DataFrame
            Cross-sectional z-scored rolling-mean delivery-pct signal.
            Positive = high delivery conviction; negative = speculative.
        """
        # 1. Rolling mean — require at least half the window populated.
        min_obs = max(1, self.lookback // 2)
        rolling_mean = deliv_pct_df.rolling(
            window=self.lookback, min_periods=min_obs,
        ).mean()

        # Mask to tradeable universe (non-NaN close)
        tradeable = prices_df.notna()
        rolling_mean = rolling_mean.where(tradeable)

        # 2. Cross-sectional z-score (per row)
        cs_mean = rolling_mean.mean(axis=1)
        cs_std = rolling_mean.std(axis=1)
        # Defensive: avoid divide-by-zero when all stocks have equal signal
        cs_std_safe = cs_std.replace(0.0, np.nan)
        z_signal = rolling_mean.sub(cs_mean, axis=0).div(cs_std_safe, axis=0)

        return z_signal

    # ---- bucket assignment ---------------------------------------------------

    def assign_buckets(
        self,
        signal_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Assign long (+1), short (−1), or neutral (0) for each (date, stock).

        Long = top bucket by delivery-pct signal.
        Short = bottom bucket.

        Returns
        -------
        pd.DataFrame
            Values in {−1, 0, +1, NaN}.
        """
        frac = _BUCKET_FRAC[self.bucket]
        bucket_df = pd.DataFrame(
            np.nan, index=signal_df.index, columns=signal_df.columns,
        )

        for dt in signal_df.index:
            row = signal_df.loc[dt].dropna()
            if len(row) < 2:
                continue
            n_bucket = max(1, int(np.floor(len(row) * frac)))
            sorted_syms = row.sort_values()
            short_syms = sorted_syms.index[:n_bucket]
            long_syms = sorted_syms.index[-n_bucket:]
            bucket_df.loc[dt, short_syms] = -1.0
            bucket_df.loc[dt, long_syms] = 1.0
            # Neutral for stocks in neither bucket
            neutral = sorted_syms.index[n_bucket:-n_bucket]
            bucket_df.loc[dt, neutral] = 0.0

        return bucket_df

    # ---- IC computation -----------------------------------------------------

    def compute_ic_series(
        self,
        signal_df: pd.DataFrame,
        returns_df: pd.DataFrame,
    ) -> pd.Series:
        """Rank IC (Spearman) at each rebalance date.

        Parameters
        ----------
        signal_df : pd.DataFrame
            Cross-sectional signal values (output of ``compute_signal``).
        returns_df : pd.DataFrame
            Forward returns (output of ``compute_forward_returns`` with
            the matching holding period).

        Returns
        -------
        pd.Series
            Index = rebalance dates (every *holding_period* rows),
            values = Spearman rank correlation (IC).
        """
        from scipy.stats import spearmanr

        common_dates = signal_df.index.intersection(returns_df.index)
        # Rebalance dates: step every holding_period
        rebal_dates = common_dates[:: self.holding_period]

        ics: dict[pd.Timestamp, float] = {}
        for dt in rebal_dates:
            sig = signal_df.loc[dt]
            ret = returns_df.loc[dt]
            # Paired non-NaN
            mask = sig.notna() & ret.notna()
            if mask.sum() < 5:
                log.debug("Skipping %s: only %d paired obs.", dt, mask.sum())
                continue
            rho, _ = spearmanr(sig[mask].values, ret[mask].values)
            if np.isfinite(rho):
                ics[dt] = float(rho)

        ic_series = pd.Series(ics, dtype="float64")
        ic_series.index.name = "date"
        ic_series.name = self.trial_name
        return ic_series


# ---------------------------------------------------------------------------
# Trial enumerator (§4.1)
# ---------------------------------------------------------------------------

def enumerate_trials() -> list[DeliveryPctSignal]:
    """Return all 18 pre-committed delivery-pct trials.

    The order is deterministic: lookback × bucket × holding_period,
    matching the §4.1 table (outer → inner).
    """
    trials: list[DeliveryPctSignal] = []
    for lb in LOOKBACKS:
        for bk in BUCKETS:
            for hp in HOLDING_PERIODS:
                trials.append(DeliveryPctSignal(lb, bk, hp))
    return trials
