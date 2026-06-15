"""Power calibration for the canonical gauntlet — the minimum detectable effect.

Answers the question eight failed substrates cannot answer on their own: *is the
gauntlet rejecting because the alpha isn't there, or because the instrument is
too blunt to see it?* We inject synthetic alpha of known strength onto realistic
return noise, Monte-Carlo how often the gauntlet detects it, and find the
crossover Sharpe (the MDE).
"""
from .calibrate import (PowerPoint, daily_log_returns, find_mde,
                        inject_alpha, load_base_returns, power_at, power_curve)

__all__ = [
    "load_base_returns", "daily_log_returns", "inject_alpha",
    "power_at", "power_curve", "find_mde", "PowerPoint",
]
