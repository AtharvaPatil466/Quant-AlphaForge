"""Runs a single episode through the TradingEnv and stores the trajectory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, TYPE_CHECKING

import numpy as np
import torch

from env.trading_env import TradingEnv

if TYPE_CHECKING:
    from agents.base_agent import BaseAgent


@dataclass
class Transition:
    """Single (s, a, r, s', done) tuple."""
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


@dataclass
class EpisodeResult:
    """Full episode trajectory plus summary stats."""
    trajectory: List[Transition] = field(default_factory=list)
    total_reward: float = 0.0
    final_nav: float = 100.0
    episode_length: int = 0
    terminated: bool = False
    truncated: bool = False


def run_episode(
    env: TradingEnv,
    policy: Callable[[np.ndarray], int],
    seed: Optional[int] = None,
) -> EpisodeResult:
    """Run one full episode using the given policy function."""
    state, info = env.reset(seed=seed)
    result = EpisodeResult()

    done = False
    while not done:
        action = policy(state)
        next_state, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated

        result.trajectory.append(Transition(
            state=state.copy(),
            action=action,
            reward=reward,
            next_state=next_state.copy(),
            done=done,
        ))

        result.total_reward += reward
        state = next_state

    result.final_nav = info.get("nav", 100.0)
    result.episode_length = len(result.trajectory)
    result.terminated = terminated
    result.truncated = truncated

    return result


def run_episode_with_ppo(
    env: TradingEnv,
    agent: "BaseAgent",
    seed: Optional[int] = None,
) -> EpisodeResult:
    """Run episode storing PPO trajectory data (log_prob, value) in the agent."""
    state, info = env.reset(seed=seed)
    result = EpisodeResult()

    done = False
    while not done:
        state_t = torch.FloatTensor(state).unsqueeze(0)

        if agent.ac_network is not None:
            with torch.no_grad():
                action_t, log_prob, _, value = agent.ac_network.get_action_and_value(state_t)
            action = action_t.item()
            # Store in agent's PPO trajectory
            next_state, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            agent.trajectory.append(
                state=state,
                action=action,
                reward=reward,
                value=value.item(),
                log_prob=log_prob.item(),
                done=done,
            )
        else:
            action = agent.select_action(state, training=False)
            next_state, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

        result.trajectory.append(Transition(
            state=state.copy(),
            action=action,
            reward=reward,
            next_state=next_state.copy(),
            done=done,
        ))

        result.total_reward += reward
        state = next_state

    result.final_nav = info.get("nav", 100.0)
    result.episode_length = len(result.trajectory)
    result.terminated = terminated
    result.truncated = truncated

    return result


def random_policy(state: np.ndarray) -> int:
    """Uniform random action selection."""
    return int(np.random.randint(0, 5))
