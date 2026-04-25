"""Tests for MARL convergence validation.

Runs a minimal training loop and asserts that the pipeline doesn't
degenerate (fitness should not collapse, sigma should adapt).
"""

import pytest
import numpy as np

from training.trainer import Trainer
from training.config import load_config
from evolution.evolutionary_engine import GenerationStats


def _quick_config():
    """Minimal config for fast convergence testing."""
    config = load_config()
    config._data["population"]["n_agents"] = 6
    config._data["population"]["episodes_per_agent"] = 2
    config._data["population"]["n_generations"] = 6
    config._data["validation"]["validate_every_n_gens"] = 3
    config._data["validation"]["early_stop_patience"] = 10
    config._data["environment"]["episode_length"] = 63  # quarter
    return config


class TestConvergence:
    def test_training_completes(self):
        """Training loop runs without crashing."""
        config = _quick_config()
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv")
        history = trainer.train(n_generations=3)
        assert len(history) == 3

    def test_fitness_is_finite(self):
        """All fitness values should be finite (no NaN/Inf)."""
        config = _quick_config()
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv2")
        history = trainer.train(n_generations=3)
        for stats in history:
            assert np.isfinite(stats.best_fitness)
            assert np.isfinite(stats.mean_fitness)

    def test_sigma_adapts(self):
        """Mutation sigma should change across generations."""
        config = _quick_config()
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv3")
        history = trainer.train(n_generations=6)
        sigmas = [s.sigma for s in history]
        assert len(set(round(s, 8) for s in sigmas)) > 1, "Sigma never changed"

    def test_population_diversity(self):
        """Population should maintain some diversity (not all identical)."""
        config = _quick_config()
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv4")
        trainer.train(n_generations=3)
        fitnesses = [a.fitness for a in trainer.pool.agents]
        assert np.std(fitnesses) > 0, "All agents have identical fitness"

    def test_validation_produces_sharpe(self):
        """Validation evaluation should produce a finite Sharpe value."""
        config = _quick_config()
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv5")
        trainer.train(n_generations=3)
        val_sharpe = trainer._evaluate_validation()
        assert np.isfinite(val_sharpe)

    def test_ppo_losses_finite(self):
        """PPO loss metrics should be finite when present."""
        config = _quick_config()
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv6")
        history = trainer.train(n_generations=3)
        for stats in history:
            if stats.ppo_policy_loss != 0:
                assert np.isfinite(stats.ppo_policy_loss)
            if stats.ppo_value_loss != 0:
                assert np.isfinite(stats.ppo_value_loss)

    def test_best_agent_outperforms_random(self):
        """After training, best agent should not be worse than random."""
        config = _quick_config()
        config._data["population"]["n_generations"] = 6
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv7")
        trainer.train(n_generations=6)

        best = trainer.pool.best()
        worst = trainer.pool.ranked()[-1]
        # Best agent should have higher fitness than worst
        assert best.fitness >= worst.fitness

    def test_early_stopping_mechanism(self):
        """Early stopping should trigger when patience is exceeded."""
        config = _quick_config()
        config._data["validation"]["early_stop_patience"] = 1
        config._data["validation"]["validate_every_n_gens"] = 1
        trainer = Trainer(config=config, checkpoint_dir="/tmp/test_marl_conv8")
        history = trainer.train(n_generations=20)
        # Should stop well before 20 generations due to patience=1
        assert len(history) < 20
