"""Binary-outcome calibration gauntlet — the FLB analogue of the Sharpe stack.

Where the Sharpe gauntlet (``sharpe.py`` / ``gates.py``) asks "is this return
stream's risk-adjusted edge real after deflation?", this module asks the
calibration question for prediction markets: do market-implied probabilities
match realized frequencies, or is there an exploitable favorite-longshot bias
(FLB)? Inputs throughout are two aligned arrays — ``predicted`` (market-implied
probabilities in [0, 1]) and ``outcomes`` (binary: 1 = YES resolved, 0 = NO).

Key statistical distinction from the Sharpe stack: prediction-market events are
**independent** resolutions, not an autocorrelated time series. The edge
bootstrap here therefore uses an **iid** resample (each event drawn with
replacement), in contrast to the stationary (geometric-block) bootstrap that
``bootstrap.py`` uses to preserve serial dependence in daily returns.

The gate constructors return :class:`afgauntlet.GateOutcome`, so a calibration
study composes with ``evaluate_gates`` / ``GauntletReport`` exactly like the
Sharpe substrates do.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

from .gates import GateOutcome, _clean

_EPS = 1e-12


def _align(predicted, outcomes) -> tuple[np.ndarray, np.ndarray]:
    """Coerce inputs to aligned finite float arrays of equal length."""
    if isinstance(predicted, pd.Series):
        predicted = predicted.to_numpy()
    if isinstance(outcomes, pd.Series):
        outcomes = outcomes.to_numpy()
    p = np.asarray(predicted, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.shape != y.shape:
        raise ValueError(
            f"predicted and outcomes must share shape, got {p.shape} vs {y.shape}")
    mask = np.isfinite(p) & np.isfinite(y)
    return p[mask], y[mask]


# ─── Scoring rules ────────────────────────────────────────────────────────────

def brier_score(predicted, outcomes) -> float:
    """Mean squared error of the probability forecast: ``mean((p - y)^2)``.

    Lower is better; 0 is perfect. Returns NaN on empty input.
    """
    p, y = _align(predicted, outcomes)
    if p.size == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def log_loss(predicted, outcomes, eps: float = 1e-15) -> float:
    """Mean binary cross-entropy with probabilities clipped to ``[eps, 1-eps]``.

    ``-mean(y·log p + (1-y)·log(1-p))``. Lower is better. Returns NaN on empty
    input. Clipping bounds the penalty for confident-and-wrong forecasts so a
    single p=0 / p=1 miss does not send the score to infinity.
    """
    p, y = _align(predicted, outcomes)
    if p.size == 0:
        return float("nan")
    pc = np.clip(p, eps, 1.0 - eps)
    return float(-np.mean(y * np.log(pc) + (1.0 - y) * np.log(1.0 - pc)))


# ─── Reliability / calibration ───────────────────────────────────────────────

def reliability_curve(predicted, outcomes,
                      bins: Sequence[float]) -> list[dict]:
    """Per-bucket calibration table over the supplied bin edges.

    ``bins`` is a monotone sequence of bucket edges in [0, 1] (the FLB study
    uses cent buckets ``[0, .05, .15, .35, .65, .85, .95, 1.0]``). Each event is
    assigned to the bucket ``(edge[i-1], edge[i]]``; the first bucket is closed
    on the left so events at exactly 0 are included. Empty buckets are skipped.

    Returns one dict per non-empty bucket with::

        {bin_lo, bin_hi, p_mean, realized_freq, count, edge}

    where ``edge = realized_freq - p_mean`` is the calibration gap: positive
    means the market under-priced YES (favorite end), negative means it
    over-priced YES (longshot end) — the signature of favorite-longshot bias.
    """
    p, y = _align(predicted, outcomes)
    edges = np.asarray(list(bins), dtype=float)
    if edges.size < 2:
        raise ValueError("bins must have at least two edges")
    if np.any(np.diff(edges) <= 0):
        raise ValueError("bins must be strictly increasing")

    out: list[dict] = []
    for i in range(1, edges.size):
        lo, hi = float(edges[i - 1]), float(edges[i])
        if i == 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p > lo) & (p <= hi)
        count = int(mask.sum())
        if count == 0:
            continue
        p_mean = float(p[mask].mean())
        realized = float(y[mask].mean())
        out.append({
            "bin_lo": lo,
            "bin_hi": hi,
            "p_mean": p_mean,
            "realized_freq": realized,
            "count": count,
            "edge": realized - p_mean,
        })
    return out


def calibration_slope_intercept(predicted, outcomes) -> tuple[float, float]:
    """Logistic recalibration slope and intercept (Cox 1958 calibration).

    Fits ``logit(P(y=1)) = intercept + slope · logit(predicted)`` by maximum
    likelihood (one-feature logistic regression). A perfectly calibrated market
    gives ``slope == 1`` and ``intercept == 0``: passing the implied log-odds
    through unchanged. ``slope < 1`` indicates forecasts are too extreme
    (over-confident), the regression-to-the-mean signature behind FLB.

    Implementation: predicted probabilities are clipped to ``[eps, 1-eps]`` and
    mapped to log-odds; the 2-parameter fit is solved by Newton-Raphson on the
    log-likelihood (pure numpy, no scipy). Returns ``(slope, intercept)``;
    ``(nan, nan)`` if the design is degenerate (fewer than 3 events, no outcome
    variation, or zero predictor variance).
    """
    p, y = _align(predicted, outcomes)
    if p.size < 3:
        return float("nan"), float("nan")
    # Need both classes present and variation in the predictor to identify slope.
    if y.min() == y.max():
        return float("nan"), float("nan")
    pc = np.clip(p, _EPS, 1.0 - _EPS)
    x = np.log(pc / (1.0 - pc))  # logit of the market-implied probability
    if float(np.std(x)) < _EPS:
        return float("nan"), float("nan")

    # Design matrix [1, x]; params beta = [intercept, slope].
    X = np.column_stack([np.ones_like(x), x])
    beta = np.zeros(2, dtype=float)
    for _ in range(100):
        eta = X @ beta
        mu = 1.0 / (1.0 + np.exp(-eta))           # fitted probabilities
        w = np.clip(mu * (1.0 - mu), _EPS, None)  # IRLS weights
        grad = X.T @ (y - mu)
        hess = (X * w[:, None]).T @ X             # X' W X
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            return float("nan"), float("nan")
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    intercept, slope = float(beta[0]), float(beta[1])
    if not (math.isfinite(slope) and math.isfinite(intercept)):
        return float("nan"), float("nan")
    return slope, intercept


# ─── Edge with iid bootstrap CI ───────────────────────────────────────────────

def bucket_edge_ci(predicted, outcomes, lo: float, hi: float,
                   n_boot: int = 4000, confidence: float = 0.95,
                   seed: int = 0) -> dict:
    """Bootstrap CI for the calibration edge of events with ``lo < p <= hi``.

    The point estimate is ``realized_freq - mean_implied`` over the in-region
    events. Because prediction-market resolutions are **independent**, this uses
    an **iid** bootstrap — resampling whole events with replacement — rather
    than the stationary (geometric-block) bootstrap that ``bootstrap.py`` uses
    for autocorrelated daily returns. There is no serial structure to preserve,
    so block resampling would only add variance.

    Returns ``{edge, lo, hi, n, excludes_zero}`` where ``lo``/``hi`` are the
    ``confidence`` CI bounds on the edge and ``excludes_zero`` is True iff the
    whole interval lies on one side of zero (a detected mispricing).
    """
    if not hi > lo:
        raise ValueError("require hi > lo")
    p, y = _align(predicted, outcomes)
    mask = (p > lo) & (p <= hi)
    pr = p[mask]
    yr = y[mask]
    n = int(pr.size)
    if n == 0:
        return {"edge": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "n": 0, "excludes_zero": False}
    point = float(yr.mean() - pr.mean())
    if n < 2:
        return {"edge": point, "lo": float("nan"), "hi": float("nan"),
                "n": n, "excludes_zero": False}

    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot, dtype=float)
    for k in range(n_boot):
        idx = rng.integers(0, n, size=n)  # iid resample of independent events
        boots[k] = yr[idx].mean() - pr[idx].mean()
    alpha = 1.0 - confidence
    ci_lo = float(np.quantile(boots, alpha / 2.0))
    ci_hi = float(np.quantile(boots, 1.0 - alpha / 2.0))
    excludes_zero = bool((ci_lo > 0.0) or (ci_hi < 0.0))
    return {"edge": point, "lo": ci_lo, "hi": ci_hi, "n": n,
            "excludes_zero": excludes_zero}


# ─── Up-front power analysis ──────────────────────────────────────────────────

def binary_mde(edge: float, base_rate: float, power: float = 0.8,
               alpha: float = 0.05) -> int:
    """Minimum resolved-event count to detect a calibration edge.

    Up-front power analysis for a one-proportion, two-sided test: how many
    resolved events are needed before a realized frequency that differs from the
    market-implied ``base_rate`` by ``edge`` is distinguishable from sampling
    noise? This is the small-N wall that killed PEAD — run it *before*
    collecting data, not after.

    Uses the standard normal-approximation power formula for one proportion::

        n = ( z_{1-α/2}·√(p0·(1-p0)) + z_{power}·√(p1·(1-p1)) )² / edge²

    with ``p0 = base_rate`` and ``p1 = base_rate + edge`` (clamped to (0, 1)).
    The result is rounded **up** (``ceil``). Monotonicity guarantees: smaller
    ``|edge|`` → more events; higher ``power`` → more events.

    Args:
        edge:      signed calibration edge to detect (p1 - p0); |edge| is used.
        base_rate: null proportion p0 ∈ (0, 1).
        power:     target detection power (1 - β) ∈ (0, 1).
        alpha:     two-sided significance level ∈ (0, 1).

    Returns the required event count (int). Raises ``ValueError`` on a zero
    edge or out-of-range base_rate / power / alpha.
    """
    from .deflated import _norm_inv  # lazy: shared standard-normal quantile

    if edge == 0.0:
        raise ValueError("edge must be non-zero (cannot size a null effect)")
    if not (0.0 < base_rate < 1.0):
        raise ValueError("base_rate must be in (0, 1)")
    if not (0.0 < power < 1.0):
        raise ValueError("power must be in (0, 1)")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0, 1)")

    e = abs(float(edge))
    p0 = float(base_rate)
    # Alternative proportion in the signed direction, clamped to (0, 1) for a
    # well-defined variance term; |edge| is the detectable distance.
    p1 = min(max(p0 + (e if edge > 0 else -e), _EPS), 1.0 - _EPS)

    z_alpha = _norm_inv(1.0 - alpha / 2.0)
    z_power = _norm_inv(power)
    num = (z_alpha * math.sqrt(p0 * (1.0 - p0))
           + z_power * math.sqrt(p1 * (1.0 - p1)))
    n = (num * num) / (e * e)
    return int(math.ceil(n))


# ─── Calibration-aware gate constructors ─────────────────────────────────────

def gate_calibration_gap(predicted, outcomes, region_lo: float,
                         region_hi: float, direction: str,
                         min_gap: float) -> GateOutcome:
    """Gate on the calibration edge inside ``(region_lo, region_hi]``.

    ``direction`` is ``"positive"`` (favorite end: realized should exceed
    implied) or ``"negative"`` (longshot end: realized should fall short). The
    gate passes when the signed edge clears ``min_gap`` in that direction —
    i.e. ``edge >= min_gap`` for positive, ``edge <= -min_gap`` for negative.
    ``min_gap`` is a non-negative magnitude.
    """
    if direction not in ("positive", "negative"):
        raise ValueError("direction must be 'positive' or 'negative'")
    p, y = _align(predicted, outcomes)
    mask = (p > region_lo) & (p <= region_hi)
    n = int(mask.sum())
    if n == 0:
        return GateOutcome("CalibrationGap", False, float("nan"),
                           float(min_gap), detail="no events in region")
    edge = float(y[mask].mean() - p[mask].mean())
    if direction == "positive":
        passed = edge >= min_gap
        thr = float(min_gap)
    else:
        passed = edge <= -min_gap
        thr = -float(min_gap)
    return GateOutcome("CalibrationGap", passed, edge, thr,
                       detail=f"{direction} edge, n={n}, "
                              f"region=({region_lo:.2f},{region_hi:.2f}]")


def gate_edge_ci_excludes_zero(predicted, outcomes, region_lo: float,
                               region_hi: float, n_boot: int = 4000,
                               confidence: float = 0.95,
                               seed: int = 0) -> GateOutcome:
    """Gate: the iid-bootstrap CI for the region's edge must exclude zero.

    Composes :func:`bucket_edge_ci`; the gate passes iff the whole CI lies on
    one side of zero (a statistically detected mispricing). Reports the nearer
    CI bound as the gate value against a zero threshold.
    """
    res = bucket_edge_ci(predicted, outcomes, region_lo, region_hi,
                         n_boot=n_boot, confidence=confidence, seed=seed)
    if res["n"] == 0 or not math.isfinite(res["lo"]):
        return GateOutcome("EdgeCIExcludesZero", False, float("nan"), 0.0,
                           detail="insufficient events in region")
    # Value = signed nearer bound (the one closest to zero) for readability.
    near = res["lo"] if res["edge"] > 0 else res["hi"]
    return GateOutcome("EdgeCIExcludesZero", bool(res["excludes_zero"]),
                       float(near), 0.0,
                       detail=f"edge={res['edge']:+.4f}, "
                              f"CI=[{res['lo']:+.4f},{res['hi']:+.4f}], "
                              f"n={res['n']}")


def gate_net_of_fee_edge(gross_edge: float, fee_per_unit: float,
                         threshold: float = 0.0) -> GateOutcome:
    """Gate: the edge net of per-unit trading fees must exceed ``threshold``.

    ``net = |gross_edge| - fee_per_unit``. A calibration edge is only tradeable
    if it survives the venue's per-contract fee/spread; an edge of 0.03 against
    a 0.04 round-trip fee is not deployable. Passes when ``net > threshold``.
    """
    net = abs(float(gross_edge)) - float(fee_per_unit)
    return GateOutcome("NetOfFeeEdge", net > threshold, net, float(threshold),
                       detail=f"gross={gross_edge:+.4f}, fee={fee_per_unit:.4f}")
