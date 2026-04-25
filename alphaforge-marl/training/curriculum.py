"""Curriculum learning: progressive difficulty for market environments.

Starts with easier trading conditions (lower volatility, stronger trends)
and gradually increases difficulty as agents improve, preventing early
random agents from wasting compute on impossible environments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class CurriculumStage:
    """A single difficulty stage."""
    name: str
    # Environment overrides
    tx_cost_bps: int = 5
    max_gross_exposure: float = 1.50
    stop_loss: float = 0.03
    episode_length: int = 252
    # Promotion criteria
    min_fitness: float = 0.0
    min_generations: int = 5


# Default curriculum: 4 stages of increasing difficulty
DEFAULT_CURRICULUM = [
    CurriculumStage(
        name="beginner",
        tx_cost_bps=1,              # Very low transaction costs
        max_gross_exposure=2.0,     # Generous leverage
        stop_loss=0.05,             # Wider stops
        episode_length=126,         # Half-year (faster feedback)
        min_fitness=-1.0,           # Easy promotion
        min_generations=3,
    ),
    CurriculumStage(
        name="intermediate",
        tx_cost_bps=3,
        max_gross_exposure=1.75,
        stop_loss=0.04,
        episode_length=189,         # 3/4 year
        min_fitness=0.0,
        min_generations=5,
    ),
    CurriculumStage(
        name="advanced",
        tx_cost_bps=5,              # Standard costs
        max_gross_exposure=1.50,
        stop_loss=0.03,
        episode_length=252,         # Full year
        min_fitness=0.5,
        min_generations=8,
    ),
    CurriculumStage(
        name="expert",
        tx_cost_bps=8,              # Higher costs (realistic slippage)
        max_gross_exposure=1.25,    # Tighter leverage
        stop_loss=0.02,             # Tighter stops
        episode_length=252,
        min_fitness=float("inf"),   # Never auto-promote (terminal stage)
        min_generations=999,
    ),
]


class CurriculumScheduler:
    """Manages progression through curriculum stages.

    Tracks current difficulty level and promotes to the next stage when
    the population meets the promotion criteria (fitness threshold +
    minimum generations at current stage).
    """

    def __init__(
        self,
        stages: list[CurriculumStage] | None = None,
        enabled: bool = True,
    ):
        self.stages = stages or list(DEFAULT_CURRICULUM)
        self.enabled = enabled
        self.current_stage_idx = 0
        self._gens_at_stage = 0

    @property
    def current_stage(self) -> CurriculumStage:
        return self.stages[self.current_stage_idx]

    @property
    def is_final_stage(self) -> bool:
        return self.current_stage_idx >= len(self.stages) - 1

    def step(self, best_fitness: float) -> bool:
        """Check if we should promote to next stage.

        Returns True if promotion occurred.
        """
        if not self.enabled or self.is_final_stage:
            self._gens_at_stage += 1
            return False

        self._gens_at_stage += 1
        stage = self.current_stage

        if (
            best_fitness >= stage.min_fitness
            and self._gens_at_stage >= stage.min_generations
        ):
            self.current_stage_idx += 1
            self._gens_at_stage = 0
            return True

        return False

    def get_env_overrides(self) -> Dict[str, float | int]:
        """Get environment parameter overrides for current stage."""
        stage = self.current_stage
        return {
            "tx_cost_bps": stage.tx_cost_bps,
            "max_gross_exposure": stage.max_gross_exposure,
            "stop_loss": stage.stop_loss,
            "episode_length": stage.episode_length,
        }

    def progress(self) -> float:
        """Return curriculum progress as fraction [0, 1]."""
        if not self.stages:
            return 1.0
        return self.current_stage_idx / max(1, len(self.stages) - 1)
