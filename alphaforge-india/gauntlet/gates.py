"""Five-gate gauntlet for alphaforge-india signal evaluation.

Per research/INDIA_DESIGN.md §5 and §10:

    Gate 1 — DSR > 0.95 (both OOS-A and OOS-B)
    Gate 2 — Bootstrap CI excludes zero (both OOS-A and OOS-B)
    Gate 3 — Sign agreement (positive Sharpe in both OOS windows)
    Gate 4 — Cost survival under doubled Indian regulatory stack
    Gate 5 — Regime stress test (4-of-4 + 60% positive months)

Architecture:
    Each gate is a pure function returning a GateResult.
    The orchestrator runs all five and reports pass/fail per trial.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("india.gauntlet")


# ---------------------------------------------------------------------------
# Window definitions
# ---------------------------------------------------------------------------

IS_START = date(2004, 1, 1)
IS_END = date(2014, 12, 31)

OOS_A_START = date(2015, 1, 1)
OOS_A_END = date(2019, 12, 31)

OOS_B_START = date(2020, 1, 1)
OOS_B_END = date(2026, 5, 18)  # present

EMBARGO_DAYS = 21  # trading days at each window boundary

# Gate 5 stress periods (§5.5)
STRESS_PERIODS = [
    ("2008_crisis", date(2008, 1, 1), date(2009, 6, 30)),
    ("2013_taper_tantrum", date(2013, 5, 1), date(2013, 9, 30)),
    ("2020_covid", date(2020, 2, 1), date(2020, 12, 31)),
    ("2022_rate_cycle", date(2022, 1, 1), date(2022, 12, 31)),
]

# Total pre-committed trials for DSR deflation
N_TRIALS = 22


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Result of a single gate evaluation."""
    gate_name: str
    passed: bool
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class GauntletResult:
    """Result of running the full 5-gate gauntlet on a single trial."""
    trial_name: str
    gate_results: list[GateResult]

    @property
    def all_gates_passed(self) -> bool:
        return all(g.passed for g in self.gate_results)

    def summary(self) -> str:
        lines = [f"=== {self.trial_name} ==="]
        for g in self.gate_results:
            status = "PASS" if g.passed else "FAIL"
            lines.append(f"  Gate {g.gate_name}: {status} — {g.summary}")
        verdict = "DEPLOY-READY" if self.all_gates_passed else "FAILED"
        lines.append(f"  Verdict: {verdict}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utility: Sharpe ratio
# ---------------------------------------------------------------------------

def sharpe_ratio(returns: np.ndarray, annualize: float = 252.0) -> float:
    """Annualized Sharpe ratio. Returns 0.0 on degenerate input."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2 or np.std(r) == 0:
        return 0.0
    return float(np.mean(r) / np.std(r) * np.sqrt(annualize))


def split_oos_returns(
    daily_returns: pd.Series,
) -> tuple[np.ndarray, np.ndarray]:
    """Split returns into OOS-A and OOS-B arrays."""
    idx = daily_returns.index
    if hasattr(idx[0], 'date'):
        dates = pd.Series([d.date() if hasattr(d, 'date') else d for d in idx])
    else:
        dates = pd.Series(idx)

    oos_a_mask = (dates >= OOS_A_START) & (dates <= OOS_A_END)
    oos_b_mask = (dates >= OOS_B_START) & (dates <= OOS_B_END)

    return (
        daily_returns.values[oos_a_mask.values],
        daily_returns.values[oos_b_mask.values],
    )


# ---------------------------------------------------------------------------
# Gate 1 — Deflated Sharpe Ratio
# ---------------------------------------------------------------------------

def deflated_sharpe_ratio(
    sharpe_obs: float,
    n_trials: int = N_TRIALS,
    n_obs: int = 252,
    skew: float = 0.0,
    kurt_excess: float = 0.0,
) -> float:
    """Bailey & López de Prado (2014) DSR.

    Returns the probability that the observed Sharpe is significant
    after correcting for multiple testing.

    DSR = Φ((SR_obs - SR_0) / σ(SR))

    where SR_0 ≈ √(2 * ln(N)) * (1 - γ / √(2 * ln(N)))  (Euler γ ≈ 0.5772)
    and σ(SR) = √(1 / n * (1 - γ₃ * SR + (γ₄ - 1)/4 * SR²))
    """
    from scipy.stats import norm

    euler_gamma = 0.5772156649
    if n_trials <= 1:
        return 1.0 if sharpe_obs > 0 else 0.0

    # Expected max Sharpe under the null (Euler approximation)
    sqrt_2ln = np.sqrt(2.0 * np.log(n_trials))
    sr_0 = sqrt_2ln * (1.0 - euler_gamma / sqrt_2ln)

    # Standard error of the Sharpe estimator
    se_sr = np.sqrt(
        (1.0 + 0.5 * sharpe_obs**2
         - skew * sharpe_obs
         + (kurt_excess / 4.0) * sharpe_obs**2)
        / max(n_obs, 1)
    )

    if se_sr <= 0:
        return 0.0

    z = (sharpe_obs - sr_0) / se_sr
    return float(norm.cdf(z))


def gate1_dsr(
    oos_a_returns: np.ndarray,
    oos_b_returns: np.ndarray,
    n_trials: int = N_TRIALS,
    threshold: float = 0.95,
) -> GateResult:
    """Gate 1: DSR > threshold in both OOS-A and OOS-B."""
    sr_a = sharpe_ratio(oos_a_returns)
    sr_b = sharpe_ratio(oos_b_returns)

    dsr_a = deflated_sharpe_ratio(sr_a, n_trials=n_trials, n_obs=len(oos_a_returns))
    dsr_b = deflated_sharpe_ratio(sr_b, n_trials=n_trials, n_obs=len(oos_b_returns))

    passed = dsr_a > threshold and dsr_b > threshold

    return GateResult(
        gate_name="1_DSR",
        passed=passed,
        summary=(
            f"DSR_A={dsr_a:.4f} (SR={sr_a:.3f}), "
            f"DSR_B={dsr_b:.4f} (SR={sr_b:.3f}), "
            f"threshold={threshold}"
        ),
        metrics={
            "sharpe_a": sr_a, "sharpe_b": sr_b,
            "dsr_a": dsr_a, "dsr_b": dsr_b,
            "threshold": threshold, "n_trials": n_trials,
        },
    )


# ---------------------------------------------------------------------------
# Gate 2 — Stationary Bootstrap CI
# ---------------------------------------------------------------------------

def stationary_bootstrap_sharpe(
    returns: np.ndarray,
    n_boot: int = 4000,
    block_mean: int = 21,
    seed: int = 42,
) -> tuple[float, float]:
    """Stationary bootstrap (Politis & Romano 1994) 95% CI for Sharpe.

    Returns (ci_lower, ci_upper).
    """
    rng = np.random.default_rng(seed)
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 5:
        return (0.0, 0.0)

    p = 1.0 / block_mean  # geometric probability
    sharpes = np.empty(n_boot)

    for b in range(n_boot):
        # Build one bootstrap sample
        sample = np.empty(n)
        i = rng.integers(0, n)
        for j in range(n):
            sample[j] = r[i]
            if rng.random() < p:
                i = rng.integers(0, n)
            else:
                i = (i + 1) % n
        s = np.std(sample)
        sharpes[b] = (np.mean(sample) / s * np.sqrt(252.0)) if s > 0 else 0.0

    return (float(np.percentile(sharpes, 2.5)),
            float(np.percentile(sharpes, 97.5)))


def gate2_bootstrap_ci(
    oos_a_returns: np.ndarray,
    oos_b_returns: np.ndarray,
    n_boot: int = 4000,
    block_mean: int = 21,
) -> GateResult:
    """Gate 2: 95% bootstrap CI excludes zero in both OOS windows."""
    ci_a = stationary_bootstrap_sharpe(oos_a_returns, n_boot, block_mean, seed=42)
    ci_b = stationary_bootstrap_sharpe(oos_b_returns, n_boot, block_mean, seed=43)

    a_excludes_zero = ci_a[0] > 0 or ci_a[1] < 0
    b_excludes_zero = ci_b[0] > 0 or ci_b[1] < 0
    passed = a_excludes_zero and b_excludes_zero

    return GateResult(
        gate_name="2_Bootstrap_CI",
        passed=passed,
        summary=(
            f"OOS-A CI=[{ci_a[0]:.3f}, {ci_a[1]:.3f}] "
            f"{'excl 0' if a_excludes_zero else 'incl 0'}, "
            f"OOS-B CI=[{ci_b[0]:.3f}, {ci_b[1]:.3f}] "
            f"{'excl 0' if b_excludes_zero else 'incl 0'}"
        ),
        metrics={
            "ci_a_lower": ci_a[0], "ci_a_upper": ci_a[1],
            "ci_b_lower": ci_b[0], "ci_b_upper": ci_b[1],
        },
    )


# ---------------------------------------------------------------------------
# Gate 3 — Sign Agreement
# ---------------------------------------------------------------------------

def gate3_sign_agreement(
    oos_a_returns: np.ndarray,
    oos_b_returns: np.ndarray,
) -> GateResult:
    """Gate 3: Sharpe positive in both OOS-A and OOS-B."""
    sr_a = sharpe_ratio(oos_a_returns)
    sr_b = sharpe_ratio(oos_b_returns)
    passed = sr_a > 0 and sr_b > 0

    return GateResult(
        gate_name="3_Sign_Agreement",
        passed=passed,
        summary=f"SR_A={sr_a:.3f}, SR_B={sr_b:.3f} — {'both positive' if passed else 'sign disagreement'}",
        metrics={"sharpe_a": sr_a, "sharpe_b": sr_b},
    )


# ---------------------------------------------------------------------------
# Gate 4 — Cost Survival (Doubled Indian Stack)
# ---------------------------------------------------------------------------

def gate4_cost_survival(
    oos_a_returns: np.ndarray,
    oos_b_returns: np.ndarray,
    oos_a_gross_returns: np.ndarray | None = None,
    oos_b_gross_returns: np.ndarray | None = None,
    base_round_trip_bps: float = 35.9,
    base_impact_bps: float = 10.0,
    avg_turnover: float = 1.0,
) -> GateResult:
    """Gate 4: Positive Sharpe under doubled costs in both OOS windows.

    If gross_returns are provided, costs are deducted from those.
    Otherwise, the already-costed returns are doubled in cost haircut
    (approximate method).
    """
    stress_multiplier = 2.0
    stressed_rt = base_round_trip_bps * stress_multiplier
    stressed_impact = base_impact_bps * stress_multiplier

    daily_cost_bps = (stressed_rt + stressed_impact * avg_turnover) / 252.0

    if oos_a_gross_returns is not None and oos_b_gross_returns is not None:
        stressed_a = oos_a_gross_returns - daily_cost_bps / 10000.0
        stressed_b = oos_b_gross_returns - daily_cost_bps / 10000.0
    else:
        # Approximate: apply additional cost haircut to net returns
        additional_cost = daily_cost_bps / 10000.0 / 2.0  # half since already costed
        stressed_a = oos_a_returns - additional_cost
        stressed_b = oos_b_returns - additional_cost

    sr_a = sharpe_ratio(stressed_a)
    sr_b = sharpe_ratio(stressed_b)
    passed = sr_a > 0 and sr_b > 0

    return GateResult(
        gate_name="4_Cost_Survival",
        passed=passed,
        summary=(
            f"Stressed SR_A={sr_a:.3f}, SR_B={sr_b:.3f} "
            f"(2× costs: {stressed_rt:.1f}bp RT + {stressed_impact:.1f}bp impact)"
        ),
        metrics={
            "stressed_sharpe_a": sr_a, "stressed_sharpe_b": sr_b,
            "stressed_round_trip_bps": stressed_rt,
            "stressed_impact_bps": stressed_impact,
        },
    )


# ---------------------------------------------------------------------------
# Gate 5 — Regime Stress Test
# ---------------------------------------------------------------------------

def gate5_regime_stress(
    daily_returns: pd.Series,
    stress_periods: list[tuple[str, date, date]] | None = None,
    min_positive_month_frac: float = 0.60,
) -> GateResult:
    """Gate 5: Positive Sharpe in all 4 stress periods + 60% positive months.

    Requires 4-of-4 pass (not 3-of-4).
    """
    if stress_periods is None:
        stress_periods = STRESS_PERIODS

    idx = daily_returns.index
    if hasattr(idx[0], 'date'):
        dates = pd.Series([d.date() if hasattr(d, 'date') else d for d in idx],
                          index=idx)
    else:
        dates = pd.Series(idx, index=idx)

    period_results: list[dict[str, Any]] = []
    all_passed = True

    for name, start, end in stress_periods:
        mask = (dates >= start) & (dates <= end)
        period_rets = daily_returns[mask.values]

        if len(period_rets) < 5:
            period_results.append({
                "period": name, "sharpe": 0.0, "positive_month_frac": 0.0,
                "passed": False, "reason": "insufficient data",
            })
            all_passed = False
            continue

        sr = sharpe_ratio(period_rets.values)

        # Monthly returns for positive-month check
        monthly = period_rets.resample("ME").sum()
        if len(monthly) == 0:
            pos_frac = 0.0
        else:
            pos_frac = float((monthly > 0).mean())

        period_pass = sr > 0 and pos_frac >= min_positive_month_frac
        if not period_pass:
            all_passed = False

        period_results.append({
            "period": name,
            "sharpe": sr,
            "positive_month_frac": pos_frac,
            "passed": period_pass,
        })

    summary_parts = [
        f"{p['period']}: SR={p['sharpe']:.3f} "
        f"pos_months={p['positive_month_frac']:.1%} "
        f"{'✓' if p['passed'] else '✗'}"
        for p in period_results
    ]

    return GateResult(
        gate_name="5_Regime_Stress",
        passed=all_passed,
        summary=f"4-of-4 required: {'; '.join(summary_parts)}",
        metrics={"period_results": period_results},
    )


# ---------------------------------------------------------------------------
# Full gauntlet orchestrator
# ---------------------------------------------------------------------------

def run_gauntlet(
    trial_name: str,
    daily_returns: pd.Series,
    n_trials: int = N_TRIALS,
    daily_gross_returns: pd.Series | None = None,
    avg_turnover: float = 1.0,
) -> GauntletResult:
    """Run the full 5-gate gauntlet on a single trial's daily return series.

    Parameters
    ----------
    trial_name : str
        Human-readable trial identifier.
    daily_returns : pd.Series
        Net daily returns (after base costs). DatetimeIndex required.
    n_trials : int
        Total pre-committed trials for DSR deflation.
    daily_gross_returns : pd.Series, optional
        Gross returns before costs. If provided, Gate 4 uses these
        for accurate stress-costing. Otherwise, approximate method.
    avg_turnover : float
        Average daily turnover (fraction of portfolio).
    """
    oos_a, oos_b = split_oos_returns(daily_returns)

    gross_a, gross_b = None, None
    if daily_gross_returns is not None:
        gross_a, gross_b = split_oos_returns(daily_gross_returns)

    gates = [
        gate1_dsr(oos_a, oos_b, n_trials=n_trials),
        gate2_bootstrap_ci(oos_a, oos_b),
        gate3_sign_agreement(oos_a, oos_b),
        gate4_cost_survival(oos_a, oos_b, gross_a, gross_b,
                            avg_turnover=avg_turnover),
        gate5_regime_stress(daily_returns),
    ]

    return GauntletResult(trial_name=trial_name, gate_results=gates)
