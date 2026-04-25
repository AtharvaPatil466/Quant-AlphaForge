"""Pre-trade risk checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class RiskCheckResult:
    passed: bool
    failures: List[str]


def check_pre_trade(
    target_weights: Dict[str, float],
    current_nav: float,
    max_position_pct: float = 0.10,
    max_gross_exposure: float = 1.50,
    max_daily_turnover: float = 0.30,
    current_weights: Dict[str, float] | None = None,
) -> RiskCheckResult:
    """Run all pre-trade risk checks. Returns pass/fail + failure reasons."""
    failures: List[str] = []
    current_weights = current_weights or {}

    # Max single position
    for ticker, weight in target_weights.items():
        if abs(weight) > max_position_pct:
            failures.append(
                f"{ticker} weight {weight:.2%} exceeds max {max_position_pct:.2%}"
            )

    # Max gross exposure
    gross = sum(abs(w) for w in target_weights.values())
    if gross > max_gross_exposure:
        failures.append(
            f"Gross exposure {gross:.2%} exceeds max {max_gross_exposure:.2%}"
        )

    # Max daily turnover
    all_tickers = set(target_weights.keys()) | set(current_weights.keys())
    turnover = sum(
        abs(target_weights.get(t, 0.0) - current_weights.get(t, 0.0))
        for t in all_tickers
    )
    if turnover > max_daily_turnover:
        failures.append(
            f"Daily turnover {turnover:.2%} exceeds max {max_daily_turnover:.2%}"
        )

    return RiskCheckResult(passed=len(failures) == 0, failures=failures)


def check_circuit_breakers(
    daily_return: float,
    drawdown: float,
    max_daily_loss: float = 0.02,
    max_drawdown: float = 0.10,
) -> RiskCheckResult:
    """Check circuit breakers. If triggered, trading should halt."""
    failures: List[str] = []

    if daily_return < -max_daily_loss:
        failures.append(
            f"Daily loss {daily_return:.2%} exceeds limit {-max_daily_loss:.2%}"
        )

    if drawdown > max_drawdown:
        failures.append(
            f"Drawdown {drawdown:.2%} exceeds limit {max_drawdown:.2%}"
        )

    return RiskCheckResult(passed=len(failures) == 0, failures=failures)
