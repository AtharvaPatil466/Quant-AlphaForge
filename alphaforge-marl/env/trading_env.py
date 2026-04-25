"""
MARL Trading Environment — Gymnasium-compatible.

Supports four data modes:
- "synthetic" (default): Deterministic PRNG-based prices from alphaforge-python.
- "real": Real market data via yfinance, converted to PriceSeries format.
- "real_strict": Real market data only. Raises if data is unavailable/invalid.
- "hybrid": Randomly mixes synthetic and real episodes for robustness.

Observation: 57-dim float32. Actions: 5 discrete or 10-dim continuous.
Reward: Dense per-step shaping + Sharpe-based episode-end reward.
"""

from __future__ import annotations

import math
from datetime import date
import random
import sys
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import gymnasium as gym
from gymnasium import spaces

# Add alpha engine to path so we can import its modules directly
_ALPHA_ENGINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "alphaforge-python",
)
if _ALPHA_ENGINE not in sys.path:
    sys.path.insert(0, _ALPHA_ENGINE)

from data.synthetic import generate_dataset, generate_prices, PriceSeries, safe_div, clamp
from backtest.engine import _compute_factor_scores_js
from factors.registry import JS_FACTOR_NAMES

from env.action_space import Action, ACTION_POSITION, N_ACTIONS, continuous_weights_to_positions
from env.state_builder import build_state, rolling_signal_score
from env.reward import compute_reward


class TradingEnv(gym.Env):
    """Multi-agent capable trading environment.

    Wraps the AlphaForge synthetic market with a richer 57-dim state
    and Sharpe-based episode-end reward.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        sector: str = "Technology",
        lookback: int = 252,
        base_seed: int = 42,
        episode_length: int = 252,
        max_position: float = 0.05,
        max_gross_exposure: float = 1.50,
        stop_loss: float = 0.03,
        tx_cost_bps: int = 5,
        catastrophic_nav: float = 0.50,
        render_mode: Optional[str] = None,
        # Data mode: "synthetic", "real", "real_strict", or "hybrid"
        data_mode: str = "synthetic",
        real_data_cache_dir: Optional[str] = None,
        real_data_dir: Optional[str] = None,
        real_data_start_date: Optional[date | str] = None,
        real_data_end_date: Optional[date | str] = None,
        hybrid_real_prob: float = 0.5,
        strict_real_data: bool = False,
        normalize_observations: bool = True,
        observation_norm_window: int = 63,
        # Reward params
        drawdown_penalty_coeff: float = 2.0,
        drawdown_threshold: float = 0.10,
        consistency_bonus: float = 0.20,
        consistency_threshold: float = 0.55,
        turnover_penalty_coeff: float = 0.10,
        benchmark_relative_mix: float = 0.5,
        relative_reference_strategy: str = "equal_weight",
        sharpe_delta_scale: float = 0.5,
        drawdown_step_penalty: float = 0.5,
        participation_bonus: float = 0.005,
        inactivity_penalty: float = 0.10,
        baseline_sharpe_reference: float = 0.8,
        episode_reward_scale: Optional[float] = None,
    ):
        super().__init__()
        self.sector = sector
        self.lookback = lookback
        self.base_seed = base_seed
        self.data_mode = data_mode
        self.real_data_cache_dir = real_data_cache_dir
        self.real_data_dir = real_data_dir
        if isinstance(real_data_start_date, str):
            self.real_data_start_date = date.fromisoformat(real_data_start_date)
        else:
            self.real_data_start_date = real_data_start_date
        if isinstance(real_data_end_date, str):
            self.real_data_end_date = date.fromisoformat(real_data_end_date)
        else:
            self.real_data_end_date = real_data_end_date
        self.hybrid_real_prob = hybrid_real_prob
        self.strict_real_data = strict_real_data or data_mode == "real_strict"
        self.normalize_observations = normalize_observations
        self.observation_norm_window = max(2, int(observation_norm_window))
        self._real_windows: Optional[List[Dict[str, PriceSeries]]] = None
        self._resolved_data_source: str = "synthetic"
        self.episode_length = episode_length
        self.max_position = max_position
        self.max_gross_exposure = max_gross_exposure
        self.stop_loss = stop_loss
        self.tx_cost = tx_cost_bps / 10000.0
        self.catastrophic_nav = catastrophic_nav
        self.render_mode = render_mode

        # Reward params
        self._reward_kwargs = dict(
            drawdown_penalty_coeff=drawdown_penalty_coeff,
            drawdown_threshold=drawdown_threshold,
            consistency_bonus=consistency_bonus,
            consistency_threshold=consistency_threshold,
            turnover_penalty_coeff=turnover_penalty_coeff,
            benchmark_relative_mix=benchmark_relative_mix,
        )
        self.relative_reference_strategy = relative_reference_strategy
        self.sharpe_delta_scale = sharpe_delta_scale
        self.drawdown_step_penalty = drawdown_step_penalty
        self.participation_bonus = participation_bonus
        self.inactivity_penalty = inactivity_penalty
        if episode_reward_scale is None:
            self.episode_reward_scale = max(
                1.0,
                2.0 / max(0.25, float(baseline_sharpe_reference)),
            )
        else:
            self.episode_reward_scale = float(episode_reward_scale)

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(57,), dtype=np.float32
        )
        # Support both discrete and continuous action spaces
        self.continuous_actions = False
        self.action_space = spaces.Discrete(N_ACTIONS)

        # Episode state (initialized in reset)
        self._dataset: Dict[str, PriceSeries] = {}
        self._tickers: List[str] = []
        self._scores: Dict[str, Dict[str, float]] = {}
        self._num_days: int = 0
        self._day: int = 0
        self._nav: float = 100.0
        self._nav_history: List[float] = []
        self._daily_returns: List[float] = []
        self._benchmark_daily_returns: List[float] = []
        self._active_daily_returns: List[float] = []
        self._reference_return_path: List[float] = []
        self._daily_turnover: List[float] = []
        self._positions: Dict[str, float] = {}  # ticker -> weight
        self._prev_gross: float = 0.0
        self._days_since_rebalance: int = 0
        self._index_returns: np.ndarray = np.zeros(0)
        self._index_volumes: np.ndarray = np.zeros(0)
        self._index_prices: np.ndarray = np.zeros(0)
        self._prev_rolling_sharpe: float = 0.0
        self._episode_seed: int = base_seed
        self._raw_obs_history: List[np.ndarray] = []

    def reset(
        self, *, seed: Optional[int] = None, options: Optional[dict] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        super().reset(seed=seed)
        ep_seed = seed if seed is not None else self.base_seed
        self._episode_seed = int(ep_seed)

        # Choose data source based on data_mode
        use_real = False
        if self.data_mode in {"real", "real_strict"}:
            use_real = True
        elif self.data_mode == "hybrid":
            use_real = random.random() < self.hybrid_real_prob

        if use_real:
            self._dataset = self._load_real_data(ep_seed)
        else:
            self._dataset = generate_dataset(self.sector, self.lookback, ep_seed)
            self._resolved_data_source = "synthetic"

        self._tickers = list(self._dataset.keys())
        self._scores = _compute_factor_scores_js(self._dataset, self.lookback)
        self._num_days = (
            len(self._dataset[self._tickers[0]].prices) if self._tickers else 0
        )

        # Build equal-weight index
        if self._tickers and self._num_days > 0:
            all_rets = np.zeros(self._num_days)
            all_vols = np.zeros(self._num_days)
            all_prices = np.zeros(self._num_days)
            for t in self._tickers:
                all_rets += self._dataset[t].returns / len(self._tickers)
                all_vols += self._dataset[t].volumes / len(self._tickers)
                all_prices += self._dataset[t].prices / len(self._tickers)
            self._index_returns = all_rets
            self._index_volumes = all_vols
            self._index_prices = all_prices
        else:
            self._index_returns = np.zeros(1)
            self._index_volumes = np.ones(1)
            self._index_prices = np.ones(1)

        self._reference_return_path = self._build_reference_return_path()

        self._day = 0
        self._nav = 100.0
        self._nav_history = [100.0]
        self._daily_returns = []
        self._benchmark_daily_returns = []
        self._active_daily_returns = []
        self._daily_turnover = []
        self._positions = {}
        self._prev_gross = 0.0
        self._days_since_rebalance = 0
        self._prev_rolling_sharpe = 0.0
        self._raw_obs_history = []

        return self._get_obs(), self._get_info()

    def set_continuous(self, enabled: bool = True) -> None:
        """Switch to continuous action space (10-dim weight vector)."""
        self.continuous_actions = enabled
        if enabled:
            self.action_space = spaces.Box(
                low=-self.max_position, high=self.max_position,
                shape=(10,), dtype=np.float32,
            )
        else:
            self.action_space = spaces.Discrete(N_ACTIONS)

    def step(
        self, action
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        # ── Apply action ─────────────────────────────────────────
        decision_day = self._day
        old_positions = dict(self._positions)

        if self.continuous_actions and not isinstance(action, (int, np.integer)):
            # Continuous: action is a weight vector
            weights = np.asarray(action, dtype=np.float32)
            ranked = self._rank_tickers(day=decision_day)
            top5 = ranked[:5]
            bot5 = ranked[-5:] if len(ranked) >= 5 else ranked[:5]
            self._positions = continuous_weights_to_positions(
                weights, top5, bot5,
                self.max_position, self.max_gross_exposure,
            )
        else:
            act = Action(int(action))
            self._apply_action(act, day=decision_day)

        self._day += 1

        # ── Compute turnover ─────────────────────────────────────
        turnover = self._compute_turnover(old_positions)
        self._daily_turnover.append(turnover)

        # ── Portfolio return for this day ────────────────────────
        port_return = 0.0
        benchmark_return = 0.0
        if self._day < self._num_days:
            for ticker, weight in self._positions.items():
                if ticker in self._dataset:
                    ret = self._dataset[ticker].returns[self._day]
                    port_return += weight * ret
            ref_idx = self._day - 1
            if 0 <= ref_idx < len(self._reference_return_path):
                benchmark_return = float(self._reference_return_path[ref_idx])
            else:
                benchmark_return = float(self._index_returns[self._day]) if len(self._index_returns) > self._day else 0.0

        # Transaction cost
        port_return -= turnover * self.tx_cost
        active_return = port_return - benchmark_return

        # Update NAV
        new_nav = self._nav * (1.0 + clamp(port_return, -0.20, 0.20))
        new_nav = max(0.01, new_nav)
        self._daily_returns.append(port_return)
        self._benchmark_daily_returns.append(benchmark_return)
        self._active_daily_returns.append(active_return)
        self._nav = new_nav
        self._nav_history.append(new_nav)

        # ── Stop-loss check ──────────────────────────────────────
        self._check_stop_losses()

        # ── Days since rebalance ─────────────────────────────────
        if old_positions != self._positions:
            self._days_since_rebalance = 0
        else:
            self._days_since_rebalance += 1

        # ── Termination ──────────────────────────────────────────
        terminated = bool(self._day >= min(self.episode_length, self._num_days - 1))
        truncated = bool(
            not terminated and self._nav < self.catastrophic_nav
        )

        # ── Per-step reward: dense shaping ──────────────────────
        step_reward = 0.0

        # 1. Rolling Sharpe delta: reward improvement in rolling Sharpe
        prev_sharpe = self._prev_rolling_sharpe
        curr_sharpe = self._rolling_reward_signal_21d()
        sharpe_delta = curr_sharpe - prev_sharpe
        self._prev_rolling_sharpe = curr_sharpe
        step_reward += np.clip(sharpe_delta * self.sharpe_delta_scale, -0.10, 0.10)

        # 2. Drawdown-aware penalty: penalize new drawdowns in real time
        nav_arr = np.array(self._nav_history)
        peak = float(np.max(nav_arr))
        curr_dd = (peak - self._nav) / max(peak, 1e-10)
        dd_threshold = float(self._reward_kwargs.get("drawdown_threshold", 0.10))
        if curr_dd > dd_threshold:
            step_reward -= (curr_dd - dd_threshold) * self.drawdown_step_penalty

        # 3. Participation incentive (softer than before)
        if len(self._positions) > 0:
            step_reward += self.participation_bonus
        else:
            step_reward -= self.inactivity_penalty

        # ── Episode-end reward (scaled up) ───────────────────────
        reward = step_reward
        if terminated or truncated:
            episode_reward = compute_reward(
                self._daily_returns,
                self._nav_history,
                self._daily_turnover,
                benchmark_returns=self._benchmark_daily_returns,
                **self._reward_kwargs,
            )
            reward += episode_reward * self.episode_reward_scale

        reward = reward if math.isfinite(reward) else 0.0
        return self._get_obs(), float(reward), terminated, truncated, self._get_info()

    def _load_real_data(self, seed: int) -> Dict[str, PriceSeries]:
        """Load real market data for an episode.

        Uses pre-fetched windowed data when available (fast, no network call).
        Falls back to on-demand fetch. The seed selects which window to use,
        giving different training episodes different market periods.
        """
        from env.real_data import (
            generate_real_dataset,
            generate_real_dataset_windowed,
            validate_real_data,
        )
        strict_real = self.strict_real_data or self.data_mode == "real_strict"

        # Lazy-load windowed data on first call
        if self._real_windows is None:
            try:
                self._real_windows = generate_real_dataset_windowed(
                    sector=self.sector,
                    total_days=max(756, self.lookback * 3),
                    window_size=self.lookback,
                    start_date=self.real_data_start_date,
                    end_date=self.real_data_end_date,
                    cache_dir=self.real_data_cache_dir,
                    market_dir=self.real_data_dir,
                )
            except Exception:
                self._real_windows = []

        # Select window based on seed for reproducibility
        if self._real_windows:
            idx = seed % len(self._real_windows)
            dataset = self._real_windows[idx]
            if validate_real_data(dataset, min_days=self.lookback // 2):
                self._resolved_data_source = "real"
                return dataset

        # Fallback: generate fresh (may hit network)
        try:
            dataset = generate_real_dataset(
                sector=self.sector,
                lookback=self.lookback,
                start_date=self.real_data_start_date,
                end_date=self.real_data_end_date,
                cache_dir=self.real_data_cache_dir,
                market_dir=self.real_data_dir,
            )
            if validate_real_data(dataset, min_days=self.lookback // 2):
                self._resolved_data_source = "real"
                return dataset
        except Exception:
            if strict_real:
                raise

        if strict_real:
            raise RuntimeError(
                "Strict real-data mode could not load a valid real market dataset"
            )

        # Last resort: synthetic
        self._resolved_data_source = "synthetic_fallback"
        return generate_dataset(self.sector, self.lookback, seed)

    def _rolling_reward_signal_21d(self) -> float:
        """Blend portfolio and active Sharpe over the recent window."""
        if len(self._daily_returns) < 21:
            return 0.0

        def _annualized_sharpe(values: List[float]) -> float:
            arr = np.asarray(values, dtype=np.float64)
            if len(arr) < 2:
                return 0.0
            mu = float(np.mean(arr))
            sigma = float(np.std(arr, ddof=1))
            if sigma < 1e-12:
                return 0.0
            out = (mu / sigma) * math.sqrt(252)
            return out if math.isfinite(out) else 0.0

        mix = float(self._reward_kwargs.get("benchmark_relative_mix", 0.5))
        port_sharpe = _annualized_sharpe(self._daily_returns[-21:])
        active_sharpe = _annualized_sharpe(self._active_daily_returns[-21:])
        return (1.0 - mix) * port_sharpe + mix * active_sharpe

    def _build_reference_return_path(self) -> List[float]:
        """Precompute benchmark/reference returns for relative reward shaping."""
        strategy = (self.relative_reference_strategy or "equal_weight").strip()
        if strategy in {"", "equal_weight"} or not self._dataset:
            return []

        try:
            from training.baselines import simulate_baseline_path

            result = simulate_baseline_path(
                self._dataset,
                strategy=strategy,
                tx_cost_bps=int(self.tx_cost * 10000),
                seed=self._episode_seed,
            )
            daily_returns = [
                float(item)
                for item in result.get("daily_returns", [])
                if math.isfinite(float(item))
            ]
            return daily_returns
        except Exception:
            return []

    def _apply_action(self, action: Action, day: Optional[int] = None) -> None:
        """Update portfolio positions based on action."""
        if action == Action.HOLD:
            return

        multiplier = ACTION_POSITION[action]
        ranked = self._rank_tickers(day=day)
        top5 = ranked[:5]
        bot5 = ranked[-5:] if len(ranked) >= 5 else []

        new_positions: Dict[str, float] = {}

        if multiplier > 0:  # Long actions
            for t in top5:
                new_positions[t] = self.max_position * abs(multiplier)
        elif multiplier < 0:  # Short actions
            for t in bot5:
                new_positions[t] = -self.max_position * abs(multiplier)

        # Enforce gross exposure limit
        gross = sum(abs(v) for v in new_positions.values())
        if gross > self.max_gross_exposure:
            scale = self.max_gross_exposure / gross
            new_positions = {t: w * scale for t, w in new_positions.items()}

        self._positions = new_positions

    def _check_stop_losses(self) -> None:
        """Close positions that have hit stop-loss."""
        if self._day >= self._num_days:
            return
        to_close = []
        for ticker, weight in self._positions.items():
            if ticker not in self._dataset:
                continue
            d = self._dataset[ticker]
            if self._day >= len(d.prices) or self._day < 1:
                continue
            entry_price = d.prices[max(0, self._day - 1)]
            curr_price = d.prices[self._day]
            ret = safe_div(curr_price - entry_price, entry_price, 0.0)
            pos_pnl = weight * ret
            if pos_pnl < -self.stop_loss:
                to_close.append(ticker)
        for t in to_close:
            del self._positions[t]

    def _compute_turnover(self, old: Dict[str, float]) -> float:
        """Sum of absolute weight changes."""
        all_tickers = set(old.keys()) | set(self._positions.keys())
        turnover = 0.0
        for t in all_tickers:
            old_w = old.get(t, 0.0)
            new_w = self._positions.get(t, 0.0)
            turnover += abs(new_w - old_w)
        return turnover

    def _rank_tickers(self, day: Optional[int] = None) -> List[str]:
        """Rank tickers by rolling composite signal at the current day.

        Uses a blend of 5-day momentum, 21-day momentum, and mean-reversion
        so the ranking changes every step — the agent's action produces
        different positions at different points in the episode.
        """
        ref_day = self._day if day is None else day
        d = min(ref_day, self._num_days - 1)
        scored: List[tuple] = []
        for t in self._tickers:
            ps = self._dataset.get(t)
            if ps is None or d < 1:
                scored.append((t, 0.0))
                continue
            composite = rolling_signal_score(ps, d)
            scored.append((t, composite))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in scored]

    def _get_obs(self) -> np.ndarray:
        raw_obs = build_state(
            day=self._day,
            episode_length=self.episode_length,
            nav_history=self._nav_history,
            positions=self._positions,
            cash_ratio=1.0 - sum(abs(v) for v in self._positions.values()),
            index_returns=self._index_returns,
            index_volumes=self._index_volumes,
            index_prices=self._index_prices,
            factor_scores=self._scores,
            tickers=self._tickers,
            days_since_rebalance=self._days_since_rebalance,
            dataset=self._dataset,
        )
        if not self.normalize_observations:
            return raw_obs

        if self._raw_obs_history:
            recent = np.asarray(self._raw_obs_history[-self.observation_norm_window :], dtype=np.float32)
            mean_vec = np.mean(recent, axis=0)
            std_vec = np.std(recent, axis=0)
            std_vec = np.where(std_vec < 1e-6, 1.0, std_vec)
            obs = (raw_obs - mean_vec) / std_vec
        else:
            obs = raw_obs

        self._raw_obs_history.append(np.asarray(raw_obs, dtype=np.float32))
        return np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    def _get_info(self) -> Dict[str, Any]:
        return {
            "day": self._day,
            "nav": self._nav,
            "n_positions": len(self._positions),
            "gross_exposure": sum(abs(v) for v in self._positions.values()),
            "data_mode": self.data_mode,
            "strict_real_data": self.strict_real_data,
            "resolved_data_source": self._resolved_data_source,
            "relative_reference_strategy": self.relative_reference_strategy,
            "n_tickers": len(self._tickers),
            "n_days": self._num_days,
            "real_data_end_date": self.real_data_end_date.isoformat() if self.real_data_end_date else None,
        }

    def render(self) -> None:
        if self.render_mode == "human":
            print(
                f"Day {self._day:4d} | NAV {self._nav:8.2f} | "
                f"Pos {len(self._positions)} | "
                f"Gross {sum(abs(v) for v in self._positions.values()):.2f}"
            )
