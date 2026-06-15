"""afgauntlet — the canonical AlphaForge evaluation gauntlet.

One audited, version-pinned implementation of every statistic the substrate
verdicts depend on: Sharpe + higher moments, the Deflated Sharpe Ratio,
stationary-bootstrap Sharpe CIs, Hansen SPA / White's Reality Check, and
purged+embargoed cross-validation, plus a flexible six-gate evaluator.

Historically each substrate (crypto, PEAD, India, VIX) shipped its own copy of
these primitives. This package consolidates them so (a) every future verdict
runs identical, unit-tested code, and (b) ``source_hash()`` lets a verdict pin
exactly which code produced it. Reconciliation tests prove it reproduces the
upstream substrate numbers to float equality.
"""
from __future__ import annotations

from .bootstrap import (SharpeBootstrapCI, stationary_bootstrap_indices,
                        stationary_bootstrap_sharpe_ci)
from .cross_val import PurgedEmbargoedKFold, cross_sectional_ic_cv
from .deflated import (deflated_sharpe_ratio,
                       deflated_sharpe_ratio_from_trials, expected_max_sharpe)
from .gates import (GateOutcome, GauntletReport, evaluate_gates,
                    gate_bootstrap_excludes_zero, gate_cornish_fisher,
                    gate_cost_survival, gate_deflated_sharpe,
                    gate_max_drawdown, gate_sign_agreement)
from .multiple_testing import hansen_spa_test, white_reality_check
from .precommit import (PreRegistration, PreRegistrationError,
                        assert_trial_count, compute_contract_hash,
                        verify_contract_hash)
from .sharpe import (ANNUALIZATION, annualized_sharpe, cornish_fisher_sharpe,
                     sample_excess_kurtosis, sample_skewness, sign_agreement)
from .version import __version__, source_hash

__all__ = [
    "__version__", "source_hash", "ANNUALIZATION",
    "annualized_sharpe", "cornish_fisher_sharpe", "sample_skewness",
    "sample_excess_kurtosis", "sign_agreement",
    "deflated_sharpe_ratio", "deflated_sharpe_ratio_from_trials",
    "expected_max_sharpe",
    "stationary_bootstrap_indices", "stationary_bootstrap_sharpe_ci",
    "SharpeBootstrapCI",
    "hansen_spa_test", "white_reality_check",
    "PurgedEmbargoedKFold", "cross_sectional_ic_cv",
    "GateOutcome", "GauntletReport", "evaluate_gates",
    "gate_deflated_sharpe", "gate_bootstrap_excludes_zero",
    "gate_sign_agreement", "gate_cost_survival", "gate_max_drawdown",
    "gate_cornish_fisher",
    "PreRegistration", "PreRegistrationError", "compute_contract_hash",
    "verify_contract_hash", "assert_trial_count",
]
