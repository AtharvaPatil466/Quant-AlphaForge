"""
Gym environment tests — interface compliance and basic episode mechanics.
"""

import numpy as np
import pytest

try:
    import gymnasium
    HAS_GYM = True
except ImportError:
    HAS_GYM = False

from backtest.environment import EnvConfig, HAS_GYM as ENV_HAS_GYM


@pytest.mark.skipif(not HAS_GYM, reason="gymnasium not installed")
class TestTradingEnv:
    @pytest.fixture
    def env(self):
        from backtest.environment import TradingEnv
        e = TradingEnv(EnvConfig(sector="Technology", lookback=252, base_seed=42))
        yield e
        e.close()

    def test_reset_shape(self, env):
        obs, info = env.reset(seed=42)
        assert obs.shape == (47,)
        assert obs.dtype == np.float32

    def test_step_shape(self, env):
        env.reset(seed=42)
        obs, reward, terminated, truncated, info = env.step(0)
        assert obs.shape == (47,)
        assert isinstance(reward, float)
        assert terminated is True or terminated is False  # Python bool
        assert truncated is True or truncated is False

    def test_reward_finite(self, env):
        env.reset(seed=42)
        for _ in range(50):
            obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
            assert np.isfinite(reward)
            if terminated or truncated:
                break

    def test_deterministic_reset(self, env):
        obs1, _ = env.reset(seed=42)
        obs2, _ = env.reset(seed=42)
        np.testing.assert_array_equal(obs1, obs2)

    def test_full_episode(self, env):
        """Run a full episode without crashing."""
        obs, info = env.reset(seed=42)
        total_reward = 0.0
        steps = 0
        while True:
            action = env.action_space.sample()
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break
        assert steps > 0
        assert np.isfinite(total_reward)

    def test_10_random_episodes(self, env):
        """10 random episodes complete without error."""
        for seed in range(10):
            env.reset(seed=seed)
            done = False
            while not done:
                _, _, terminated, truncated, _ = env.step(env.action_space.sample())
                done = terminated or truncated

    def test_gym_check_env(self):
        """Official Gymnasium compliance check."""
        from backtest.environment import TradingEnv
        from gymnasium.utils.env_checker import check_env
        env = TradingEnv(EnvConfig(sector="Technology", lookback=100, base_seed=42))
        check_env(env, skip_render_check=True)
        env.close()
