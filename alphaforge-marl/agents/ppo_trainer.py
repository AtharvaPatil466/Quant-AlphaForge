"""PPO trainer with GAE for the Actor-Critic network."""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import torch
import torch.nn as nn

from agents.actor_critic import ActorCriticNetwork


class TrajectoryBatch:
    """Stores a batch of trajectory data for PPO updates."""

    def __init__(self) -> None:
        self.states: List[np.ndarray] = []
        self.actions: List[int] = []
        self.rewards: List[float] = []
        self.values: List[float] = []
        self.log_probs: List[float] = []
        self.dones: List[bool] = []

    def append(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        value: float,
        log_prob: float,
        done: bool,
    ) -> None:
        self.states.append(state)
        self.actions.append(action)
        self.rewards.append(reward)
        self.values.append(value)
        self.log_probs.append(log_prob)
        self.dones.append(done)

    def __len__(self) -> int:
        return len(self.states)


def compute_gae(
    rewards: List[float],
    values: List[float],
    dones: List[bool],
    last_value: float,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute Generalized Advantage Estimation.

    Returns:
        (advantages, returns) as tensors.
    """
    n = len(rewards)
    advantages = torch.zeros(n)
    last_gae = 0.0

    for t in reversed(range(n)):
        next_val = last_value if t == n - 1 else values[t + 1]
        next_non_terminal = 0.0 if dones[t] else 1.0
        delta = rewards[t] + gamma * next_val * next_non_terminal - values[t]
        last_gae = delta + gamma * gae_lambda * next_non_terminal * last_gae
        advantages[t] = last_gae

    returns = advantages + torch.FloatTensor(values)
    return advantages, returns


class RunningMeanStd:
    """Online running mean/variance tracker for reward normalization."""

    def __init__(self) -> None:
        self.mean: float = 0.0
        self.var: float = 1.0
        self.count: int = 0

    def update(self, x: np.ndarray) -> None:
        batch_mean = float(np.mean(x))
        batch_var = float(np.var(x))
        batch_count = len(x)
        self._update(batch_mean, batch_var, batch_count)

    def _update(self, batch_mean: float, batch_var: float, batch_count: int) -> None:
        total = self.count + batch_count
        if total == 0:
            return
        delta = batch_mean - self.mean
        new_mean = self.mean + delta * batch_count / total
        m_a = self.var * self.count
        m_b = batch_var * batch_count
        m2 = m_a + m_b + delta ** 2 * self.count * batch_count / total
        self.mean = new_mean
        self.var = m2 / total if total > 0 else 1.0
        self.count = total

    def normalize(self, x: np.ndarray) -> np.ndarray:
        std = max(np.sqrt(self.var), 1e-8)
        return (x - self.mean) / std


class PPOTrainer:
    """Proximal Policy Optimization trainer for Actor-Critic networks."""

    def __init__(
        self,
        network: ActorCriticNetwork,
        lr: float = 1e-3,
        clip_epsilon: float = 0.20,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        ppo_epochs: int = 4,
        minibatch_size: int = 32,
        entropy_coeff: float = 0.01,
        value_loss_coeff: float = 0.5,
        max_grad_norm: float = 0.5,
    ):
        self.network = network
        self.optimizer = torch.optim.Adam(network.parameters(), lr=lr)
        self.clip_epsilon = clip_epsilon
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.ppo_epochs = ppo_epochs
        self.minibatch_size = minibatch_size
        self.entropy_coeff = entropy_coeff
        self.value_loss_coeff = value_loss_coeff
        self.max_grad_norm = max_grad_norm
        self.reward_normalizer = RunningMeanStd()

    def update(self, batch: TrajectoryBatch) -> Dict[str, float]:
        """Run PPO update on a trajectory batch.

        Returns dict of loss metrics.
        """
        if len(batch) < 2:
            return {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}

        states = torch.FloatTensor(np.array(batch.states))
        actions = torch.LongTensor(batch.actions)
        old_log_probs = torch.FloatTensor(batch.log_probs)

        # Normalize rewards
        raw_rewards = np.array(batch.rewards)
        self.reward_normalizer.update(raw_rewards)
        normalized_rewards = self.reward_normalizer.normalize(raw_rewards).tolist()

        # Compute last value for GAE
        with torch.no_grad():
            _, last_value = self.network(states[-1:])
            last_value = last_value.item()

        advantages, returns = compute_gae(
            normalized_rewards,
            batch.values,
            batch.dones,
            last_value,
            self.gamma,
            self.gae_lambda,
        )

        # Normalize advantages
        if advantages.std() > 1e-8:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        # PPO epochs
        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        n_updates = 0

        n = len(batch)
        indices = np.arange(n)

        for _ in range(self.ppo_epochs):
            np.random.shuffle(indices)
            for start in range(0, n, self.minibatch_size):
                end = min(start + self.minibatch_size, n)
                mb_idx = indices[start:end]

                mb_states = states[mb_idx]
                mb_actions = actions[mb_idx]
                mb_old_log_probs = old_log_probs[mb_idx]
                mb_advantages = advantages[mb_idx]
                mb_returns = returns[mb_idx]

                new_log_probs, entropy, values = self.network.evaluate_actions(
                    mb_states, mb_actions
                )

                # Policy loss (clipped surrogate)
                ratio = torch.exp(new_log_probs - mb_old_log_probs)
                surr1 = ratio * mb_advantages
                surr2 = torch.clamp(
                    ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon
                ) * mb_advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss
                value_loss = nn.functional.mse_loss(values, mb_returns)

                # Total loss
                loss = (
                    policy_loss
                    + self.value_loss_coeff * value_loss
                    - self.entropy_coeff * entropy.mean()
                )

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(
                    self.network.parameters(), self.max_grad_norm
                )
                self.optimizer.step()

                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy += entropy.mean().item()
                n_updates += 1

        n_updates = max(1, n_updates)
        return {
            "policy_loss": total_policy_loss / n_updates,
            "value_loss": total_value_loss / n_updates,
            "entropy": total_entropy / n_updates,
        }
