"""MARL ensemble strategy — pure inference wrapper for live trading.

Loads a deployment checkpoint, constructs the 57-dim observation from live
market data, runs the Pareto ensemble forward pass, and returns target weights.

No training logic, no evolution, no mutation. Pure inference.
"""

from __future__ import annotations

import logging
import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import sys
import torch

# Add alphaforge-marl and alphaforge-python to path for shared modules
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MARL_DIR = os.path.join(_PROJECT_ROOT, "alphaforge-marl")
_PYTHON_DIR = os.path.join(_PROJECT_ROOT, "alphaforge-python")

# Temporarily hide the execution layer's 'data' package
_exec_data = sys.modules.pop("data", None)

sys.path.insert(0, _MARL_DIR)
sys.path.insert(0, _PYTHON_DIR)

# Now these resolve to alphaforge-python/data and alphaforge-marl/env
from data.synthetic import PriceSeries, safe_div
from factors.scoring import compute_factor_scores_js
from agents.actor_critic import ActorCriticNetwork
from env.action_space import Action, ACTION_POSITION
from env.state_builder import build_state, rolling_signal_score

# Restore the execution layer's 'data' package so downstream code isn't broken
if _exec_data is not None:
    sys.modules["data"] = _exec_data

# Local strategy imports
from strategy.momentum import Signal, TargetPortfolio
from strategy.marl_logger import log_marl_decision

logger = logging.getLogger(__name__)


@dataclass
class _EnsembleState:
    """Module-level singleton holding loaded checkpoint state."""
    networks: List[ActorCriticNetwork]
    agent_ids: List[str]
    fitnesses: List[float]
    network_config: Dict[str, Any]
    obs_buffer: List[np.ndarray]  # Rolling buffer for observation normalization
    nav_history: List[float]      # Track NAV across trading days
    positions: Dict[str, float]   # Current position weights
    days_since_rebalance: int
    checkpoint_path: str


_state: Optional[_EnsembleState] = None


def _load_checkpoint(checkpoint_path: str) -> _EnsembleState:
    """Load deployment checkpoint and reconstruct agent networks."""
    global _state
    if _state is not None and _state.checkpoint_path == checkpoint_path:
        return _state

    logger.info(f"Loading MARL deployment checkpoint: {checkpoint_path}")
    ckpt = torch.load(checkpoint_path, weights_only=False)

    version = ckpt.get("version", "unknown")
    net_cfg = ckpt["network_config"]
    agents_data = ckpt["agents"]

    networks = []
    agent_ids = []
    fitnesses = []

    for agent_data in agents_data:
        net = ActorCriticNetwork(
            obs_dim=net_cfg["obs_dim"],
            n_actions=net_cfg["n_actions"],
            hidden_sizes=net_cfg["hidden_sizes"],
            activation=net_cfg.get("activation", "relu"),
            use_attention=net_cfg.get("use_attention", False),
        )
        params = torch.FloatTensor(agent_data["params"])
        net.load_param_vector(params)
        net.eval()
        networks.append(net)
        agent_ids.append(agent_data["agent_id"])
        fitnesses.append(agent_data.get("fitness", 0.0))

    logger.info(
        f"Loaded {len(networks)} agents | "
        f"Network: {net_cfg['hidden_sizes']} attn={net_cfg.get('use_attention', False)} | "
        f"Version: {version}"
    )

    _state = _EnsembleState(
        networks=networks,
        agent_ids=agent_ids,
        fitnesses=fitnesses,
        network_config=net_cfg,
        obs_buffer=[],
        nav_history=[100.0],
        positions={},
        days_since_rebalance=0,
        checkpoint_path=checkpoint_path,
    )
    return _state


def _ohlcv_to_dataset(history: Dict[str, pd.DataFrame]) -> Dict[str, PriceSeries]:
    """Convert execution-system OHLCV DataFrames to PriceSeries for state builder.

    Inline version of env.real_data.ohlcv_to_price_series to avoid pulling in
    data.market.loader and its heavy dependencies.
    """
    dataset: Dict[str, PriceSeries] = {}
    for ticker, df in history.items():
        if df.empty or "Close" not in df.columns:
            continue
        prices = df["Close"].values.astype(np.float64)
        volumes = df["Volume"].values.astype(np.float64) if "Volume" in df.columns else np.ones(len(prices))
        returns = np.zeros(len(prices), dtype=np.float64)
        for i in range(1, len(prices)):
            returns[i] = safe_div(prices[i] - prices[i - 1], max(prices[i - 1], 1e-10), 0.0)
        dataset[ticker] = PriceSeries(
            ticker=ticker,
            name=ticker,
            prices=np.nan_to_num(prices, nan=0.0, posinf=0.0, neginf=0.0),
            volumes=np.nan_to_num(volumes, nan=0.0, posinf=0.0, neginf=0.0),
            returns=np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0),
        )
    return dataset


def _build_index_arrays(
    dataset: Dict[str, PriceSeries],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build equal-weight index returns/volumes/prices from dataset."""
    tickers = list(dataset.keys())
    if not tickers:
        return np.zeros(1), np.ones(1), np.ones(1)

    n_days = len(dataset[tickers[0]].prices)
    all_rets = np.zeros(n_days)
    all_vols = np.zeros(n_days)
    all_prices = np.zeros(n_days)

    for t in tickers:
        all_rets += dataset[t].returns / len(tickers)
        all_vols += dataset[t].volumes / len(tickers)
        all_prices += dataset[t].prices / len(tickers)

    return all_rets, all_vols, all_prices


def _rank_tickers(dataset: Dict[str, PriceSeries], tickers: List[str], day: int) -> List[str]:
    """Rank tickers by rolling composite signal (same as TradingEnv._rank_tickers)."""
    scored = []
    for t in tickers:
        ps = dataset.get(t)
        if ps is None or day < 1:
            scored.append((t, 0.0))
            continue
        composite = rolling_signal_score(ps, day)
        scored.append((t, composite))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored]


def _action_to_weights(
    action: int,
    dataset: Dict[str, PriceSeries],
    tickers: List[str],
    day: int,
    max_position: float = 0.05,
    max_gross_exposure: float = 1.50,
) -> Dict[str, float]:
    """Convert discrete action to portfolio weights (same as TradingEnv._apply_action)."""
    act = Action(action)
    if act == Action.HOLD:
        return {}

    multiplier = ACTION_POSITION[act]
    ranked = _rank_tickers(dataset, tickers, day)
    top5 = ranked[:5]
    bot5 = ranked[-5:] if len(ranked) >= 5 else []

    new_positions: Dict[str, float] = {}
    if multiplier > 0:
        for t in top5:
            new_positions[t] = max_position * abs(multiplier)
    elif multiplier < 0:
        for t in bot5:
            new_positions[t] = -max_position * abs(multiplier)

    gross = sum(abs(v) for v in new_positions.values())
    if gross > max_gross_exposure:
        scale = max_gross_exposure / gross
        new_positions = {t: w * scale for t, w in new_positions.items()}

    return new_positions


def _ensemble_select_action(
    state: _EnsembleState,
    obs: np.ndarray,
) -> tuple[int, List[float], Dict[str, float]]:
    """Run ensemble forward pass — fitness-weighted blend of action distributions.

    Returns (action, action_probs, agent_weights).
    """
    obs_t = torch.FloatTensor(obs).unsqueeze(0)

    # Fitness-weighted blending (simple and robust — no regime bandit for v1)
    total_fitness = sum(max(0.01, f) for f in state.fitnesses)
    agent_weights = {}
    blended = torch.zeros(5)

    for net, aid, fitness in zip(state.networks, state.agent_ids, state.fitnesses):
        w = max(0.01, fitness) / total_fitness
        agent_weights[aid] = w
        with torch.no_grad():
            probs = net.get_policy(obs_t).squeeze(0)
        blended += w * probs

    total = blended.sum()
    if total < 1e-10:
        blended = torch.ones(5) / 5.0
    else:
        blended = blended / total

    action = blended.argmax().item()
    return action, blended.tolist(), agent_weights


def generate_target_weights(
    history: Dict[str, pd.DataFrame],
    checkpoint_path: str | None = None,
    max_position: float = 0.05,
    max_gross_exposure: float = 1.50,
    **kwargs: Any,
) -> TargetPortfolio:
    """Generate target portfolio weights using the trained MARL ensemble.

    Drop-in replacement for strategy.momentum.generate_target_weights().

    Args:
        history: ticker -> DataFrame with OHLCV columns
        checkpoint_path: Path to deployment checkpoint (.pt)
        max_position: Max weight per ticker (default 5%)
        max_gross_exposure: Max total gross exposure

    Returns:
        TargetPortfolio with weights and signals for audit.
    """
    if checkpoint_path is None:
        checkpoint_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "checkpoints", "deploy_v1.pt",
        )

    # Resolve relative to alphaforge-marl if not absolute
    if not os.path.isabs(checkpoint_path):
        checkpoint_path = os.path.join(_MARL_DIR, checkpoint_path)

    state = _load_checkpoint(checkpoint_path)

    # Convert OHLCV to PriceSeries
    dataset = _ohlcv_to_dataset(history)
    tickers = list(dataset.keys())
    if not tickers:
        return TargetPortfolio(weights={}, signals=[], date="")

    # Compute factor scores (for state builder backward compat)
    n_days = len(dataset[tickers[0]].prices)
    lookback = n_days
    scores = compute_factor_scores_js(dataset, lookback)

    # Build index arrays
    index_rets, index_vols, index_prices = _build_index_arrays(dataset)

    # Day index = last day of data
    day = n_days - 1

    # Build 57-dim observation (matching TradingEnv._get_obs exactly)
    raw_obs = build_state(
        day=day,
        episode_length=252,
        nav_history=state.nav_history,
        positions=state.positions,
        cash_ratio=1.0 - sum(abs(v) for v in state.positions.values()),
        index_returns=index_rets,
        index_volumes=index_vols,
        index_prices=index_prices,
        factor_scores=scores,
        tickers=tickers,
        days_since_rebalance=state.days_since_rebalance,
        dataset=dataset,
    )

    # Apply rolling z-normalization (matching TradingEnv, 63-window)
    norm_window = 63
    if state.obs_buffer:
        recent = np.asarray(state.obs_buffer[-norm_window:], dtype=np.float32)
        mean_vec = np.mean(recent, axis=0)
        std_vec = np.std(recent, axis=0)
        std_vec = np.where(std_vec < 1e-6, 1.0, std_vec)
        obs = (raw_obs - mean_vec) / std_vec
    else:
        obs = raw_obs

    state.obs_buffer.append(np.asarray(raw_obs, dtype=np.float32))
    obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    # Ensemble forward pass
    action, action_probs, agent_weights = _ensemble_select_action(state, obs)

    # Convert action to portfolio weights
    weights = _action_to_weights(
        action, dataset, tickers, day, max_position, max_gross_exposure,
    )

    # Update persistent state for next call
    state.positions = weights
    if weights:
        state.days_since_rebalance = 0
    else:
        state.days_since_rebalance += 1

    # Build signals for audit trail (reuse momentum Signal format)
    ranked = _rank_tickers(dataset, tickers, day)
    signals = []
    for rank, ticker in enumerate(ranked):
        ps = dataset.get(ticker)
        if ps is None:
            continue
        d = min(day, len(ps.prices) - 1)
        d5 = max(0, d - 5)
        d21 = max(0, d - 21)
        mom5 = safe_div(ps.prices[d] - ps.prices[d5], max(ps.prices[d5], 1e-10), 0.0)
        mom21 = safe_div(ps.prices[d] - ps.prices[d21], max(ps.prices[d21], 1e-10), 0.0)
        signals.append(Signal(
            ticker=ticker,
            mom_5d=float(mom5),
            mom_21d=float(mom21),
            mean_reversion=0.0,
            composite=rolling_signal_score(ps, d),
            rank=rank + 1,
        ))

    # Extract date
    trade_date = ""
    for df in history.values():
        if not df.empty:
            idx = df.index[-1]
            trade_date = str(idx.date()) if hasattr(idx, "date") else str(idx)
            break

    # Log decision for audit
    action_names = ["HOLD", "LONG_STRONG", "LONG_MILD", "SHORT_STRONG", "SHORT_MILD"]
    log_marl_decision(
        date=trade_date,
        action=action,
        action_name=action_names[action],
        action_probs=action_probs,
        agent_weights=agent_weights,
        target_weights=weights,
        obs_buffer_size=len(state.obs_buffer),
        n_agents=len(state.networks),
    )

    return TargetPortfolio(weights=weights, signals=signals, date=trade_date)
