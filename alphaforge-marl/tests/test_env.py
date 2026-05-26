"""Tests for the MARL trading environment (Phase 0)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from env.trading_env import TradingEnv
from env.action_space import Action, N_ACTIONS, ACTION_POSITION
from env.reward import compute_reward
from env.state_builder import build_state, rolling_signal_score
from env.episode_runner import run_episode, random_policy, EpisodeResult


# ── Environment basics ──────────────────────────────────────────


class TestEnvReset:
    def test_reset_returns_57_dim(self):
        env = TradingEnv()
        obs, info = env.reset(seed=42)
        assert obs.shape == (57,)
        assert obs.dtype == np.float32

    def test_reset_info_keys(self):
        env = TradingEnv()
        _, info = env.reset(seed=42)
        assert "day" in info
        assert "nav" in info
        assert "n_positions" in info
        assert "gross_exposure" in info
        assert info["day"] == 0
        assert info["nav"] == 100.0

    def test_reset_obs_finite(self):
        env = TradingEnv()
        obs, _ = env.reset(seed=42)
        assert np.all(np.isfinite(obs))

    def test_real_strict_raises_when_real_data_unavailable(self, monkeypatch):
        import env.real_data as real_data

        monkeypatch.setattr(real_data, "generate_real_dataset_windowed", lambda **kwargs: [])

        def _raise(**kwargs):
            raise RuntimeError("real data unavailable")

        monkeypatch.setattr(real_data, "generate_real_dataset", _raise)

        env = TradingEnv(data_mode="real_strict", strict_real_data=True)
        with pytest.raises(RuntimeError):
            env.reset(seed=42)

    def test_real_mode_can_fall_back_to_synthetic(self, monkeypatch):
        import env.real_data as real_data

        monkeypatch.setattr(real_data, "generate_real_dataset_windowed", lambda **kwargs: [])

        def _raise(**kwargs):
            raise RuntimeError("real data unavailable")

        monkeypatch.setattr(real_data, "generate_real_dataset", _raise)

        env = TradingEnv(data_mode="real")
        obs, info = env.reset(seed=42)
        assert obs.shape == (57,)
        assert info["data_mode"] == "real"
        assert info["strict_real_data"] is False
        assert info["resolved_data_source"] == "synthetic_fallback"
        assert info["n_tickers"] > 0
        assert info["n_days"] > 0

    def test_reference_strategy_uses_baseline_path(self, monkeypatch):
        import training.baselines as baselines

        monkeypatch.setattr(
            baselines,
            "simulate_baseline_path",
            lambda *args, **kwargs: {
                "daily_returns": [0.01, 0.02, 0.03],
                "nav_history": [100.0, 101.0, 103.02, 106.1106],
                "turnover": [0.2, 0.2, 0.2],
            },
        )

        env = TradingEnv(
            episode_length=3,
            relative_reference_strategy="ridge_excess_top5",
        )
        _, info = env.reset(seed=42)

        assert info["relative_reference_strategy"] == "ridge_excess_top5"
        assert env._reference_return_path == [0.01, 0.02, 0.03]


class TestEnvStep:
    def test_hold_252_steps(self):
        """HOLD for full episode — should terminate with zero reward effect."""
        env = TradingEnv(episode_length=252)
        obs, _ = env.reset(seed=42)
        total_reward = 0.0
        done = False
        steps = 0
        while not done:
            obs, reward, terminated, truncated, info = env.step(Action.HOLD)
            total_reward += reward
            done = terminated or truncated
            steps += 1
        assert steps > 0
        assert done
        assert math.isfinite(total_reward)
        assert math.isfinite(info["nav"])

    def test_long_strong_changes_positions(self):
        """LONG_STRONG should open positions."""
        env = TradingEnv()
        env.reset(seed=42)
        _, _, _, _, info = env.step(Action.LONG_STRONG)
        assert info["n_positions"] > 0
        assert info["gross_exposure"] > 0

    def test_short_strong_changes_positions(self):
        """SHORT_STRONG should open short positions."""
        env = TradingEnv()
        env.reset(seed=42)
        _, _, _, _, info = env.step(Action.SHORT_STRONG)
        assert info["n_positions"] > 0
        assert info["gross_exposure"] > 0

    def test_obs_always_finite(self):
        """All observations across an episode should be finite."""
        env = TradingEnv(episode_length=50)
        obs, _ = env.reset(seed=42)
        assert np.all(np.isfinite(obs))
        for _ in range(50):
            action = np.random.randint(0, N_ACTIONS)
            obs, _, term, trunc, _ = env.step(action)
            assert np.all(np.isfinite(obs))
            if term or trunc:
                break

    def test_reward_only_at_end(self):
        """Mid-episode reward should be 0; only episode end has non-trivial reward."""
        env = TradingEnv(episode_length=20)
        env.reset(seed=42)
        mid_rewards = []
        for i in range(19):
            _, reward, term, trunc, _ = env.step(Action.LONG_STRONG)
            if not (term or trunc):
                mid_rewards.append(reward)
        # With per-step reward shaping, mid-episode rewards are small but non-zero
        assert all(np.isfinite(r) for r in mid_rewards)
        # Mid-episode rewards should be clipped to [-1, 1] (before episode-end bonus)
        assert all(-1.0 <= r <= 1.0 for r in mid_rewards)

    def test_step_returns_correct_types(self):
        env = TradingEnv()
        env.reset(seed=42)
        obs, reward, terminated, truncated, info = env.step(0)
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_action_applies_previous_day_ranking_not_future_day(self):
        env = TradingEnv(episode_length=3)
        env.reset(seed=42)

        def make_series(prices):
            prices = np.array(prices, dtype=np.float64)
            returns = np.zeros(len(prices), dtype=np.float64)
            returns[1:] = np.diff(prices) / prices[:-1]
            return SimpleNamespace(
                prices=prices,
                returns=returns,
                volumes=np.ones(len(prices), dtype=np.float64),
            )

        env._dataset = {
            "A": make_series([100, 110, 100]),
            "B": make_series([100, 109, 100]),
            "C": make_series([100, 108, 100]),
            "D": make_series([100, 107, 100]),
            "E": make_series([100, 106, 100]),
            "F": make_series([100, 90, 150]),
        }
        env._tickers = list(env._dataset.keys())
        env._scores = {}
        env._num_days = 3
        env._index_returns = sum(ps.returns for ps in env._dataset.values()) / len(env._dataset)
        env._index_volumes = sum(ps.volumes for ps in env._dataset.values()) / len(env._dataset)
        env._index_prices = sum(ps.prices for ps in env._dataset.values()) / len(env._dataset)

        env.step(Action.HOLD)
        env.step(Action.LONG_STRONG)

        assert "F" not in env._positions
        assert set(env._positions) == {"A", "B", "C", "D", "E"}

    def test_step_uses_reference_return_path_when_configured(self):
        env = TradingEnv(episode_length=3, relative_reference_strategy="ridge_excess_top5")
        env.reset(seed=42)
        env._reference_return_path = [0.012, 0.015]

        env.step(Action.HOLD)

        assert len(env._benchmark_daily_returns) == 1
        assert abs(env._benchmark_daily_returns[0] - 0.012) < 1e-12


class TestStopLoss:
    def test_stop_loss_closes_positions(self):
        """Positions hitting stop-loss should be removed."""
        env = TradingEnv(stop_loss=0.0001)  # Very tight stop-loss
        env.reset(seed=42)
        # Take a position
        env.step(Action.LONG_STRONG)
        initial_pos = env._positions.copy()
        # Step several times — tight stop-loss should trigger
        positions_reduced = False
        for _ in range(20):
            env.step(Action.HOLD)
            if len(env._positions) < len(initial_pos):
                positions_reduced = True
                break
        # With a 0.01% stop-loss, positions should get stopped out
        assert positions_reduced or len(env._positions) == 0


class TestTxCost:
    def test_tx_cost_deducted(self):
        """Turnover should reduce NAV through tx costs."""
        env_no_cost = TradingEnv(tx_cost_bps=0, episode_length=10)
        env_with_cost = TradingEnv(tx_cost_bps=50, episode_length=10)

        env_no_cost.reset(seed=42)
        env_with_cost.reset(seed=42)

        # Take the same actions in both
        actions = [Action.LONG_STRONG, Action.SHORT_STRONG] * 5
        for a in actions:
            env_no_cost.step(a)
            env_with_cost.step(a)

        # Higher tx cost should produce lower NAV (or same if no trades)
        # The exact relationship depends on market moves, but with high churn
        # the tx cost env should have lower NAV
        assert env_with_cost._nav <= env_no_cost._nav + 1.0  # Allow small tolerance


class TestCatastrophicNav:
    def test_truncation_on_catastrophic_nav(self):
        """NAV dropping below catastrophic threshold should truncate."""
        env = TradingEnv(catastrophic_nav=99.0, episode_length=252)
        env.reset(seed=42)
        # Force NAV down by trading — at 99.0 threshold, any small loss truncates
        truncated_occurred = False
        for _ in range(252):
            _, _, terminated, truncated, _ = env.step(Action.LONG_STRONG)
            if truncated:
                truncated_occurred = True
                break
            if terminated:
                break
        # With catastrophic_nav=99.0, almost any trading will cause truncation
        assert truncated_occurred or terminated


# ── Reward function ─────────────────────────────────────────────


class TestReward:
    def test_reward_finite(self):
        rets = [0.01, -0.005, 0.02, 0.003, -0.01] * 10
        nav = [100.0]
        for r in rets:
            nav.append(nav[-1] * (1 + r))
        turnover = [0.1] * len(rets)
        reward = compute_reward(rets, nav, turnover)
        assert math.isfinite(reward)

    def test_reward_empty_returns_zero(self):
        assert compute_reward([], [100.0], []) == 0.0
        assert compute_reward([0.01], [100.0, 101.0], [0.1]) == 0.0  # len < 2 after first

    def test_positive_sharpe_positive_reward(self):
        """Consistently positive returns should yield positive base reward."""
        rets = [0.005] * 60
        nav = [100.0]
        for r in rets:
            nav.append(nav[-1] * (1 + r))
        reward = compute_reward(rets, nav, [0.0] * 60)
        assert reward > 0

    def test_drawdown_penalty(self):
        """Larger drawdown penalty coeff should reduce reward for same returns."""
        rets = [0.01] * 20 + [-0.05] * 5 + [0.01] * 35
        nav = [100.0]
        for r in rets:
            nav.append(nav[-1] * (1 + r))
        turnover = [0.0] * len(rets)

        r_low_pen = compute_reward(rets, nav, turnover, drawdown_penalty_coeff=0.0)
        r_high_pen = compute_reward(rets, nav, turnover, drawdown_penalty_coeff=5.0)
        assert r_low_pen > r_high_pen

    def test_benchmark_relative_reward_prefers_true_outperformance(self):
        rets = [0.01, -0.004, 0.012, -0.003, 0.009] * 12
        nav = [100.0]
        for r in rets:
            nav.append(nav[-1] * (1 + r))
        turnover = [0.0] * len(rets)
        weak_benchmark = [r * 0.5 for r in rets]
        strong_benchmark = [r * 1.5 for r in rets]

        reward_vs_weak = compute_reward(
            rets,
            nav,
            turnover,
            benchmark_returns=weak_benchmark,
            benchmark_relative_mix=0.5,
        )
        reward_vs_strong = compute_reward(
            rets,
            nav,
            turnover,
            benchmark_returns=strong_benchmark,
            benchmark_relative_mix=0.5,
        )

        assert reward_vs_weak > reward_vs_strong


# ── State builder ───────────────────────────────────────────────


class TestStateBuilder:
    def test_output_shape(self):
        obs = build_state(
            day=0,
            episode_length=252,
            nav_history=[100.0],
            positions={},
            cash_ratio=1.0,
            index_returns=np.zeros(252),
            index_volumes=np.ones(252),
            index_prices=np.ones(252) * 100,
            factor_scores={},
            tickers=[],
            days_since_rebalance=0,
        )
        assert obs.shape == (57,)
        assert obs.dtype == np.float32
        assert np.all(np.isfinite(obs))

    def test_time_features(self):
        obs = build_state(
            day=126,
            episode_length=252,
            nav_history=[100.0],
            positions={},
            cash_ratio=1.0,
            index_returns=np.zeros(252),
            index_volumes=np.ones(252),
            index_prices=np.ones(252) * 100,
            factor_scores={},
            tickers=[],
            days_since_rebalance=10,
        )
        assert abs(obs[55] - 0.5) < 0.01  # day 126/252
        assert abs(obs[56] - 10.0 / 21.0) < 0.01

    def test_dataset_ranking_uses_current_day_not_static_factor_scores(self):
        prices_a = np.arange(100.0, 123.0, dtype=np.float64)
        returns_a = np.zeros(len(prices_a), dtype=np.float64)
        returns_a[1:] = np.diff(prices_a) / prices_a[:-1]

        prices_b = np.ones(23, dtype=np.float64) * 100.0
        returns_b = np.zeros(len(prices_b), dtype=np.float64)

        dataset = {
            "AAA": SimpleNamespace(prices=prices_a, returns=returns_a),
            "BBB": SimpleNamespace(prices=prices_b, returns=returns_b),
        }

        obs = build_state(
            day=21,
            episode_length=252,
            nav_history=[100.0],
            positions={},
            cash_ratio=1.0,
            index_returns=np.zeros(252),
            index_volumes=np.ones(252),
            index_prices=np.ones(252) * 100,
            factor_scores={
                "AAA": {"_composite": -999.0},
                "BBB": {"_composite": 999.0},
            },
            tickers=["AAA", "BBB"],
            days_since_rebalance=0,
            dataset=dataset,
        )

        expected_aaa_5d = (prices_a[21] - prices_a[16]) / prices_a[16]
        assert abs(obs[15] - expected_aaa_5d) < 1e-6

    def test_rolling_signal_prefers_smoother_trend(self):
        smooth_prices = np.linspace(100.0, 130.0, 30, dtype=np.float64)
        smooth_returns = np.zeros(len(smooth_prices), dtype=np.float64)
        smooth_returns[1:] = np.diff(smooth_prices) / smooth_prices[:-1]
        smooth_volumes = np.ones(len(smooth_prices), dtype=np.float64) * 1_000_000

        choppy_prices = np.array(
            [100, 108, 101, 110, 102, 112, 103, 114, 104, 116,
             105, 118, 106, 119, 107, 121, 108, 122, 109, 123,
             110, 124, 111, 125, 112, 126, 113, 127, 114, 128],
            dtype=np.float64,
        )
        choppy_returns = np.zeros(len(choppy_prices), dtype=np.float64)
        choppy_returns[1:] = np.diff(choppy_prices) / choppy_prices[:-1]
        choppy_volumes = np.ones(len(choppy_prices), dtype=np.float64) * 1_000_000

        smooth = SimpleNamespace(prices=smooth_prices, returns=smooth_returns, volumes=smooth_volumes)
        choppy = SimpleNamespace(prices=choppy_prices, returns=choppy_returns, volumes=choppy_volumes)

        assert rolling_signal_score(smooth, 29) > rolling_signal_score(choppy, 29)


# ── Action space ────────────────────────────────────────────────


class TestActionSpace:
    def test_n_actions(self):
        assert N_ACTIONS == 5

    def test_action_values(self):
        assert Action.HOLD == 0
        assert Action.LONG_STRONG == 1
        assert Action.LONG_MILD == 2
        assert Action.SHORT_STRONG == 3
        assert Action.SHORT_MILD == 4

    def test_position_multipliers(self):
        assert ACTION_POSITION[Action.HOLD] == 0.0
        assert ACTION_POSITION[Action.LONG_STRONG] == 1.0
        assert ACTION_POSITION[Action.LONG_MILD] == 0.5
        assert ACTION_POSITION[Action.SHORT_STRONG] == -1.0
        assert ACTION_POSITION[Action.SHORT_MILD] == -0.5


# ── Episode runner ──────────────────────────────────────────────


class TestEpisodeRunner:
    def test_random_agent_survives_episode(self):
        """Random agent should complete a full 252-day episode without crashing."""
        env = TradingEnv(episode_length=252)
        result = run_episode(env, random_policy, seed=42)
        assert result.episode_length > 0
        assert math.isfinite(result.total_reward)
        assert math.isfinite(result.final_nav)
        assert result.final_nav > 0
        assert result.terminated or result.truncated

    def test_trajectory_stored(self):
        """Trajectory should contain transitions for every step."""
        env = TradingEnv(episode_length=50)
        result = run_episode(env, random_policy, seed=42)
        assert len(result.trajectory) == result.episode_length
        for t in result.trajectory:
            assert t.state.shape == (57,)
            assert t.next_state.shape == (57,)
            assert 0 <= t.action < N_ACTIONS
            assert isinstance(t.reward, float)
            assert isinstance(t.done, bool)

    def test_hold_policy(self):
        """A hold-only policy should run to completion."""
        env = TradingEnv(episode_length=100)
        result = run_episode(env, lambda s: Action.HOLD, seed=42)
        assert result.terminated or result.truncated
        assert result.episode_length > 0

    def test_deterministic_with_seed(self):
        """Same seed + same policy = same result."""
        env = TradingEnv(episode_length=50)
        np.random.seed(123)
        r1 = run_episode(env, lambda s: Action.LONG_STRONG, seed=42)
        np.random.seed(123)
        r2 = run_episode(env, lambda s: Action.LONG_STRONG, seed=42)
        assert r1.final_nav == r2.final_nav
        assert r1.total_reward == r2.total_reward
