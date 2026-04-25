"""
Gym-compatible trading environment — MARL handoff point.

47-dim observation, 5 discrete actions, log-return reward.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import math
import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
    HAS_GYM = True
except ImportError:
    HAS_GYM = False

from data.synthetic import generate_dataset, safe_div, clamp, PriceSeries
from factors.registry import load_factor, JS_FACTOR_NAMES
from backtest.engine import _compute_factor_scores_js


@dataclass
class EnvConfig:
    sector: str = "Technology"
    lookback: int = 252
    base_seed: int = 42
    initial_nav: float = 100.0
    tx_cost_bps: int = 5
    max_position: float = 1.0


if HAS_GYM:
    class TradingEnv(gym.Env):
        """Single-agent trading environment over synthetic AlphaForge data.

        Actions: 0=HOLD, 1=BUY, 2=SELL, 3=SCALE_UP, 4=SCALE_DOWN
        Observation: 47-dim float32.
        Reward: log(NAV_t / NAV_{t-1})
        """

        metadata = {"render_modes": ["human"]}

        def __init__(self, config: Optional[EnvConfig] = None,
                     render_mode: Optional[str] = None):
            super().__init__()
            self.config = config or EnvConfig()
            self.render_mode = render_mode
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(47,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(5)
            self._dataset: Dict[str, PriceSeries] = {}
            self._tickers: list = []
            self._scores: dict = {}
            self._day: int = 0
            self._nav: float = self.config.initial_nav
            self._prev_nav: float = self.config.initial_nav
            self._position: float = 0.0
            self._num_days: int = 0

        def reset(self, *, seed: Optional[int] = None,
                  options: Optional[dict] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
            super().reset(seed=seed)
            base_seed = seed if seed is not None else self.config.base_seed
            self._dataset = generate_dataset(
                self.config.sector, self.config.lookback, base_seed
            )
            self._tickers = list(self._dataset.keys())
            self._scores = _compute_factor_scores_js(self._dataset, self.config.lookback)
            self._day = 21
            self._nav = self.config.initial_nav
            self._prev_nav = self.config.initial_nav
            self._position = 0.0
            self._num_days = (
                len(self._dataset[self._tickers[0]].prices) if self._tickers else 0
            )
            return self._get_obs(), {"day": self._day, "nav": self._nav}

        def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
            tx_cost = self.config.tx_cost_bps / 10000
            old_position = self._position

            if action == 1:
                self._position = min(self.config.max_position, self._position + 0.25)
            elif action == 2:
                self._position = max(-self.config.max_position, self._position - 0.25)
            elif action == 3:
                self._position = min(
                    self.config.max_position,
                    self._position * 1.5 if self._position > 0 else self._position + 0.1,
                )
            elif action == 4:
                self._position *= 0.5

            cost = abs(self._position - old_position) * tx_cost

            self._day += 1
            market_return = 0.0
            if self._tickers and self._day < self._num_days:
                for t in self._tickers:
                    market_return += self._dataset[t].returns[self._day] / len(self._tickers)

            port_return = self._position * market_return - cost
            self._prev_nav = self._nav
            self._nav = max(0.01, self._nav * (1 + clamp(port_return, -0.20, 0.20)))

            reward = float(math.log(self._nav / self._prev_nav)) if self._prev_nav > 0 else 0.0
            terminated = bool(self._day >= self._num_days - 1)
            truncated = bool(not terminated and self._nav < 1.0)

            return (
                self._get_obs(),
                reward,
                terminated,
                truncated,
                {"day": self._day, "nav": self._nav, "position": self._position,
                 "market_return": market_return},
            )

        def _get_obs(self) -> np.ndarray:
            obs = np.zeros(47, dtype=np.float32)
            if not self._tickers or self._day >= self._num_days:
                return obs

            ticker = self._tickers[0]
            d = self._dataset[ticker]
            p, v = d.prices, d.volumes
            day = min(self._day, len(p) - 1)

            # Price returns
            for idx, w in enumerate([1, 5, 21, 63, 252]):
                if day >= w:
                    obs[idx] = float(safe_div(p[day] - p[day - w], p[day - w], 0.0))

            # Volume features
            if day >= 5:
                vol5 = float(np.mean(v[max(0, day - 4):day + 1]))
                vol20 = float(np.mean(v[max(0, day - 19):day + 1])) if day >= 20 else vol5
                obs[5] = float(safe_div(v[day], vol20, 1.0))
                obs[6] = float(safe_div(vol5 - vol20, vol20, 0.0))
                obs[7] = float(np.log1p(v[day] / 1e6))

            # Volatility
            if day >= 21:
                rets = np.diff(p[day - 20:day + 1]) / p[day - 20:day]
                obs[8] = float(np.std(rets, ddof=1) * math.sqrt(252))
                if day >= 63:
                    rets_l = np.diff(p[day - 62:day + 1]) / p[day - 62:day]
                    obs[9] = float(np.std(rets_l, ddof=1) * math.sqrt(252))
                obs[10] = float(obs[8] - obs[9]) if day >= 63 else 0.0

            # Factor z-scores
            s = self._scores.get(ticker, {})
            for idx, f in enumerate(JS_FACTOR_NAMES):
                obs[11 + idx] = float(s.get(f, 0.0))
            obs[16] = float(s.get("_composite", 0.0)) / 100.0
            signal = s.get("_signal", "NEUTRAL")
            obs[17] = 1.0 if signal == "LONG" else (-1.0 if signal == "SHORT" else 0.0)

            # MA distances
            if day >= 21:
                ma21 = float(np.mean(p[day - 20:day + 1]))
                obs[18] = float(safe_div(p[day] - ma21, ma21, 0.0))
            if day >= 50:
                ma50 = float(np.mean(p[max(0, day - 49):day + 1]))
                obs[19] = float(safe_div(p[day] - ma50, ma50, 0.0))
            obs[20] = float(self._position)
            obs[21] = float(safe_div(
                self._nav - self.config.initial_nav, self.config.initial_nav, 0.0
            ))

            return obs

        def render(self) -> None:
            if self.render_mode == "human":
                print(f"Day {self._day:4d} | NAV {self._nav:8.2f} | Pos {self._position:+.2f}")
