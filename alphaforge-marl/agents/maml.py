"""MAML (Model-Agnostic Meta-Learning) for fast regime adaptation.

Instead of training a single policy, MAML finds an initialization that
can quickly adapt to any market regime with just a few gradient steps.
At deployment, the agent takes K inner-loop gradient steps on recent
data to specialize for the current regime.
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

from agents.actor_critic import ActorCriticNetwork
from agents.ppo_trainer import TrajectoryBatch, compute_gae


class MAMLTrainer:
    """MAML wrapper for Actor-Critic networks.

    Outer loop: find good initialization across tasks (market regimes).
    Inner loop: K gradient steps to adapt to a specific regime.

    This is a first-order MAML (FOMAML) for efficiency — uses stop-gradient
    on the inner loop to avoid computing second-order derivatives.
    """

    def __init__(
        self,
        network: ActorCriticNetwork,
        inner_lr: float = 0.01,
        outer_lr: float = 1e-3,
        inner_steps: int = 3,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_epsilon: float = 0.20,
        entropy_coeff: float = 0.01,
        value_loss_coeff: float = 0.5,
    ):
        self.network = network
        self.inner_lr = inner_lr
        self.outer_lr = outer_lr
        self.inner_steps = inner_steps
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_epsilon = clip_epsilon
        self.entropy_coeff = entropy_coeff
        self.value_loss_coeff = value_loss_coeff

        self.meta_optimizer = torch.optim.Adam(network.parameters(), lr=outer_lr)

    def _compute_policy_loss(
        self,
        network: ActorCriticNetwork,
        batch: TrajectoryBatch,
    ) -> torch.Tensor:
        """Compute PPO-style loss for a trajectory batch."""
        if len(batch) < 2:
            return torch.tensor(0.0)

        states = torch.FloatTensor(np.array(batch.states))
        actions = torch.LongTensor(batch.actions)
        old_log_probs = torch.FloatTensor(batch.log_probs)

        with torch.no_grad():
            _, last_value = network(states[-1:])
            last_value = last_value.item()

        advantages, returns = compute_gae(
            batch.rewards, batch.values, batch.dones,
            last_value, self.gamma, self.gae_lambda,
        )
        if advantages.std() > 1e-8:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        new_log_probs, entropy, values = network.evaluate_actions(states, actions)

        ratio = torch.exp(new_log_probs - old_log_probs)
        surr1 = ratio * advantages
        surr2 = torch.clamp(ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon) * advantages
        policy_loss = -torch.min(surr1, surr2).mean()
        value_loss = nn.functional.mse_loss(values, returns)
        loss = policy_loss + self.value_loss_coeff * value_loss - self.entropy_coeff * entropy.mean()
        return loss

    def inner_adapt(
        self,
        support_batch: TrajectoryBatch,
    ) -> ActorCriticNetwork:
        """Inner loop: adapt network to a specific task/regime.

        Creates a copy and takes K gradient steps on the support set.
        Uses FOMAML (first-order) — no second derivatives.
        """
        adapted = copy.deepcopy(self.network)
        inner_opt = torch.optim.SGD(adapted.parameters(), lr=self.inner_lr)

        for _ in range(self.inner_steps):
            loss = self._compute_policy_loss(adapted, support_batch)
            inner_opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(adapted.parameters(), 0.5)
            inner_opt.step()

        return adapted

    def meta_update(
        self,
        task_batches: List[Tuple[TrajectoryBatch, TrajectoryBatch]],
    ) -> Dict[str, float]:
        """Outer loop: update meta-parameters across multiple tasks.

        Args:
            task_batches: List of (support_batch, query_batch) per task.
                         Support is used for inner adaptation, query for
                         evaluating the adapted model.

        Returns:
            Dict of loss metrics.
        """
        if not task_batches:
            return {"meta_loss": 0.0}

        meta_loss = torch.tensor(0.0)
        n_tasks = 0

        for support, query in task_batches:
            if len(support) < 2 or len(query) < 2:
                continue

            # Inner adapt on support
            adapted = self.inner_adapt(support)

            # Evaluate adapted model on query (this is FOMAML: no second-order)
            # Copy adapted params back to main network temporarily for gradient flow
            original_params = [p.data.clone() for p in self.network.parameters()]
            for p_main, p_adapted in zip(self.network.parameters(), adapted.parameters()):
                p_main.data.copy_(p_adapted.data)

            query_loss = self._compute_policy_loss(self.network, query)
            meta_loss = meta_loss + query_loss

            # Restore original params (gradients are accumulated)
            for p_main, orig in zip(self.network.parameters(), original_params):
                p_main.data.copy_(orig)

            n_tasks += 1

        if n_tasks == 0:
            return {"meta_loss": 0.0}

        meta_loss = meta_loss / n_tasks

        self.meta_optimizer.zero_grad()
        meta_loss.backward()
        nn.utils.clip_grad_norm_(self.network.parameters(), 0.5)
        self.meta_optimizer.step()

        return {"meta_loss": meta_loss.item()}

    def adapt_for_deployment(
        self,
        recent_trajectory: TrajectoryBatch,
    ) -> ActorCriticNetwork:
        """Adapt the meta-learned model for deployment on current regime.

        Takes a few gradient steps on recent market data to specialize.
        """
        return self.inner_adapt(recent_trajectory)
