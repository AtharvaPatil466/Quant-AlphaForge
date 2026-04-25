"""Continuous Actor-Critic: outputs per-ticker portfolio weights directly.

Instead of 5 discrete actions (HOLD, LONG_STRONG, etc.), this network
outputs a continuous weight vector for the top-N and bottom-N tickers,
allowing nuanced position sizing.
"""

from __future__ import annotations

from typing import List, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class ContinuousActorCritic(nn.Module):
    """Actor-Critic that outputs continuous portfolio weights.

    Actor head outputs a mean and log_std for a diagonal Gaussian over
    N_TICKERS weight dimensions. The weights are squashed through tanh
    to bound them in [-max_weight, +max_weight].

    Architecture:
        obs_dim → trunk → actor (mean + log_std for N weights)
                       → critic (scalar value)
    """

    N_WEIGHTS = 10  # Top 5 long + top 5 short candidates

    def __init__(
        self,
        obs_dim: int = 57,
        hidden_sizes: List[int] | None = None,
        activation: str = "relu",
        max_weight: float = 0.05,
    ):
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = [256, 128, 64]

        self.max_weight = max_weight
        self.n_weights = self.N_WEIGHTS

        act_fn = {"relu": nn.ReLU, "tanh": nn.Tanh, "elu": nn.ELU}.get(
            activation, nn.ReLU
        )

        # Shared trunk
        layers: list[nn.Module] = []
        in_dim = obs_dim
        for h in hidden_sizes:
            layers.append(nn.Linear(in_dim, h))
            layers.append(act_fn())
            in_dim = h
        self.trunk = nn.Sequential(*layers)

        # Actor: mean and log_std for Gaussian policy over weights
        self.mean_head = nn.Linear(in_dim, self.n_weights)
        self.log_std_head = nn.Linear(in_dim, self.n_weights)

        # Critic
        self.critic_head = nn.Linear(in_dim, 1)

        self._init_weights()

    def _init_weights(self) -> None:
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=0.01)
                nn.init.zeros_(m.bias)

    def forward(
        self, x: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Returns (weight_means, weight_log_stds, state_value)."""
        features = self.trunk(x)
        mean = self.mean_head(features)
        log_std = self.log_std_head(features).clamp(-5.0, 2.0)
        value = self.critic_head(features).squeeze(-1)
        return mean, log_std, value

    def get_action_and_value(
        self, x: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Sample continuous weights, return (weights, log_prob, entropy, value).

        Weights are squashed through tanh * max_weight.
        """
        mean, log_std, value = self.forward(x)
        std = log_std.exp()
        dist = torch.distributions.Normal(mean, std)
        raw_action = dist.rsample()

        # Squash to [-max_weight, max_weight]
        weights = torch.tanh(raw_action) * self.max_weight

        # Log prob with tanh correction
        log_prob = dist.log_prob(raw_action)
        log_prob -= torch.log(1 - torch.tanh(raw_action).pow(2) + 1e-6)
        log_prob = log_prob.sum(dim=-1)

        entropy = dist.entropy().sum(dim=-1)

        return weights, log_prob, entropy, value

    def evaluate_actions(
        self, x: torch.Tensor, actions: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Evaluate given continuous actions, return (log_prob, entropy, value).

        actions should be the raw (pre-tanh) values.
        """
        mean, log_std, value = self.forward(x)
        std = log_std.exp()
        dist = torch.distributions.Normal(mean, std)

        log_prob = dist.log_prob(actions)
        log_prob -= torch.log(1 - torch.tanh(actions).pow(2) + 1e-6)
        log_prob = log_prob.sum(dim=-1)

        entropy = dist.entropy().sum(dim=-1)

        return log_prob, entropy, value

    def get_weights(self, x: torch.Tensor) -> torch.Tensor:
        """Deterministic weight prediction (for deployment)."""
        mean, _, _ = self.forward(x)
        return torch.tanh(mean) * self.max_weight

    def param_vector(self) -> torch.Tensor:
        return torch.cat([p.data.view(-1) for p in self.parameters()])

    def load_param_vector(self, vec: torch.Tensor) -> None:
        offset = 0
        for p in self.parameters():
            n = p.numel()
            p.data.copy_(vec[offset: offset + n].view(p.shape))
            offset += n

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())
