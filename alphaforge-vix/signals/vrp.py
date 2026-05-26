"""VRP carry signal — Phase 1A (per VIX_DESIGN.md §1.2 + §8.1 + §17.7 ADDENDUM).

VRP_t = VIX_t − realized_vol_t(L)   with L ∈ {10, 21, 63}

Forward return at horizon h (per §17.7 ADDENDUM, 2026-05-21):

    forward_return_{t,h} = -log(VIX_{t+h} / VIX_t)

Positive when VIX falls — i.e., a short-volatility position profits. Pure
spot-VIX proxy; underestimates the contracted-but-unavailable VIX-futures
forward return (makes Phase 1 harder, not easier).

Trial set (18 total): L × VRP threshold × horizon-of-interest
    L ∈ {10, 21, 63}
    VRP threshold ∈ {0, 2, 4} vol points
    holding period ∈ {5, 21} trading days

Phase 1A pass criteria (per §8.1, signed-positive interpretation):
    1. IC > +0.05 at at least one of the 5 horizons {5, 10, 21, 42, 63}.
       The signal as pre-committed is `VRP > threshold → short vol`, which
       has a built-in directional intent: positive VRP should predict
       positive short-vol forward return. A negative IC means the signal
       direction is wrong; per pre-commit discipline this is a FAIL, not
       a sign-flipped pass.
    2. Yearly IC > 0 in at least 8 of 11 IS calendar years (signed).
    3. NOT concentrated in 2008-2009: yearly IC > 0 in at least 6 of the 9
       remaining IS years when 2008+2009 are excluded.

Peak horizon is selected as `argmax(IC)` over the 5 horizons — the most
*positive* IC, not the largest by absolute value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Trial set
# ---------------------------------------------------------------------------

REALIZED_VOL_LOOKBACKS: tuple[int, ...] = (10, 21, 63)
VRP_THRESHOLDS: tuple[float, ...] = (0.0, 2.0, 4.0)
HOLDING_PERIODS: tuple[int, ...] = (5, 21)

IC_HORIZONS: tuple[int, ...] = (5, 10, 21, 42, 63)

# IS window (per §3)
IS_START = pd.Timestamp("2004-03-26")
IS_END = pd.Timestamp("2014-12-31")

# Pass criteria thresholds (per §8.1)
IC_THRESHOLD = 0.05
MIN_POSITIVE_YEARS_ALL = 8       # of 11
MIN_POSITIVE_YEARS_EX_2008_09 = 6  # of 9


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def compute_vrp(vix: pd.Series, realized_vol: pd.Series) -> pd.Series:
    """VRP = VIX − realized_vol. Both inputs are in percent (VIX units)."""
    aligned = pd.concat([vix.rename("vix"), realized_vol.rename("rv")], axis=1, sort=True)
    return (aligned["vix"] - aligned["rv"]).rename("vrp")


def compute_forward_return(vix: pd.Series, horizon: int) -> pd.Series:
    """Short-vol forward return proxy per §17.7 ADDENDUM.

        r_{t,h} = -log(VIX_{t+h} / VIX_t)

    The output is aligned to date t (not t+h) so that strategy[t] and
    forward_return[t] are aligned.
    """
    if horizon <= 0:
        raise ValueError(f"horizon must be positive, got {horizon}")
    vix = vix.astype(float)
    return (-np.log(vix.shift(-horizon) / vix)).rename(f"fwd_ret_h{horizon}")


def ic_pearson(signal: pd.Series, forward_return: pd.Series) -> float:
    """Pearson correlation of signal_t against forward_return_t.

    Drops rows where either is NaN. Returns NaN if fewer than 30 paired obs.
    """
    df = pd.concat([signal.rename("s"), forward_return.rename("r")], axis=1, sort=True).dropna()
    if len(df) < 30:
        return float("nan")
    return float(df["s"].corr(df["r"]))


def yearly_ic(signal: pd.Series, forward_return: pd.Series) -> pd.Series:
    """Pearson IC computed within each calendar year. Index = year (int)."""
    df = pd.concat([signal.rename("s"), forward_return.rename("r")], axis=1, sort=True).dropna()
    df["year"] = df.index.year
    out: dict[int, float] = {}
    for y, sub in df.groupby("year"):
        if len(sub) < 30:
            out[y] = float("nan")
        else:
            out[y] = float(sub["s"].corr(sub["r"]))
    return pd.Series(out, name="yearly_ic").sort_index()


# ---------------------------------------------------------------------------
# Trial enumeration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VrpTrial:
    """A single VRP trial parameter combo. 18 total."""
    lookback: int
    vrp_threshold: float
    holding_period: int

    @property
    def name(self) -> str:
        return (f"vrp_L{self.lookback}_thr{self.vrp_threshold:g}"
                f"_hold{self.holding_period}")


def all_trials() -> tuple[VrpTrial, ...]:
    """Enumerate all 18 pre-committed VRP trials in deterministic order."""
    trials: list[VrpTrial] = []
    for L in REALIZED_VOL_LOOKBACKS:
        for thr in VRP_THRESHOLDS:
            for hold in HOLDING_PERIODS:
                trials.append(VrpTrial(lookback=L, vrp_threshold=thr,
                                       holding_period=hold))
    return tuple(trials)


# ---------------------------------------------------------------------------
# Phase 1A per-trial evaluation
# ---------------------------------------------------------------------------

@dataclass
class VrpTrialResult:
    trial: VrpTrial
    is_window: tuple[pd.Timestamp, pd.Timestamp]
    n_obs: int
    ic_by_horizon: dict[int, float]
    peak_horizon: int | None
    peak_ic: float
    peak_abs_ic: float
    yearly_ic_at_peak: dict[int, float]
    years_positive_all: int
    years_total_all: int
    years_positive_ex_2008_09: int
    years_total_ex_2008_09: int
    pass_ic_threshold: bool
    pass_yearly_all: bool
    pass_yearly_ex_2008_09: bool
    passed: bool

    def to_dict(self) -> dict:
        return {
            "trial_name": self.trial.name,
            "lookback": self.trial.lookback,
            "vrp_threshold": self.trial.vrp_threshold,
            "holding_period": self.trial.holding_period,
            "is_start": str(self.is_window[0].date()),
            "is_end": str(self.is_window[1].date()),
            "n_obs": self.n_obs,
            "ic_by_horizon": {str(k): v for k, v in self.ic_by_horizon.items()},
            "peak_horizon": self.peak_horizon,
            "peak_ic": self.peak_ic,
            "peak_abs_ic": self.peak_abs_ic,
            "yearly_ic_at_peak": {str(k): v
                                  for k, v in self.yearly_ic_at_peak.items()},
            "years_positive_all": self.years_positive_all,
            "years_total_all": self.years_total_all,
            "years_positive_ex_2008_09": self.years_positive_ex_2008_09,
            "years_total_ex_2008_09": self.years_total_ex_2008_09,
            "pass_ic_threshold": self.pass_ic_threshold,
            "pass_yearly_all": self.pass_yearly_all,
            "pass_yearly_ex_2008_09": self.pass_yearly_ex_2008_09,
            "passed": self.passed,
        }


def _signed_signal(vrp: pd.Series, threshold: float) -> pd.Series:
    """Map VRP to a directional signal:
        VRP > threshold  → +1  (short vol)
        VRP < -threshold → -1  (long vol)
        else             →  0  (flat)
    """
    sig = pd.Series(0.0, index=vrp.index)
    sig[vrp > threshold] = 1.0
    sig[vrp < -threshold] = -1.0
    return sig.rename(f"signal_thr{threshold:g}")


def evaluate_trial(
    trial: VrpTrial,
    vix: pd.Series,
    spy_realized_vol_table: pd.DataFrame,
    is_start: pd.Timestamp = IS_START,
    is_end: pd.Timestamp = IS_END,
    horizons: tuple[int, ...] = IC_HORIZONS,
) -> VrpTrialResult:
    """Evaluate one VRP trial against the IS window.

    `spy_realized_vol_table` must have a `realized_vol_<L>` column for the
    trial's lookback. (Produced by `ingest.realized_vol.build_spy_panel`.)
    """
    rv_col = f"realized_vol_{trial.lookback}"
    if rv_col not in spy_realized_vol_table.columns:
        raise KeyError(
            f"missing column {rv_col!r} on SPY panel; available: "
            f"{list(spy_realized_vol_table.columns)}"
        )
    rv = spy_realized_vol_table[rv_col]
    vrp = compute_vrp(vix, rv)
    signal = _signed_signal(vrp, trial.vrp_threshold)

    # Restrict to IS window for Phase 1.
    mask = (signal.index >= is_start) & (signal.index <= is_end)
    signal_is = signal[mask]
    vix_is = vix.reindex(signal.index)[mask]

    # Compute IC at each horizon. Forward returns are computed on the
    # full series (to capture h-step lookahead at the window edge), then
    # filtered to the IS window.
    ic_by_h: dict[int, float] = {}
    forward_returns_full: dict[int, pd.Series] = {}
    for h in horizons:
        fr_full = compute_forward_return(vix, h)
        forward_returns_full[h] = fr_full
        # Effective signal for IC = directional VRP * fwd_ret.
        # (Signal mean is zero only for thr>0 strategies; that's fine — Pearson
        # correlation handles non-zero mean.)
        fr_is = fr_full.reindex(signal_is.index)
        ic_by_h[h] = ic_pearson(signal_is, fr_is)

    # Peak horizon = argmax of *signed* IC, per pre-commit (signal has
    # a fixed directional intent: VRP > thr → short vol → expect IC > 0).
    finite = {h: v for h, v in ic_by_h.items() if not np.isnan(v)}
    if not finite:
        peak_h, peak_ic = None, float("nan")
    else:
        peak_h = max(finite, key=lambda h: finite[h])
        peak_ic = ic_by_h[peak_h]
    peak_abs = abs(peak_ic) if not np.isnan(peak_ic) else float("nan")

    # Yearly IC at the peak horizon.
    if peak_h is None:
        y_ic: pd.Series = pd.Series(dtype=float, name="yearly_ic")
    else:
        y_ic = yearly_ic(signal_is, forward_returns_full[peak_h].reindex(signal_is.index))

    y_ic_dict = {int(y): (float(v) if not np.isnan(v) else float("nan"))
                 for y, v in y_ic.items()}

    # Count years with *positive* yearly IC (signed). Per §8.1 the signal
    # has a fixed directional intent; sign-flips are not pre-committed.
    years_pos_all = sum(1 for v in y_ic_dict.values()
                        if not np.isnan(v) and v > 0.0)
    years_pos_ex = sum(1 for y, v in y_ic_dict.items()
                       if y not in (2008, 2009)
                       and not np.isnan(v) and v > 0.0)
    years_total_all = sum(1 for v in y_ic_dict.values() if not np.isnan(v))
    years_total_ex = sum(1 for y, v in y_ic_dict.items()
                         if y not in (2008, 2009) and not np.isnan(v))

    # Signed positive IC required.
    pass_ic = (not np.isnan(peak_ic)) and peak_ic >= IC_THRESHOLD
    pass_yall = years_pos_all >= MIN_POSITIVE_YEARS_ALL
    pass_yex = years_pos_ex >= MIN_POSITIVE_YEARS_EX_2008_09
    passed = bool(pass_ic and pass_yall and pass_yex)

    # n_obs: number of paired (signal, fwd_ret) observations at the 21-day
    # horizon (canonical) on IS.
    canonical_fr = forward_returns_full.get(21, list(forward_returns_full.values())[0])
    paired_n = pd.concat(
        [signal_is.rename("s"),
         canonical_fr.reindex(signal_is.index).rename("r")],
        axis=1,
        sort=True,
    ).dropna().shape[0]

    return VrpTrialResult(
        trial=trial,
        is_window=(is_start, is_end),
        n_obs=int(paired_n),
        ic_by_horizon={int(h): float(v) for h, v in ic_by_h.items()},
        peak_horizon=int(peak_h) if peak_h is not None else None,
        peak_ic=float(peak_ic),
        peak_abs_ic=float(peak_abs),
        yearly_ic_at_peak=y_ic_dict,
        years_positive_all=int(years_pos_all),
        years_total_all=int(years_total_all),
        years_positive_ex_2008_09=int(years_pos_ex),
        years_total_ex_2008_09=int(years_total_ex),
        pass_ic_threshold=bool(pass_ic),
        pass_yearly_all=bool(pass_yall),
        pass_yearly_ex_2008_09=bool(pass_yex),
        passed=passed,
    )


def evaluate_all(
    vix: pd.Series,
    spy_realized_vol_table: pd.DataFrame,
    is_start: pd.Timestamp = IS_START,
    is_end: pd.Timestamp = IS_END,
) -> list[VrpTrialResult]:
    """Evaluate all 18 VRP trials. Returns results in deterministic order."""
    return [evaluate_trial(t, vix, spy_realized_vol_table, is_start, is_end)
            for t in all_trials()]
