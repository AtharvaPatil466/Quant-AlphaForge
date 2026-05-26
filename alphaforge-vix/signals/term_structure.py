"""Term-structure slope signal — Phase 1B (per VIX_DESIGN.md §1.3 + §4.2 + §17.1).

Three slope measures (per §1.3 + §17.1 ADDENDUM — index-ratio proxy, no
futures):

    slope_3M    = VIX3M / VIX        (contango ratio)
    slope_6M    = VIX6M / VIX        (longer-dated contango ratio)
    slope_diff  = VIX3M − VIX        (additive slope, vol points)

Trial set (6 total, per §4.2):

    | Slope measure        | Entry threshold                |
    | -------------------- | ------------------------------ |
    | slope_3M, slope_6M   | ≥ 1.05, ≥ 1.10                 |
    | slope_diff           | ≥ 0.05, ≥ 0.10 (vol points)    |

Forward-return proxy (per §17.7 ADDENDUM, consistent with VRP):

    forward_return_{t,h} = -log(VIX_{t+h} / VIX_t)

Sanity check (per §8.2): contango months (slope > 1 / slope_diff > 0)
must on average earn POSITIVE forward returns. Backwardation months
must average NEGATIVE. If this fails, the index-ratio proxy is broken
and Phase 1 is blocked pending investigation.

Phase 1B pass criteria — same as Phase 1A (per §8.2):
    1. |IC| > 0.05 at at least one horizon.
    2. Positive sign in at least 8 of 11 IS years.
    3. ≥ 6 of 9 ex-2008/09 IS years positive.

Note: VIX3M coverage begins 2009-09-18 and VIX6M coverage begins 2008-01-02
(per Phase 0 cert). For the 2004-2014 IS window, slope-3M and slope-diff
trials have effective coverage 2009-09-18 → 2014-12-31 (~5.3 years);
slope-6M trials have 2008-01-02 → 2014-12-31 (~7 years). Per-trial
n_obs and is_effective_start are reported transparently.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .vrp import (
    IC_HORIZONS,
    IC_THRESHOLD,
    IS_END,
    IS_START,
    MIN_POSITIVE_YEARS_ALL,
    MIN_POSITIVE_YEARS_EX_2008_09,
    compute_forward_return,
    ic_pearson,
    yearly_ic,
)


# ---------------------------------------------------------------------------
# Trial set
# ---------------------------------------------------------------------------

SLOPE_MEASURES: tuple[str, ...] = ("slope_3M", "slope_6M", "slope_diff")

# Thresholds keyed by measure. Ratio measures use 1.05/1.10; the additive
# measure uses the equivalent vol-point cutoffs 0.05/0.10 (per §4.2).
SLOPE_THRESHOLDS: dict[str, tuple[float, float]] = {
    "slope_3M": (1.05, 1.10),
    "slope_6M": (1.05, 1.10),
    "slope_diff": (0.05, 0.10),
}


# ---------------------------------------------------------------------------
# Slope computation
# ---------------------------------------------------------------------------

def compute_slope(panel: pd.DataFrame, measure: str) -> pd.Series:
    """Compute one slope series from the term-structure panel.

    `panel` must have columns: VIX, VIX3M, VIX6M (close prices).
    """
    if measure == "slope_3M":
        if "VIX3M" not in panel.columns or "VIX" not in panel.columns:
            raise KeyError("slope_3M requires VIX3M and VIX columns")
        s = panel["VIX3M"] / panel["VIX"]
    elif measure == "slope_6M":
        if "VIX6M" not in panel.columns or "VIX" not in panel.columns:
            raise KeyError("slope_6M requires VIX6M and VIX columns")
        s = panel["VIX6M"] / panel["VIX"]
    elif measure == "slope_diff":
        if "VIX3M" not in panel.columns or "VIX" not in panel.columns:
            raise KeyError("slope_diff requires VIX3M and VIX columns")
        s = panel["VIX3M"] - panel["VIX"]
    else:
        raise ValueError(f"unknown slope measure {measure!r}; "
                         f"expected one of {SLOPE_MEASURES}")
    return s.rename(measure)


def _signed_slope_signal(slope: pd.Series, threshold: float,
                         measure: str) -> pd.Series:
    """Map slope to a directional signal.

    Above threshold → short-vol (+1). Below `-threshold` (or `2 − threshold`
    for ratio measures) → long-vol (-1). Otherwise flat.

    For ratio measures the "negative" side is `slope < 2 − threshold`,
    i.e., the same magnitude in the backwardation direction. For the
    additive measure it's `slope < -threshold`.
    """
    sig = pd.Series(0.0, index=slope.index)
    if measure in ("slope_3M", "slope_6M"):
        # Ratio: contango threshold 1.05 → backwardation threshold 0.95.
        backwardation_thr = 2.0 - threshold
        sig[slope >= threshold] = 1.0
        sig[slope <= backwardation_thr] = -1.0
    else:  # slope_diff (additive)
        sig[slope >= threshold] = 1.0
        sig[slope <= -threshold] = -1.0
    return sig.rename(f"signal_{measure}_thr{threshold:g}")


# ---------------------------------------------------------------------------
# Sanity check — contango → positive short-vol return
# ---------------------------------------------------------------------------

@dataclass
class ContangoSanityResult:
    measure: str
    contango_n: int
    backwardation_n: int
    contango_mean_fwd_ret_21: float
    backwardation_mean_fwd_ret_21: float
    contango_positive: bool
    backwardation_negative_or_zero: bool
    passed: bool

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def contango_sanity_check(
    panel: pd.DataFrame, vix: pd.Series,
    measure: str = "slope_diff",
    horizon: int = 21,
    is_start: pd.Timestamp = IS_START,
    is_end: pd.Timestamp = IS_END,
) -> ContangoSanityResult:
    """Empirical check: are contango months on average profitable for
    short-vol? Mean forward return is computed for the contango subset
    (slope > 1 ratio, or slope > 0 difference) and the backwardation
    subset. Contango mean must be > 0 for the proxy to be self-consistent.

    Not a hard pass test — used for explicit "block if broken" decision.
    """
    slope = compute_slope(panel, measure)
    fr = compute_forward_return(vix, horizon)
    df = pd.concat([slope.rename("slope"), fr.rename("fr")], axis=1, sort=True).dropna()
    df = df[(df.index >= is_start) & (df.index <= is_end)]
    if measure in ("slope_3M", "slope_6M"):
        contango_mask = df["slope"] > 1.0
        backwardation_mask = df["slope"] < 1.0
    else:  # slope_diff
        contango_mask = df["slope"] > 0.0
        backwardation_mask = df["slope"] < 0.0
    c_mean = float(df.loc[contango_mask, "fr"].mean()) if contango_mask.any() else float("nan")
    b_mean = float(df.loc[backwardation_mask, "fr"].mean()) if backwardation_mask.any() else float("nan")
    c_pos = (not np.isnan(c_mean)) and c_mean > 0.0
    b_neg = (np.isnan(b_mean)) or b_mean <= 0.0
    return ContangoSanityResult(
        measure=measure,
        contango_n=int(contango_mask.sum()),
        backwardation_n=int(backwardation_mask.sum()),
        contango_mean_fwd_ret_21=c_mean,
        backwardation_mean_fwd_ret_21=b_mean,
        contango_positive=bool(c_pos),
        backwardation_negative_or_zero=bool(b_neg),
        passed=bool(c_pos and b_neg),
    )


# ---------------------------------------------------------------------------
# Trial enumeration + evaluation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SlopeTrial:
    measure: str
    threshold: float

    @property
    def name(self) -> str:
        return f"slope_{self.measure}_thr{self.threshold:g}"


def all_trials() -> tuple[SlopeTrial, ...]:
    trials: list[SlopeTrial] = []
    for m in SLOPE_MEASURES:
        for t in SLOPE_THRESHOLDS[m]:
            trials.append(SlopeTrial(measure=m, threshold=t))
    return tuple(trials)


@dataclass
class SlopeTrialResult:
    trial: SlopeTrial
    is_window: tuple[pd.Timestamp, pd.Timestamp]
    is_effective_start: pd.Timestamp | None
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
            "measure": self.trial.measure,
            "threshold": self.trial.threshold,
            "is_start": str(self.is_window[0].date()),
            "is_end": str(self.is_window[1].date()),
            "is_effective_start": (str(self.is_effective_start.date())
                                   if self.is_effective_start is not None else None),
            "n_obs": self.n_obs,
            "ic_by_horizon": {str(k): v for k, v in self.ic_by_horizon.items()},
            "peak_horizon": self.peak_horizon,
            "peak_ic": self.peak_ic,
            "peak_abs_ic": self.peak_abs_ic,
            "yearly_ic_at_peak": {str(k): v for k, v in self.yearly_ic_at_peak.items()},
            "years_positive_all": self.years_positive_all,
            "years_total_all": self.years_total_all,
            "years_positive_ex_2008_09": self.years_positive_ex_2008_09,
            "years_total_ex_2008_09": self.years_total_ex_2008_09,
            "pass_ic_threshold": self.pass_ic_threshold,
            "pass_yearly_all": self.pass_yearly_all,
            "pass_yearly_ex_2008_09": self.pass_yearly_ex_2008_09,
            "passed": self.passed,
        }


def evaluate_trial(
    trial: SlopeTrial,
    panel: pd.DataFrame,
    vix: pd.Series,
    is_start: pd.Timestamp = IS_START,
    is_end: pd.Timestamp = IS_END,
    horizons: tuple[int, ...] = IC_HORIZONS,
) -> SlopeTrialResult:
    slope = compute_slope(panel, trial.measure)
    signal = _signed_slope_signal(slope, trial.threshold, trial.measure)

    mask = (signal.index >= is_start) & (signal.index <= is_end)
    signal_is = signal[mask].dropna()
    if signal_is.empty:
        effective_start: pd.Timestamp | None = None
    else:
        effective_start = signal_is.index.min()

    ic_by_h: dict[int, float] = {}
    fr_full: dict[int, pd.Series] = {}
    for h in horizons:
        fr_full[h] = compute_forward_return(vix, h)
        ic_by_h[h] = ic_pearson(signal_is, fr_full[h].reindex(signal_is.index))

    # Peak horizon = argmax signed IC (slope signal has a fixed
    # directional intent: contango → short vol → expect IC > 0).
    finite = {h: v for h, v in ic_by_h.items() if not np.isnan(v)}
    if not finite:
        peak_h, peak_ic = None, float("nan")
    else:
        peak_h = max(finite, key=lambda h: finite[h])
        peak_ic = ic_by_h[peak_h]
    peak_abs = abs(peak_ic) if not np.isnan(peak_ic) else float("nan")

    if peak_h is None:
        y_ic = pd.Series(dtype=float)
    else:
        y_ic = yearly_ic(signal_is, fr_full[peak_h].reindex(signal_is.index))
    y_ic_dict = {int(y): (float(v) if not np.isnan(v) else float("nan"))
                 for y, v in y_ic.items()}
    years_pos_all = sum(1 for v in y_ic_dict.values()
                        if not np.isnan(v) and v > 0.0)
    years_pos_ex = sum(1 for y, v in y_ic_dict.items()
                       if y not in (2008, 2009)
                       and not np.isnan(v) and v > 0.0)
    years_total_all = sum(1 for v in y_ic_dict.values() if not np.isnan(v))
    years_total_ex = sum(1 for y, v in y_ic_dict.items()
                         if y not in (2008, 2009) and not np.isnan(v))

    pass_ic = (not np.isnan(peak_ic)) and peak_ic >= IC_THRESHOLD
    pass_yall = years_pos_all >= MIN_POSITIVE_YEARS_ALL
    pass_yex = years_pos_ex >= MIN_POSITIVE_YEARS_EX_2008_09
    passed = bool(pass_ic and pass_yall and pass_yex)

    paired_n = pd.concat(
        [signal_is.rename("s"),
         fr_full.get(21, list(fr_full.values())[0]).reindex(signal_is.index).rename("r")],
        axis=1,
        sort=True,
    ).dropna().shape[0]

    return SlopeTrialResult(
        trial=trial,
        is_window=(is_start, is_end),
        is_effective_start=effective_start,
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
    panel: pd.DataFrame,
    vix: pd.Series,
    is_start: pd.Timestamp = IS_START,
    is_end: pd.Timestamp = IS_END,
) -> list[SlopeTrialResult]:
    return [evaluate_trial(t, panel, vix, is_start, is_end) for t in all_trials()]
