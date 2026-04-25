"""Tests for training orchestrator, checkpointing, and logging (Phase 5)."""

from __future__ import annotations

import os
import sys
import tempfile
import math
from types import SimpleNamespace

import numpy as np
import torch
import pytest

_MARL = os.path.dirname(os.path.dirname(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
for p in [os.path.join(_ROOT, "alphaforge-python"), _MARL]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agents.agent_pool import AgentPool
from agents.base_agent import AgentType
from env.trading_env import TradingEnv
from evolution.evolutionary_engine import EvolutionaryEngine, GenerationStats
from training.config import Config, load_config
from training.checkpoint import save_checkpoint, load_checkpoint
from training.logger import TrainingLogger
from training.baselines import compute_performance_metrics, evaluate_baselines, simulate_supervised_baseline
from training.benchmark import BenchmarkReport, classify_window_regimes
from training.trainer import Trainer
from data.synthetic import generate_dataset


# ── Config ──────────────────────────────────────────────────────


class TestConfig:
    def test_load_default_config(self):
        config = load_config()
        assert config.population.get("n_agents") == 30
        assert config.ppo.get("learning_rate") == 1e-3
        assert config.environment.get("obs_dim") == 57

    def test_dotted_access(self):
        config = load_config()
        assert config.network.get("hidden_sizes") == [128, 64]
        assert config.mutation.get("sigma_init") == 0.02

    def test_missing_key_raises(self):
        config = Config(_data={"a": 1})
        with pytest.raises(AttributeError):
            _ = config.nonexistent


# ── Checkpoint ──────────────────────────────────────────────────


class TestCheckpoint:
    def test_save_and_load(self):
        pool = AgentPool(n_agents=3)
        for i, a in enumerate(pool.agents):
            a.fitness = float(i + 1)
            a.fitness_history = [float(i)]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.pt")
            save_checkpoint(pool, generation=5, sigma=0.03, path=path)
            assert os.path.exists(path)

            # Load into fresh pool
            new_pool = AgentPool(n_agents=3)
            meta = load_checkpoint(path, new_pool)
            assert meta["generation"] == 5
            assert meta["sigma"] == 0.03

            # Check agent params restored
            for i in range(3):
                orig_vec = pool.agents[i].get_param_vector()
                loaded_vec = new_pool.agents[i].get_param_vector()
                assert torch.allclose(orig_vec, loaded_vec)
                assert new_pool.agents[i].fitness == float(i + 1)


# ── Logger ──────────────────────────────────────────────────────


class TestLogger:
    def test_log_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.jsonl")
            logger = TrainingLogger(log_path=log_path)

            stats = GenerationStats(
                generation=1,
                best_fitness=1.5,
                mean_fitness=0.8,
                fitness_std=0.3,
                sigma=0.02,
                best_agent_id="a1",
            )
            logger.log_generation(stats)

            assert len(logger.entries) == 1
            assert logger.latest()["generation"] == 1
            assert logger.latest()["best_fitness"] == 1.5
            assert os.path.exists(log_path)

    def test_in_memory_only(self):
        logger = TrainingLogger(log_path=None)
        stats = GenerationStats(
            generation=1, best_fitness=1.0, mean_fitness=0.5,
            fitness_std=0.2, sigma=0.02, best_agent_id="a1",
        )
        logger.log_generation(stats)
        assert len(logger.get_history()) == 1


# ── Trainer ─────────────────────────────────────────────────────


class TestTrainer:
    def _make_small_config(self) -> Config:
        return Config(_data={
            "population": {
                "n_agents": 4,
                "episodes_per_agent": 1,
                "n_generations": 3,
                "elite_fraction": 0.25,
                "survivor_fraction": 0.50,
            },
            "mutation": {
                "sigma_init": 0.02,
                "sigma_min": 0.001,
                "sigma_max": 0.10,
                "diversity_threshold": 0.5,
                "crossover_prob": 0.30,
            },
            "ppo": {"learning_rate": 3e-4},
            "dqn": {},
            "environment": {
                "episode_length": 20,
                "max_position": 0.05,
                "max_gross_exposure": 1.50,
                "stop_loss": 0.03,
                "tx_cost_bps": 5,
                "obs_dim": 57,
                "n_actions": 5,
                "catastrophic_nav": 0.50,
            },
            "reward": {
                "drawdown_penalty_coeff": 2.0,
                "drawdown_threshold": 0.10,
                "consistency_bonus": 0.20,
                "consistency_threshold": 0.55,
                "turnover_penalty_coeff": 0.10,
                "relative_reference_strategy": "ridge_excess_top5",
            },
            "bandit": {
                "n_regimes": 2,
                "bandit_prior_alpha": 1.0,
                "bandit_prior_beta": 1.0,
            },
            "network": {
                "hidden_sizes": [32, 16],
                "activation": "relu",
                "use_attention": False,
            },
            "alpha_engine": {
                "base_seed": 42,
            },
            "evolution": {
                "maml_enabled": False,
                "nsga2_enabled": False,
            },
            "curriculum": {
                "enabled": False,
            },
            "seeds": {
                "train_min": 0,
                "train_max": 899999,
                "val_min": 900000,
                "val_max": 999999,
                "n_val_seeds": 5,
            },
            "validation": {
                "validate_every_n_gens": 2,
                "early_stop_patience": 10,
                "n_val_episodes": 5,
                "use_stochastic_policy": False,
                "monitor": "stable",
                "selection_window": 2,
                "selection_stability_penalty": 0.25,
                "use_fixed_windows": False,
                "n_val_windows": 2,
                "shortlist_size": 2,
                "selection_min_activity_ratio": 0.05,
                "selection_min_avg_turnover": 0.01,
                "selection_baselines": ["equal_weight", "momentum_top5"],
                "baseline_margin": 0.0,
                "selection_metric_weights": {
                    "mean_sharpe": 0.6,
                    "sharpe_std": -0.2,
                    "max_drawdown": -0.1,
                    "avg_turnover": -0.1,
                },
            },
        })

    def test_trainer_runs(self):
        config = self._make_small_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer = Trainer(
                config=config,
                checkpoint_dir=os.path.join(tmpdir, "ckpt"),
                log_path=os.path.join(tmpdir, "log.jsonl"),
            )
            history = trainer.train(n_generations=2)
            assert len(history) == 2
            assert history[-1].generation == 2

    def test_trainer_runs_without_validation_section(self):
        config = self._make_small_config()
        config._data.pop("validation", None)
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer = Trainer(
                config=config,
                checkpoint_dir=os.path.join(tmpdir, "ckpt"),
            )
            history = trainer.train(n_generations=1)
            assert len(history) == 1

    def test_trainer_status(self):
        config = self._make_small_config()
        trainer = Trainer(config=config)
        status = trainer.get_status()
        assert status["generation"] == 0
        assert status["running"] is False

    def test_trainer_respects_simplified_config(self):
        config = self._make_small_config()
        trainer = Trainer(config=config)
        assert trainer.pool.agents[0].ac_network.use_attention is False
        assert trainer.evo_engine.maml_enabled is False
        assert trainer.evo_engine.nsga2_enabled is False
        assert trainer.curriculum.enabled is False
        assert trainer.env.relative_reference_strategy == "ridge_excess_top5"

    def test_trainer_stop(self):
        config = self._make_small_config()
        trainer = Trainer(config=config)
        trainer.stop()
        assert not trainer._running

    def test_trainer_checkpoint_and_resume(self):
        config = self._make_small_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer = Trainer(
                config=config,
                checkpoint_dir=os.path.join(tmpdir, "ckpt"),
            )
            history = trainer.train(n_generations=2)
            best_before = trainer.pool.max_fitness()

            # Save explicitly
            ckpt_path = os.path.join(tmpdir, "manual.pt")
            save_checkpoint(
                trainer.pool, trainer.generation, trainer.evo_engine.sigma, ckpt_path
            )

            # Resume in new trainer
            trainer2 = Trainer(
                config=config,
                checkpoint_dir=os.path.join(tmpdir, "ckpt2"),
            )
            trainer2.resume(ckpt_path)
            assert trainer2.generation == 2

    def test_trainer_writes_best_stable_checkpoint(self):
        config = self._make_small_config()
        config._data["validation"]["validate_every_n_gens"] = 1
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_dir = os.path.join(tmpdir, "ckpt")
            trainer = Trainer(config=config, checkpoint_dir=ckpt_dir)
            trainer.train(n_generations=2)
            assert os.path.exists(os.path.join(ckpt_dir, "checkpoint_best_stable.pt"))
            assert np.isfinite(trainer.best_stable_score)

    def test_selection_score_filters_inactive_and_penalizes_baseline_gap(self):
        trainer = Trainer(config=self._make_small_config())
        active_metrics = {
            "sharpe": 1.5,
            "sharpe_std": 0.2,
            "max_drawdown": 0.05,
            "avg_turnover": 0.12,
            "activity_ratio": 0.30,
            "baseline_excess_sharpe": 0.25,
            "passes_activity_filter": 1.0,
        }
        inactive_metrics = dict(active_metrics, passes_activity_filter=0.0)
        lagging_metrics = dict(active_metrics, baseline_excess_sharpe=-0.50)

        active_score = trainer._selection_score_from_metrics(active_metrics)
        inactive_score = trainer._selection_score_from_metrics(inactive_metrics)
        lagging_score = trainer._selection_score_from_metrics(lagging_metrics)

        assert np.isfinite(active_score)
        assert inactive_score == -float("inf")
        assert lagging_score < active_score

    def test_checkpoint_shortlist_keeps_top_scores(self, monkeypatch):
        trainer = Trainer(config=self._make_small_config())
        trainer.validation_shortlist_size = 2

        monkeypatch.setattr(
            trainer,
            "_save_checkpoint",
            lambda stats, tag=None, extra_updates=None: os.path.join(
                "/tmp", f"{tag or stats.generation}.pt"
            ),
        )

        stats1 = GenerationStats(1, 1.0, 0.5, 0.1, 0.02, "a1")
        stats2 = GenerationStats(2, 1.0, 0.5, 0.1, 0.02, "a2")
        stats3 = GenerationStats(3, 1.0, 0.5, 0.1, 0.02, "a3")

        trainer._update_checkpoint_shortlist(stats1, {"sharpe": 1.0}, 1.0)
        trainer._update_checkpoint_shortlist(stats2, {"sharpe": 2.0}, 2.0)
        trainer._update_checkpoint_shortlist(stats3, {"sharpe": 0.5}, 0.5)

        assert len(trainer.checkpoint_shortlist) == 2
        assert [item["generation"] for item in trainer.checkpoint_shortlist] == [2, 1]
        assert math.isclose(trainer.checkpoint_shortlist[0]["selection_score"], 2.0)


class TestBaselines:
    def _make_trending_dataset(self):
        def build_series(ticker: str, daily_ret: float):
            prices = [100.0]
            returns = [0.0]
            volumes = [1_000_000.0]
            for day in range(1, 90):
                prices.append(prices[-1] * (1.0 + daily_ret))
                returns.append(daily_ret)
                volumes.append(1_000_000.0 + day * 1000.0)
            return SimpleNamespace(
                ticker=ticker,
                prices=np.asarray(prices, dtype=np.float64),
                returns=np.asarray(returns, dtype=np.float64),
                volumes=np.asarray(volumes, dtype=np.float64),
            )

        return {
            "UP": build_series("UP", 0.01),
            "MID": build_series("MID", 0.002),
            "DOWN": build_series("DOWN", -0.008),
        }

    def test_compute_performance_metrics(self):
        daily_returns = [0.01, -0.002, 0.004, 0.003]
        nav_history = [100.0, 101.0, 100.798, 101.201192, 101.504795576]
        turnover = [1.0, 0.3, 0.2, 0.1]

        metrics = compute_performance_metrics(daily_returns, nav_history, turnover)

        assert metrics["annual_return"] != 0.0
        assert np.isfinite(metrics["sharpe"])
        assert metrics["max_drawdown"] >= 0.0
        assert 0.0 <= metrics["hit_rate"] <= 1.0

    def test_evaluate_baselines_returns_all_strategies(self):
        dataset = generate_dataset("Technology", 40, seed=42)

        results = evaluate_baselines([dataset], tx_cost_bps=5)

        assert set(results) == {
            "equal_weight",
            "momentum_top5",
            "mean_reversion_top5",
            "ridge_excess_top5",
            "random_top5",
        }
        for metrics in results.values():
            assert np.isfinite(metrics["sharpe"])
            assert np.isfinite(metrics["annual_return"])

    def test_supervised_baseline_finds_obvious_relative_strength(self):
        dataset = self._make_trending_dataset()

        metrics = simulate_supervised_baseline(dataset, top_n=1, tx_cost_bps=5)

        assert metrics["annual_return"] > 0.0
        assert metrics["sharpe"] > 0.0
        assert metrics["activity_ratio"] > 0.0


class TestBenchmarkUtilities:
    def test_classify_window_regimes_returns_one_label_per_window(self):
        windows = [
            generate_dataset("Technology", 40, seed=42),
            generate_dataset("Technology", 40, seed=43),
            generate_dataset("Technology", 40, seed=44),
        ]
        labels = classify_window_regimes(windows)
        assert len(labels) == len(windows)
        assert all(label in {"bull_low_vol", "bull_high_vol", "bear_low_vol", "bear_high_vol"} for label in labels)

    def test_benchmark_report_markdown_contains_sections(self):
        report = BenchmarkReport(
            cache_date="2026-03-29",
            checkpoint_metrics={"marl": {"sharpe": 1.2, "annual_return": 0.10, "max_drawdown": 0.05, "avg_turnover": 0.2, "hit_rate": 0.6}},
            baseline_metrics={"equal_weight": {"sharpe": 0.8, "annual_return": 0.08, "max_drawdown": 0.06, "avg_turnover": 0.1, "hit_rate": 0.55}},
            checkpoint_cost_grid={"marl": {"5": {"sharpe": 1.2, "annual_return": 0.10, "max_drawdown": 0.05}}},
            checkpoint_regimes={"marl": {"bull_low_vol": {"sharpe": 1.0, "annual_return": 0.09, "max_drawdown": 0.04, "hit_rate": 0.6}}},
        )
        md = report.to_markdown()
        assert "MARL Benchmark Report" in md
        assert "Cost Sensitivity" in md
        assert "Regime Breakdown" in md
