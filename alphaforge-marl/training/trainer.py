"""Training orchestrator: ties together evolution, bandit, checkpointing, and logging."""

from __future__ import annotations

import logging
import math
import os
import random
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import torch

from agents.agent_pool import AgentPool
from agents.base_agent import AgentType
from env.trading_env import TradingEnv
from env.episode_runner import run_episode
from evolution.evolutionary_engine import EvolutionaryEngine, GenerationStats
from bandit.regime_detector import RegimeDetector, extract_regime_features
from bandit.thompson_sampler import ThompsonSampler
from bandit.capital_allocator import CapitalAllocator
from agents.ensemble import EnsemblePolicy, ParetoFront
from training.baselines import compute_performance_metrics, evaluate_baselines
from training.config import Config, load_config
from training.checkpoint import save_checkpoint, load_checkpoint
from training.curriculum import CurriculumScheduler
from training.distributed import DistributedEvaluator
from training.logger import TrainingLogger

logger = logging.getLogger(__name__)


class Trainer:
    """Full MARL training orchestrator.

    Coordinates:
    - Agent population (AgentPool)
    - Evolutionary engine (evo + PPO fine-tuning)
    - Regime bandit (regime detection + Thompson sampling)
    - Validation-based early stopping
    - Checkpointing and logging
    """

    def __init__(
        self,
        config: Config | None = None,
        checkpoint_dir: str = "checkpoints",
        log_path: str | None = None,
        on_generation: Callable[[GenerationStats], None] | None = None,
    ):
        self.config = config or load_config()
        self.checkpoint_dir = checkpoint_dir
        self.on_generation = on_generation

        # Build environment
        env_cfg = self.config.environment
        reward_cfg = self.config.reward
        data_cfg = self.config.get("data", {})
        if isinstance(data_cfg, Config):
            data_cfg = data_cfg.to_dict()
        val_cfg = self.config.get("validation", {})
        if isinstance(val_cfg, Config):
            val_cfg = val_cfg.to_dict()
        evo_cfg = self.config.get("evolution", {})
        if isinstance(evo_cfg, Config):
            evo_cfg = evo_cfg.to_dict()
        curriculum_cfg = self.config.get("curriculum", {})
        if isinstance(curriculum_cfg, Config):
            curriculum_cfg = curriculum_cfg.to_dict()
        self.env = TradingEnv(
            sector=data_cfg.get("sector", "Technology"),
            lookback=data_cfg.get("lookback_days", 252),
            episode_length=env_cfg.get("episode_length", 252),
            max_position=env_cfg.get("max_position", 0.05),
            max_gross_exposure=env_cfg.get("max_gross_exposure", 1.50),
            stop_loss=env_cfg.get("stop_loss", 0.03),
            tx_cost_bps=env_cfg.get("tx_cost_bps", 5),
            catastrophic_nav=env_cfg.get("catastrophic_nav", 0.50),
            data_mode=data_cfg.get("mode", "synthetic"),
            real_data_cache_dir=data_cfg.get("cache_dir", None),
            real_data_dir=data_cfg.get("market_dir", None),
            real_data_start_date=data_cfg.get("start_date", None),
            real_data_end_date=data_cfg.get("end_date", None),
            hybrid_real_prob=data_cfg.get("hybrid_real_prob", 0.5),
            strict_real_data=data_cfg.get("strict_real_data", False),
            drawdown_penalty_coeff=reward_cfg.get("drawdown_penalty_coeff", 2.0),
            drawdown_threshold=reward_cfg.get("drawdown_threshold", 0.10),
            consistency_bonus=reward_cfg.get("consistency_bonus", 0.20),
            consistency_threshold=reward_cfg.get("consistency_threshold", 0.55),
            turnover_penalty_coeff=reward_cfg.get("turnover_penalty_coeff", 0.10),
            benchmark_relative_mix=reward_cfg.get("benchmark_relative_mix", 0.5),
            relative_reference_strategy=reward_cfg.get("relative_reference_strategy", "equal_weight"),
            sharpe_delta_scale=reward_cfg.get("sharpe_delta_scale", 0.5),
            drawdown_step_penalty=reward_cfg.get("drawdown_step_penalty", 0.5),
            participation_bonus=reward_cfg.get("participation_bonus", 0.005),
            inactivity_penalty=reward_cfg.get("inactivity_penalty", 0.10),
            normalize_observations=env_cfg.get("normalize_observations", True),
            observation_norm_window=env_cfg.get("observation_norm_window", 63),
            baseline_sharpe_reference=reward_cfg.get("baseline_sharpe_reference", 0.8),
            episode_reward_scale=reward_cfg.get("episode_reward_scale", None),
        )

        # Seed ranges
        seeds_cfg = self.config.get("seeds", {})
        if isinstance(seeds_cfg, Config):
            seeds_cfg = seeds_cfg.to_dict()
        self.seed_range_train = (
            seeds_cfg.get("train_min", 0),
            seeds_cfg.get("train_max", 899_999),
        )
        self.seed_range_val = (
            seeds_cfg.get("val_min", 900_000),
            seeds_cfg.get("val_max", 999_999),
        )
        n_val = seeds_cfg.get("n_val_seeds", 20)
        # Fixed validation seeds (drawn once, never change)
        random.seed(12345)
        self.val_seeds = [
            random.randint(self.seed_range_val[0], self.seed_range_val[1])
            for _ in range(n_val)
        ]
        random.seed()  # Re-randomize

        # Validation config
        self.validate_every = val_cfg.get("validate_every_n_gens", 5)
        self.early_stop_patience = val_cfg.get("early_stop_patience", 10)
        self.validation_n_episodes = int(val_cfg.get("n_val_episodes", len(self.val_seeds)))
        self.validation_use_stochastic_policy = val_cfg.get("use_stochastic_policy", False)
        self.validation_monitor = val_cfg.get("monitor", "stable")
        self.validation_selection_window = max(1, int(val_cfg.get("selection_window", 3)))
        self.validation_stability_penalty = float(
            val_cfg.get("selection_stability_penalty", 0.25)
        )
        selection_weights = val_cfg.get("selection_metric_weights", {})
        if isinstance(selection_weights, Config):
            selection_weights = selection_weights.to_dict()
        self.validation_use_fixed_windows = bool(val_cfg.get("use_fixed_windows", True))
        self.validation_n_windows = max(1, int(val_cfg.get("n_val_windows", 5)))
        self.validation_shortlist_size = max(1, int(val_cfg.get("shortlist_size", 3)))
        self.validation_start_date = val_cfg.get("start_date", "2020-01-01")
        self.validation_end_date = val_cfg.get("end_date", "2021-12-31")
        self.validation_min_activity_ratio = float(
            val_cfg.get("selection_min_activity_ratio", 0.05)
        )
        self.validation_min_avg_turnover = float(
            val_cfg.get("selection_min_avg_turnover", 0.01)
        )
        self.validation_baseline_names = list(
            val_cfg.get("selection_baselines", ["equal_weight", "momentum_top5"])
        )
        self.validation_baseline_margin = float(val_cfg.get("baseline_margin", 0.0))
        self.validation_metric_weights = {
            "mean_sharpe": float(selection_weights.get("mean_sharpe", 0.6)),
            "sharpe_std": float(selection_weights.get("sharpe_std", -0.2)),
            "max_drawdown": float(selection_weights.get("max_drawdown", -0.1)),
            "avg_turnover": float(selection_weights.get("avg_turnover", -0.1)),
        }

        # Build agent pool
        pop_cfg = self.config.population
        net_cfg = self.config.network
        ppo_cfg = self.config.get("ppo", {})
        if isinstance(ppo_cfg, Config):
            ppo_cfg = ppo_cfg.to_dict()
        ppo_kwargs = {
            "lr": ppo_cfg.get("learning_rate", 1e-3),
            "clip_epsilon": ppo_cfg.get("clip_epsilon", 0.20),
            "gamma": ppo_cfg.get("gamma", 0.99),
            "gae_lambda": ppo_cfg.get("gae_lambda", 0.95),
            "ppo_epochs": ppo_cfg.get("ppo_epochs", 4),
            "minibatch_size": ppo_cfg.get("minibatch_size", 32),
            "entropy_coeff": ppo_cfg.get("entropy_coeff", 0.01),
            "value_loss_coeff": ppo_cfg.get("value_loss_coeff", 0.5),
        }
        self.pool = AgentPool(
            n_agents=pop_cfg.get("n_agents", 30),
            agent_type=AgentType.ACTOR_CRITIC,
            obs_dim=env_cfg.get("obs_dim", 57),
            n_actions=env_cfg.get("n_actions", 5),
            hidden_sizes=net_cfg.get("hidden_sizes", [256, 128, 64]),
            activation=net_cfg.get("activation", "relu"),
            use_attention=net_cfg.get("use_attention", True),
            elite_fraction=pop_cfg.get("elite_fraction", 0.10),
            survivor_fraction=pop_cfg.get("survivor_fraction", 0.50),
            ppo_kwargs=ppo_kwargs,
        )

        # Build evolutionary engine
        mut_cfg = self.config.mutation
        self.evo_engine = EvolutionaryEngine(
            pool=self.pool,
            env=self.env,
            sigma_init=mut_cfg.get("sigma_init", 0.02),
            sigma_min=mut_cfg.get("sigma_min", 0.001),
            sigma_max=mut_cfg.get("sigma_max", 0.10),
            crossover_prob=mut_cfg.get("crossover_prob", 0.30),
            diversity_threshold=mut_cfg.get("diversity_threshold", 0.5),
            episodes_per_agent=pop_cfg.get("episodes_per_agent", 10),
            seed_range=self.seed_range_train,
            ppo_enabled=True,
            maml_enabled=evo_cfg.get("maml_enabled", True),
            maml_every_n_gens=evo_cfg.get("maml_every_n_gens", 5),
            nsga2_enabled=evo_cfg.get("nsga2_enabled", True),
        )

        # Build regime bandit
        bandit_cfg = self.config.bandit
        self.regime_detector = RegimeDetector(
            n_regimes=bandit_cfg.get("n_regimes", 4),
        )
        self.sampler = ThompsonSampler(
            n_regimes=bandit_cfg.get("n_regimes", 4),
            prior_alpha=bandit_cfg.get("bandit_prior_alpha", 1.0),
            prior_beta=bandit_cfg.get("bandit_prior_beta", 1.0),
        )
        self.allocator = CapitalAllocator(self.regime_detector, self.sampler)
        self.regime_fitness_blend = bandit_cfg.get("regime_fitness_blend", 0.2)

        # Register agents with bandit
        for agent in self.pool.agents:
            self.sampler.register_agent(agent.agent_id)

        # Logger
        self.logger = TrainingLogger(log_path=log_path)

        # Distributed evaluation
        dist_cfg = self.config.get("distributed", {})
        if isinstance(dist_cfg, Config):
            dist_cfg = dist_cfg.to_dict()
        self._distributed_enabled = dist_cfg.get("enabled", False)
        self._n_workers = dist_cfg.get("n_workers", None)
        self._distributed_evaluator: Optional[DistributedEvaluator] = None

        # Curriculum learning
        self.curriculum = CurriculumScheduler(
            enabled=curriculum_cfg.get("enabled", True)
        )

        # Ensemble (Pareto front + blended policy)
        self.pareto_front = ParetoFront(max_size=8)
        self.ensemble = EnsemblePolicy([], self.allocator)

        # State
        self.generation = 0
        self._running = False
        self.best_val_sharpe = -float("inf")
        self.best_val_generation = 0
        self.best_stable_score = -float("inf")
        self.best_stable_generation = 0
        self.best_monitor_score = -float("inf")
        self.best_monitor_generation = 0
        self._validation_history: List[float] = []
        self._selection_score_history: List[float] = []
        self._validation_windows = self._build_validation_windows()
        self._validation_baselines = self._build_validation_baselines()
        self._last_validation_metrics: Dict[str, float] = {}
        self._last_selection_score = -float("inf")
        self.checkpoint_shortlist: List[Dict[str, Any]] = []
        self._patience_counter = 0

    def train(self, n_generations: int | None = None) -> List[GenerationStats]:
        """Run the full training loop with validation-based early stopping."""
        if n_generations is None:
            n_generations = self.config.population.get("n_generations", 50)

        self._running = True
        history: List[GenerationStats] = []

        # Start distributed evaluator if enabled
        if self._distributed_enabled:
            env_kwargs = {
                "sector": self.env.sector,
                "lookback": self.env.lookback,
                "episode_length": self.env.episode_length,
                "max_position": self.env.max_position,
                "max_gross_exposure": self.env.max_gross_exposure,
                "stop_loss": self.env.stop_loss,
                "tx_cost_bps": int(self.env.tx_cost * 10000),
                "catastrophic_nav": self.env.catastrophic_nav,
                "data_mode": self.env.data_mode,
                "real_data_cache_dir": self.env.real_data_cache_dir,
                "real_data_end_date": self.env.real_data_end_date,
                "hybrid_real_prob": self.env.hybrid_real_prob,
                "strict_real_data": self.env.strict_real_data,
                "normalize_observations": self.env.normalize_observations,
                "observation_norm_window": self.env.observation_norm_window,
                "benchmark_relative_mix": self.env._reward_kwargs.get("benchmark_relative_mix", 0.5),
                "relative_reference_strategy": self.env.relative_reference_strategy,
                "sharpe_delta_scale": self.env.sharpe_delta_scale,
                "drawdown_step_penalty": self.env.drawdown_step_penalty,
                "participation_bonus": self.env.participation_bonus,
                "inactivity_penalty": self.env.inactivity_penalty,
                "episode_reward_scale": self.env.episode_reward_scale,
            }
            self._distributed_evaluator = DistributedEvaluator(
                n_workers=self._n_workers,
                env_kwargs=env_kwargs,
            )
            self._distributed_evaluator.start()
            self.evo_engine.distributed_evaluator = self._distributed_evaluator
            logger.info(
                f"Distributed evaluation enabled with {self._distributed_evaluator.n_workers} workers"
            )

        for g in range(n_generations):
            if not self._running:
                logger.info("Training stopped early")
                break

            stats = self.evo_engine.run_generation()
            self.generation = stats.generation

            # Fit regime detector on market data from env (first gen only)
            if stats.generation == 1 and hasattr(self.env, '_index_returns'):
                self._fit_regime_detector()

            # Detect current regime and update bandit posteriors
            current_regime = self._detect_current_regime()
            for agent in self.pool.agents:
                self.sampler.register_agent(agent.agent_id)
                self.sampler.update(current_regime, agent.agent_id, agent.fitness)

            # Apply regime-weighted fitness bonus: agents that perform well
            # in the current regime get a fitness boost, encouraging
            # specialization
            if self.regime_fitness_blend > 0:
                raw_blend = max(0.0, min(1.0, float(self.regime_fitness_blend)))
                base_blend = 1.0 - raw_blend
                for agent in self.pool.agents:
                    regime_score = self.sampler.expected_value(
                        current_regime, agent.agent_id
                    )
                    agent.fitness = base_blend * agent.fitness + raw_blend * (
                        agent.fitness * (0.5 + regime_score)
                    )

            # Curriculum: check for stage promotion and apply env overrides
            promoted = self.curriculum.step(stats.best_fitness)
            if promoted:
                overrides = self.curriculum.get_env_overrides()
                self.env.tx_cost = overrides["tx_cost_bps"] / 10000.0
                self.env.max_gross_exposure = overrides["max_gross_exposure"]
                self.env.stop_loss = overrides["stop_loss"]
                self.env.episode_length = overrides["episode_length"]
                logger.info(
                    f"Curriculum promoted to stage '{self.curriculum.current_stage.name}' "
                    f"at gen {stats.generation}"
                )

            # Update Pareto front and ensemble
            self._update_ensemble()

            # Validation evaluation
            if stats.generation % self.validate_every == 0:
                validation_metrics = self._evaluate_validation(return_metrics=True)
                val_sharpe = float(validation_metrics.get("sharpe", 0.0))
                selection_score = self._selection_score_from_metrics(validation_metrics)
                stats.val_sharpe = val_sharpe
                self._last_validation_metrics = dict(validation_metrics)
                self._last_selection_score = selection_score
                self._validation_history.append(val_sharpe)
                self._selection_score_history.append(selection_score)
                stable_score = self._validation_selection_score()

                if val_sharpe > self.best_val_sharpe:
                    self.best_val_sharpe = val_sharpe
                    self.best_val_generation = stats.generation
                    self._save_checkpoint(stats, tag="best_val")
                    logger.info(
                        f"New best val Sharpe: {val_sharpe:.4f} at gen {stats.generation}"
                    )

                if stable_score > self.best_stable_score:
                    self.best_stable_score = stable_score
                    self.best_stable_generation = stats.generation
                    self._save_checkpoint(stats, tag="best_stable")
                    logger.info(
                        f"New best stable val score: {stable_score:.4f} at gen {stats.generation}"
                    )

                self._update_checkpoint_shortlist(stats, validation_metrics, selection_score)

                monitor_score = (
                    stable_score
                    if self.validation_monitor == "stable"
                    else val_sharpe
                )
                if monitor_score > self.best_monitor_score:
                    self.best_monitor_score = monitor_score
                    self.best_monitor_generation = stats.generation
                    self._patience_counter = 0
                else:
                    self._patience_counter += 1
                    if self._patience_counter >= self.early_stop_patience:
                        logger.info(
                            f"Early stopping at gen {stats.generation} "
                            f"(no {self.validation_monitor} improvement for {self._patience_counter} checks, "
                            f"best score={self.best_monitor_score:.4f} at gen {self.best_monitor_generation})"
                        )
                        self._running = False

            self.logger.log_generation(stats, extra={
                "val_sharpe": stats.val_sharpe,
                "validation_selection_score": self._last_selection_score,
                "validation_activity_ratio": self._last_validation_metrics.get("activity_ratio", 0.0),
                "validation_baseline_excess_sharpe": self._last_validation_metrics.get("baseline_excess_sharpe", 0.0),
                "best_val_sharpe": self.best_val_sharpe,
                "best_val_generation": self.best_val_generation,
                "best_stable_score": self.best_stable_score,
                "best_stable_generation": self.best_stable_generation,
                "ppo_policy_loss": stats.ppo_policy_loss,
                "ppo_value_loss": stats.ppo_value_loss,
            })

            # Checkpoint every 10 generations
            if stats.generation % 10 == 0:
                self._save_checkpoint(stats)

            # Callback
            if self.on_generation:
                self.on_generation(stats)

            history.append(stats)

            logger.info(
                f"Gen {stats.generation}/{n_generations}: "
                f"best={stats.best_fitness:.4f} mean={stats.mean_fitness:.4f} "
                f"val={stats.val_sharpe:.4f} ppo_ploss={stats.ppo_policy_loss:.6f}"
            )

        # Final checkpoint
        if history:
            self._save_checkpoint(history[-1])

        # Shut down distributed evaluator
        if self._distributed_evaluator is not None:
            self._distributed_evaluator.stop()
            self._distributed_evaluator = None
            self.evo_engine.distributed_evaluator = None

        logger.info(
            f"Training done. Best val Sharpe: {self.best_val_sharpe:.4f} "
            f"at gen {self.best_val_generation}; "
            f"best stable score: {self.best_stable_score:.4f} at gen {self.best_stable_generation}"
        )

        self._running = False
        return history

    def _update_ensemble(self) -> None:
        """Update Pareto front from current population and refresh ensemble."""
        agents = self.pool.agents
        fitnesses = [a.fitness for a in agents]

        # Compute diversity score per agent (distance from mean param vector)
        mean_vec = torch.stack([a.get_param_vector() for a in agents]).mean(dim=0)
        diversity = [
            float(torch.norm(a.get_param_vector() - mean_vec))
            for a in agents
        ]

        objectives = {
            "fitness": fitnesses,
            "diversity": diversity,
        }
        pareto_agents = self.pareto_front.update(agents, objectives)
        self.ensemble.set_agents(pareto_agents)

    def _fit_regime_detector(self) -> None:
        """Fit the HMM regime detector on synthetic market data."""
        if not hasattr(self.env, '_index_returns') or len(self.env._index_returns) < 42:
            return
        features = extract_regime_features(
            self.env._index_returns,
            self.env._index_volumes,
            self.env._index_prices,
            window=21,
        )
        if len(features) > 0:
            self.regime_detector.fit(features)
            logger.info(
                f"Regime detector fitted on {len(features)} windows, "
                f"{self.regime_detector.n_regimes} regimes"
            )

    def _detect_current_regime(self) -> int:
        """Detect regime from the latest market window."""
        if not self.regime_detector.is_fitted:
            return 0
        if not hasattr(self.env, '_index_returns') or len(self.env._index_returns) < 22:
            return 0
        features = extract_regime_features(
            self.env._index_returns,
            self.env._index_volumes,
            self.env._index_prices,
            window=21,
        )
        if len(features) == 0:
            return 0
        return self.regime_detector.predict_single(features[-1])

    def _evaluate_validation(self, *, return_metrics: bool = False) -> float | Dict[str, float]:
        """Evaluate best agent on fixed windows/seeds.

        By default this preserves the older contract and returns the aggregate
        validation Sharpe as a float. Callers that need the richer summary can
        request the full metrics dictionary.
        """
        best = self.pool.best()
        episode_metrics: List[Dict[str, float]] = []

        def policy(state, _agent=best):
            return _agent.select_action(
                state,
                training=self.validation_use_stochastic_policy,
            )

        if self._validation_windows:
            original_windows = self.env._real_windows
            try:
                for idx, window in enumerate(self._validation_windows):
                    self.env._real_windows = [window]
                    result = run_episode(self.env, policy, seed=idx)
                    episode_metrics.append(self._summarize_validation_episode(result))
            finally:
                self.env._real_windows = original_windows
        else:
            n_eval = min(len(self.val_seeds), self.validation_n_episodes)
            for seed in self.val_seeds[:n_eval]:
                result = run_episode(self.env, policy, seed=seed)
                episode_metrics.append(self._summarize_validation_episode(result))

        aggregated = self._aggregate_validation_metrics(episode_metrics)
        if return_metrics:
            return aggregated
        return float(aggregated.get("sharpe", 0.0))

    def _validation_selection_score(self) -> float:
        """Stability-aware validation score used for checkpoint selection."""
        finite_scores = [score for score in self._selection_score_history if np.isfinite(score)]
        if not finite_scores:
            return -float("inf")
        recent = finite_scores[-self.validation_selection_window :]
        mean_score = float(np.mean(recent))
        if len(recent) < 2:
            return mean_score
        std_score = float(np.std(recent, ddof=1))
        return mean_score - self.validation_stability_penalty * std_score

    def _build_validation_windows(self) -> List[Dict[str, Any]]:
        """Create fixed validation windows from the canonical 2020-2021 period."""
        if not self.validation_use_fixed_windows:
            return []
        if self.env.data_mode not in {"real", "real_strict", "hybrid"}:
            return []

        try:
            from training.real_walk_forward import build_windows_for_period
        except Exception:
            return []

        try:
            windows = build_windows_for_period(
                sector=self.env.sector,
                period_start=date.fromisoformat(self.validation_start_date),
                period_end=date.fromisoformat(self.validation_end_date),
                lookback=self.env.lookback,
                market_dir=self.env.real_data_dir,
                n_windows=self.validation_n_windows,
            )
        except Exception as exc:
            logger.warning("Could not build fixed validation windows: %s", exc)
            return []
        return windows

    def _build_validation_baselines(self) -> Dict[str, Dict[str, float]]:
        """Precompute baseline metrics on the fixed validation windows."""
        if not self._validation_windows:
            return {}
        try:
            all_baselines = evaluate_baselines(
                self._validation_windows,
                tx_cost_bps=int(self.env.tx_cost * 10000),
            )
        except Exception as exc:
            logger.warning("Could not compute validation baselines: %s", exc)
            return {}
        return {
            name: metrics
            for name, metrics in all_baselines.items()
            if name in self.validation_baseline_names
        }

    def _summarize_validation_episode(self, result) -> Dict[str, float]:
        """Extract robust selection metrics from the most recent validation episode."""
        metrics = compute_performance_metrics(
            self.env._daily_returns,
            self.env._nav_history,
            self.env._daily_turnover,
        )
        actions = [transition.action for transition in result.trajectory]
        active_steps = sum(int(action != 0) for action in actions)
        metrics.update({
            "activity_ratio": active_steps / max(len(actions), 1),
            "active_steps": float(active_steps),
            "total_reward": float(result.total_reward),
            "final_nav": float(result.final_nav),
        })
        return metrics

    def _aggregate_validation_metrics(
        self,
        episode_metrics: List[Dict[str, float]],
    ) -> Dict[str, float]:
        """Aggregate per-window validation metrics into a robust summary."""
        if not episode_metrics:
            return {
                "sharpe": 0.0,
                "sharpe_std": 0.0,
                "max_drawdown": 0.0,
                "avg_turnover": 0.0,
                "activity_ratio": 0.0,
                "baseline_reference_sharpe": 0.0,
                "baseline_excess_sharpe": 0.0,
                "passes_activity_filter": 0.0,
                "n_windows": 0.0,
            }

        keys = sorted({key for item in episode_metrics for key in item})
        aggregated: Dict[str, float] = {}
        for key in keys:
            raw = [item[key] for item in episode_metrics if key in item]
            if not raw:
                aggregated[key] = 0.0
                continue
            if any(isinstance(v, list) for v in raw):
                combined: list = []
                for v in raw:
                    if isinstance(v, list):
                        combined.extend(v)
                aggregated[key] = combined  # list passes through; consumers guard
            else:
                aggregated[key] = float(np.mean([float(v) for v in raw]))

        sharpe_values = [float(item.get("sharpe", 0.0)) for item in episode_metrics]
        aggregated["sharpe_std"] = (
            float(np.std(sharpe_values, ddof=1))
            if len(sharpe_values) > 1
            else 0.0
        )
        aggregated["activity_ratio_min"] = min(
            float(item.get("activity_ratio", 0.0)) for item in episode_metrics
        )
        aggregated["n_windows"] = float(len(episode_metrics))

        baseline_reference = 0.0
        if self._validation_baselines:
            baseline_reference = max(
                float(metrics.get("sharpe", 0.0))
                for metrics in self._validation_baselines.values()
            )
        aggregated["baseline_reference_sharpe"] = baseline_reference
        aggregated["baseline_excess_sharpe"] = float(
            aggregated.get("sharpe", 0.0) - baseline_reference
        )
        passes_activity = (
            aggregated.get("activity_ratio", 0.0) >= self.validation_min_activity_ratio
            and aggregated.get("avg_turnover", 0.0) >= self.validation_min_avg_turnover
        )
        aggregated["passes_activity_filter"] = 1.0 if passes_activity else 0.0
        return aggregated

    def _selection_score_from_metrics(self, metrics: Dict[str, float]) -> float:
        """Composite checkpoint score for model selection."""
        if not metrics or not bool(metrics.get("passes_activity_filter", 0.0)):
            return -float("inf")

        score = (
            self.validation_metric_weights["mean_sharpe"] * float(metrics.get("sharpe", 0.0))
            + self.validation_metric_weights["sharpe_std"] * float(metrics.get("sharpe_std", 0.0))
            + self.validation_metric_weights["max_drawdown"] * float(metrics.get("max_drawdown", 0.0))
            + self.validation_metric_weights["avg_turnover"] * float(metrics.get("avg_turnover", 0.0))
        )

        baseline_gap = float(metrics.get("baseline_excess_sharpe", 0.0)) - self.validation_baseline_margin
        if baseline_gap < 0.0:
            score += baseline_gap
        return score

    def _update_checkpoint_shortlist(
        self,
        stats: GenerationStats,
        metrics: Dict[str, float],
        selection_score: float,
    ) -> None:
        """Maintain a top-k shortlist of robust checkpoints."""
        if not np.isfinite(selection_score):
            return

        candidate = {
            "generation": stats.generation,
            "val_sharpe": float(metrics.get("sharpe", 0.0)),
            "selection_score": float(selection_score),
            "activity_ratio": float(metrics.get("activity_ratio", 0.0)),
            "baseline_excess_sharpe": float(metrics.get("baseline_excess_sharpe", 0.0)),
        }
        current = [item for item in self.checkpoint_shortlist if item["generation"] != stats.generation]
        current.append(candidate)
        current.sort(
            key=lambda item: (item["selection_score"], item["val_sharpe"]),
            reverse=True,
        )
        shortlisted = current[: self.validation_shortlist_size]
        if not any(item["generation"] == stats.generation for item in shortlisted):
            self.checkpoint_shortlist = shortlisted
            return

        path = self._save_checkpoint(
            stats,
            tag=f"shortlist_gen{stats.generation:04d}",
            extra_updates={
                "validation_selection_score": selection_score,
                "validation_metrics": metrics,
            },
        )
        for item in shortlisted:
            if item["generation"] == stats.generation:
                item["checkpoint_path"] = path
        self.checkpoint_shortlist = shortlisted

    def stop(self) -> None:
        """Signal the training loop to stop."""
        self._running = False

    def _save_checkpoint(
        self,
        stats: GenerationStats,
        tag: str | None = None,
        extra_updates: Dict[str, Any] | None = None,
    ) -> str:
        if tag:
            fname = f"checkpoint_{tag}.pt"
        else:
            fname = f"checkpoint_gen{stats.generation:04d}.pt"
        path = os.path.join(self.checkpoint_dir, fname)
        extra = {
            "best_fitness": stats.best_fitness,
            "mean_fitness": stats.mean_fitness,
            "val_sharpe": stats.val_sharpe,
            "best_val_sharpe": self.best_val_sharpe,
            "best_val_generation": self.best_val_generation,
            "best_stable_score": self.best_stable_score,
            "best_stable_generation": self.best_stable_generation,
            "best_monitor_score": self.best_monitor_score,
            "best_monitor_generation": self.best_monitor_generation,
            "validation_selection_score": self._last_selection_score,
            "validation_metrics": self._last_validation_metrics,
            "checkpoint_shortlist": self.checkpoint_shortlist,
        }
        if extra_updates:
            extra.update(extra_updates)
        save_checkpoint(
            self.pool,
            stats.generation,
            self.evo_engine.sigma,
            path,
            extra=extra,
        )
        return path

    def resume(self, checkpoint_path: str) -> None:
        """Resume training from a checkpoint."""
        meta = load_checkpoint(checkpoint_path, self.pool)
        self.generation = meta["generation"]
        self.evo_engine.generation = meta["generation"]
        self.evo_engine.sigma = meta["sigma"]
        extra = meta.get("extra", {})
        self.best_val_sharpe = extra.get("best_val_sharpe", -float("inf"))
        self.best_val_generation = extra.get("best_val_generation", 0)
        self.best_stable_score = extra.get("best_stable_score", -float("inf"))
        self.best_stable_generation = extra.get("best_stable_generation", 0)
        self.best_monitor_score = extra.get("best_monitor_score", -float("inf"))
        self.best_monitor_generation = extra.get("best_monitor_generation", 0)
        self._last_selection_score = extra.get("validation_selection_score", -float("inf"))
        self._last_validation_metrics = extra.get("validation_metrics", {})
        self.checkpoint_shortlist = extra.get("checkpoint_shortlist", [])
        logger.info(f"Resumed from generation {self.generation}")

    def get_status(self) -> Dict[str, Any]:
        """Get current training status."""
        return {
            "generation": self.generation,
            "running": self._running,
            "best_fitness": self.pool.max_fitness(),
            "mean_fitness": self.pool.mean_fitness(),
            "sigma": self.evo_engine.sigma,
            "n_agents": self.pool.n_agents,
            "best_agent_id": self.pool.best().agent_id if self.pool.agents else None,
            "best_val_sharpe": self.best_val_sharpe,
            "best_val_generation": self.best_val_generation,
            "best_stable_score": self.best_stable_score,
            "best_stable_generation": self.best_stable_generation,
            "last_selection_score": self._last_selection_score,
            "checkpoint_shortlist": self.checkpoint_shortlist,
        }
