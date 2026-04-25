"""
Gym-compatible trading environment — MARL handoff point.

Implements a Gymnasium Env that wraps the AlphaForge data and backtest
layers. Agents observe factor scores and market state, take discrete
trading actions, and receive log-return rewards.

State vector: 47 dimensions total
  - 22 active (price/volume/technical features)
  - 25 zeroed (reserved for portfolio state, regime, time in MARL Phase 0)
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

from .data import generate_dataset, safe_div, clamp, PriceSeries
from .factors import get_factor, JS_FACTOR_NAMES
from .scoring import compute_factor_scores_js


@dataclass
class EnvConfig:
    """Configuration for the TradingEnv."""
    sector: str = "Technology"
    lookback: int = 252
    base_seed: int = 42
    initial_nav: float = 100.0
    tx_cost_bps: int = 5
    max_position: float = 1.0  # max fraction of capital in one direction


if HAS_GYM:
    class TradingEnv(gym.Env):
        """Single-agent trading environment over synthetic AlphaForge data.

        Actions:
            0 = HOLD
            1 = BUY  (go long / increase position)
            2 = SELL  (go short / decrease position)
            3 = SCALE_UP (increase position size)
            4 = SCALE_DOWN (decrease position size)

        Observation: 47-dim float32 vector.
        Reward: log(NAV_t / NAV_{t-1}) — simple log return.
        """

        metadata = {"render_modes": ["human"]}

        def __init__(
            self,
            config: Optional[EnvConfig] = None,
            render_mode: Optional[str] = None,
        ):
            super().__init__()
            self.config = config or EnvConfig()
            self.render_mode = render_mode

            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(47,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(5)

            # Internal state
            self._dataset: Dict[str, PriceSeries] = {}
            self._tickers: list = []
            self._scores: dict = {}
            self._day: int = 0
            self._nav: float = self.config.initial_nav
            self._prev_nav: float = self.config.initial_nav
            self._position: float = 0.0  # -1.0 to 1.0
            self._num_days: int = 0

        def reset(
            self,
            *,
            seed: Optional[int] = None,
            options: Optional[dict] = None,
        ) -> Tuple[np.ndarray, Dict[str, Any]]:
            super().reset(seed=seed)
            base_seed = seed if seed is not None else self.config.base_seed
            self._dataset = generate_dataset(
                self.config.sector, self.config.lookback, base_seed
            )
            self._tickers = list(self._dataset.keys())
            self._scores = compute_factor_scores_js(self._dataset, self.config.lookback)
            self._day = 21  # skip first 21 days for factor warm-up
            self._nav = self.config.initial_nav
            self._prev_nav = self.config.initial_nav
            self._position = 0.0
            self._num_days = len(self._dataset[self._tickers[0]].prices) if self._tickers else 0

            obs = self._get_obs()
            info = {"day": self._day, "nav": self._nav}
            return obs, info

        def step(
            self, action: int
        ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
            # Apply action
            tx_cost = self.config.tx_cost_bps / 10000
            old_position = self._position

            if action == 0:    # HOLD
                pass
            elif action == 1:  # BUY
                self._position = min(self.config.max_position, self._position + 0.25)
            elif action == 2:  # SELL
                self._position = max(-self.config.max_position, self._position - 0.25)
            elif action == 3:  # SCALE_UP
                self._position = min(self.config.max_position, self._position * 1.5 if self._position > 0 else self._position + 0.1)
            elif action == 4:  # SCALE_DOWN
                self._position *= 0.5

            # Transaction cost for position change
            pos_change = abs(self._position - old_position)
            cost = pos_change * tx_cost

            # Compute portfolio return from equal-weight market exposure
            self._day += 1
            market_return = 0.0
            if self._tickers and self._day < self._num_days:
                for t in self._tickers:
                    market_return += self._dataset[t].returns[self._day] / len(self._tickers)

            port_return = self._position * market_return - cost
            self._prev_nav = self._nav
            self._nav = max(0.01, self._nav * (1 + clamp(port_return, -0.20, 0.20)))

            # Reward: log return
            reward = float(math.log(self._nav / self._prev_nav)) if self._prev_nav > 0 else 0.0

            terminated = bool(self._day >= self._num_days - 1)
            truncated = bool(not terminated and self._nav < 1.0)  # bankrupt, only if not already terminated

            obs = self._get_obs()
            info = {
                "day": self._day,
                "nav": self._nav,
                "position": self._position,
                "market_return": market_return,
            }

            return obs, reward, terminated, truncated, info

        def _get_obs(self) -> np.ndarray:
            """Build 47-dim observation vector.

            Dims 0-21: active (price/volume/technical features)
            Dims 22-46: zeroed (reserved for MARL Phase 0)
            """
            obs = np.zeros(47, dtype=np.float32)

            if not self._tickers or self._day >= self._num_days:
                return obs

            # Use the first ticker as representative (single-agent simplification)
            # In MARL, each agent will have its own ticker
            ticker = self._tickers[0]
            d = self._dataset[ticker]
            p = d.prices
            v = d.volumes
            day = min(self._day, len(p) - 1)

            # Price features (dims 0-4)
            if day >= 1:
                obs[0] = float(safe_div(p[day] - p[day - 1], p[day - 1], 0.0))  # 1d return
            if day >= 5:
                obs[1] = float(safe_div(p[day] - p[day - 5], p[day - 5], 0.0))  # 5d return
            if day >= 21:
                obs[2] = float(safe_div(p[day] - p[day - 21], p[day - 21], 0.0))  # 21d return
            if day >= 63:
                obs[3] = float(safe_div(p[day] - p[day - 63], p[day - 63], 0.0))  # 63d return
            if day >= 252:
                obs[4] = float(safe_div(p[day] - p[day - 252], p[day - 252], 0.0))  # 252d return

            # Volume features (dims 5-7)
            if day >= 5:
                vol5 = float(np.mean(v[max(0, day - 4) : day + 1]))
                vol20 = float(np.mean(v[max(0, day - 19) : day + 1])) if day >= 20 else vol5
                obs[5] = float(safe_div(v[day], vol20, 1.0))  # volume ratio
                obs[6] = float(safe_div(vol5 - vol20, vol20, 0.0))  # volume trend
                obs[7] = float(np.log1p(v[day] / 1e6))  # log volume

            # Volatility features (dims 8-10)
            if day >= 21:
                rets = np.diff(p[day - 20 : day + 1]) / p[day - 20 : day]
                obs[8] = float(np.std(rets, ddof=1) * math.sqrt(252))  # realized vol
                if day >= 63:
                    rets_long = np.diff(p[day - 62 : day + 1]) / p[day - 62 : day]
                    obs[9] = float(np.std(rets_long, ddof=1) * math.sqrt(252))
                obs[10] = float(obs[8] - obs[9]) if day >= 63 else 0.0  # vol of vol proxy

            # Factor scores (dims 11-15): the 5 JS factors
            s = self._scores.get(ticker, {})
            for idx, f in enumerate(JS_FACTOR_NAMES):
                obs[11 + idx] = float(s.get(f, 0.0))

            # Composite and signal (dims 16-17)
            obs[16] = float(s.get("_composite", 0.0)) / 100.0  # normalized
            signal = s.get("_signal", "NEUTRAL")
            obs[17] = 1.0 if signal == "LONG" else (-1.0 if signal == "SHORT" else 0.0)

            # Price level features (dims 18-21)
            if day >= 21:
                ma21 = float(np.mean(p[day - 20 : day + 1]))
                obs[18] = float(safe_div(p[day] - ma21, ma21, 0.0))  # distance from MA21
            if day >= 50:
                ma50 = float(np.mean(p[max(0, day - 49) : day + 1]))
                obs[19] = float(safe_div(p[day] - ma50, ma50, 0.0))  # distance from MA50
            obs[20] = float(self._position)  # current position
            obs[21] = float(safe_div(self._nav - self.config.initial_nav, self.config.initial_nav, 0.0))  # PnL %

            # Dims 22-46 are zeroed — reserved for MARL Phase 0

            return obs

        def render(self) -> None:
            if self.render_mode == "human":
                print(
                    f"Day {self._day:4d} | NAV {self._nav:8.2f} | "
                    f"Pos {self._position:+.2f}"
                )
