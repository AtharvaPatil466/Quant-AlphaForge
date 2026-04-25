"""DQN head: reuses Actor-Critic trunk, outputs Q-values per action."""

from __future__ import annotations

import copy
from typing import List

import torch
import torch.nn as nn


class DQNHead(nn.Module):
    """DQN that shares the Actor-Critic trunk architecture.

    Architecture:
        obs_dim → hidden[0] → hidden[1] → hidden[2] → Q-values (n_actions)

    Includes target network for stable Q-learning.
    """

    def __init__(
        self,
        obs_dim: int = 57,
        n_actions: int = 5,
        hidden_sizes: List[int] | None = None,
        activation: str = "relu",
    ):
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = [256, 128, 64]

        act_fn = {"relu": nn.ReLU, "tanh": nn.Tanh, "elu": nn.ELU}.get(
            activation, nn.ReLU
        )

        # Q-network
        layers: list[nn.Module] = []
        in_dim = obs_dim
        for h in hidden_sizes:
            layers.append(nn.Linear(in_dim, h))
            layers.append(act_fn())
            in_dim = h
        layers.append(nn.Linear(in_dim, n_actions))
        self.q_net = nn.Sequential(*layers)

        # Target network (frozen copy)
        self.target_net = copy.deepcopy(self.q_net)
        for p in self.target_net.parameters():
            p.requires_grad = False

        self.n_actions = n_actions
        self._init_weights()

    def _init_weights(self) -> None:
        for m in self.q_net.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=0.01)
                nn.init.zeros_(m.bias)
        self.update_target()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Return Q-values for all actions."""
        return self.q_net(x)

    def get_target_q(self, x: torch.Tensor) -> torch.Tensor:
        """Return Q-values from target network."""
        with torch.no_grad():
            return self.target_net(x)

    def update_target(self) -> None:
        """Hard copy Q-network weights to target network."""
        self.target_net.load_state_dict(self.q_net.state_dict())

    def select_action(
        self, x: torch.Tensor, epsilon: float = 0.0
    ) -> int:
        """Epsilon-greedy action selection."""
        if torch.rand(1).item() < epsilon:
            return int(torch.randint(0, self.n_actions, (1,)).item())
        with torch.no_grad():
            q = self.forward(x)
            return int(q.argmax(dim=-1).item())

    def param_vector(self) -> torch.Tensor:
        """Flatten Q-network parameters into a single 1D tensor."""
        return torch.cat([p.data.view(-1) for p in self.q_net.parameters()])

    def load_param_vector(self, vec: torch.Tensor) -> None:
        """Load Q-network parameters from a flat 1D tensor."""
        offset = 0
        for p in self.q_net.parameters():
            n = p.numel()
            p.data.copy_(vec[offset : offset + n].view(p.shape))
            offset += n

    def n_params(self) -> int:
        return sum(p.numel() for p in self.q_net.parameters())
