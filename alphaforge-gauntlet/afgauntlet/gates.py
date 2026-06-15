"""Canonical gate evaluator.

Substrates pre-commit *different* gate sets (VIX used six, India five, the
equity stack three). Rather than hard-code one gate list, this module provides
a small set of standard gate constructors plus a ``GauntletReport`` aggregator,
so each substrate composes exactly its pre-committed gates from one audited
implementation. ``deploy_ready`` is the AND of every gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .bootstrap import stationary_bootstrap_sharpe_ci
from .deflated import deflated_sharpe_ratio
from .sharpe import (annualized_sharpe, cornish_fisher_sharpe,
                     sample_excess_kurtosis, sample_skewness)


@dataclass(frozen=True)
class GateOutcome:
    name: str
    passed: bool
    value: float
    threshold: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": bool(self.passed),
            "value": float(self.value),
            "threshold": float(self.threshold),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GauntletReport:
    gates: tuple[GateOutcome, ...]

    @property
    def deploy_ready(self) -> bool:
        return len(self.gates) > 0 and all(g.passed for g in self.gates)

    @property
    def n_passed(self) -> int:
        return sum(1 for g in self.gates if g.passed)

    @property
    def n_total(self) -> int:
        return len(self.gates)

    def to_dict(self) -> dict:
        return {
            "deploy_ready": self.deploy_ready,
            "n_passed": self.n_passed,
            "n_total": self.n_total,
            "gates": [g.to_dict() for g in self.gates],
        }

    def summary(self) -> str:
        lines = [f"{'PASS' if g.passed else 'FAIL'}  {g.name:<22} "
                 f"value={g.value:+.4f} thr={g.threshold:+.4f}"
                 + (f"  ({g.detail})" if g.detail else "")
                 for g in self.gates]
        verdict = "DEPLOY-READY" if self.deploy_ready else "REJECTED"
        lines.append(f"--> {verdict}  ({self.n_passed}/{self.n_total} gates)")
        return "\n".join(lines)


# ─── Standard gate constructors ──────────────────────────────────────────────

def gate_deflated_sharpe(
    daily_returns: np.ndarray | pd.Series,
    n_trials: int,
    threshold: float = 0.95,
) -> GateOutcome:
    r = _clean(daily_returns)
    sr = annualized_sharpe(r)
    dsr = deflated_sharpe_ratio(
        sharpe_observed=sr,
        n_trials=n_trials,
        n_obs=r.size,
        skewness=sample_skewness(r) if r.size >= 3 else 0.0,
        excess_kurtosis=sample_excess_kurtosis(r) if r.size >= 4 else 0.0,
    )
    val = 0.0 if np.isnan(dsr) else dsr
    return GateOutcome("DSR", val > threshold, val, threshold,
                       detail=f"sharpe={sr:+.3f}, n_trials={n_trials}, n_obs={r.size}")


def gate_bootstrap_excludes_zero(
    daily_returns: np.ndarray | pd.Series,
    n_replications: int = 4000,
    expected_block_size: int = 21,
    confidence: float = 0.95,
    seed: int = 0,
) -> GateOutcome:
    ci = stationary_bootstrap_sharpe_ci(
        daily_returns, n_replications=n_replications,
        expected_block_size=expected_block_size, confidence=confidence, seed=seed)
    return GateOutcome("BootstrapCI", ci.excludes_zero, ci.lower, 0.0,
                       detail=f"sharpe={ci.sharpe:+.3f}, CI=[{ci.lower:+.3f},{ci.upper:+.3f}]")


def gate_sign_agreement(
    returns_oos_a: np.ndarray | pd.Series,
    returns_oos_b: np.ndarray | pd.Series,
) -> GateOutcome:
    s_a = annualized_sharpe(returns_oos_a)
    s_b = annualized_sharpe(returns_oos_b)
    ok = bool(np.isfinite(s_a) and np.isfinite(s_b) and s_a > 0 and s_b > 0)
    return GateOutcome("SignAgreement", ok, min(s_a, s_b), 0.0,
                       detail=f"OOS_A={s_a:+.3f}, OOS_B={s_b:+.3f}")


def gate_cost_survival(
    daily_returns_stressed: np.ndarray | pd.Series,
    threshold: float = 0.0,
) -> GateOutcome:
    """Sharpe under a stressed (e.g. doubled) cost assumption must stay above
    ``threshold`` (default: positive)."""
    sr = annualized_sharpe(daily_returns_stressed)
    val = 0.0 if np.isnan(sr) else sr
    return GateOutcome("CostSurvival", val > threshold, val, threshold,
                       detail="sharpe under stressed costs")


def gate_max_drawdown(
    nav_series: np.ndarray | pd.Series,
    max_drawdown: float = 0.30,
) -> GateOutcome:
    """Peak-to-trough drawdown of the NAV path must not exceed ``max_drawdown``
    (reported as a positive fraction)."""
    nav = _clean(nav_series)
    if nav.size < 2:
        return GateOutcome("MaxDrawdown", False, float("nan"), max_drawdown,
                           detail="insufficient NAV history")
    running_peak = np.maximum.accumulate(nav)
    dd = (nav - running_peak) / running_peak
    worst = float(-dd.min())  # positive magnitude
    return GateOutcome("MaxDrawdown", worst <= max_drawdown, worst, max_drawdown,
                       detail="peak-to-trough")


def gate_cornish_fisher(
    daily_returns: np.ndarray | pd.Series,
    threshold: float = 0.5,
    alpha: float = 0.05,
) -> GateOutcome:
    cf = cornish_fisher_sharpe(daily_returns, alpha=alpha)
    val = 0.0 if np.isnan(cf) else cf
    return GateOutcome("CornishFisher", val > threshold, val, threshold,
                       detail="tail-penalized Sharpe")


def evaluate_gates(gates: Sequence[GateOutcome]) -> GauntletReport:
    """Aggregate a pre-committed list of gate outcomes into a report."""
    return GauntletReport(tuple(gates))


def _clean(x: np.ndarray | pd.Series) -> np.ndarray:
    if isinstance(x, pd.Series):
        x = x.dropna().to_numpy()
    x = np.asarray(x, dtype=float)
    return x[np.isfinite(x)]
