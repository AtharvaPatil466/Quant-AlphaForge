"""Actor-Critic network: shared trunk with actor (policy) and critic (value) heads.

Includes optional multi-head attention over per-ticker features for
cross-ticker relationship modeling.
"""

from __future__ import annotations

from typing import List, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class TickerAttention(nn.Module):
    """Multi-head self-attention over per-ticker feature blocks.

    The 57-dim obs has 10 ticker blocks of 4 features each (dims 15-54).
    This module applies self-attention across the 10 ticker slots so the
    network can learn cross-ticker relationships (e.g., sector rotation,
    relative momentum).
    """

    def __init__(
        self,
        n_tickers: int = 10,
        ticker_dim: int = 4,
        n_heads: int = 2,
        embed_dim: int = 16,
    ):
        super().__init__()
        self.n_tickers = n_tickers
        self.ticker_dim = ticker_dim
        self.embed_dim = embed_dim

        # Project each ticker's 4 features into embed_dim
        self.input_proj = nn.Linear(ticker_dim, embed_dim)
        self.attn = nn.MultiheadAttention(
            embed_dim=embed_dim,
            num_heads=n_heads,
            batch_first=True,
        )
        self.layer_norm = nn.LayerNorm(embed_dim)
        self.output_dim = n_tickers * embed_dim

    def forward(self, ticker_features: torch.Tensor) -> torch.Tensor:
        """Apply attention over ticker features.

        Args:
            ticker_features: (batch, n_tickers * ticker_dim) flat tensor

        Returns:
            (batch, n_tickers * embed_dim) attended features
        """
        batch_size = ticker_features.shape[0]
        # Reshape to (batch, n_tickers, ticker_dim)
        x = ticker_features.view(batch_size, self.n_tickers, self.ticker_dim)
        # Project to embed_dim
        x = self.input_proj(x)  # (batch, n_tickers, embed_dim)
        # Self-attention
        attn_out, _ = self.attn(x, x, x)
        x = self.layer_norm(x + attn_out)  # residual connection
        # Flatten back
        return x.view(batch_size, -1)


class ActorCriticNetwork(nn.Module):
    """Shared-trunk Actor-Critic with optional ticker attention.

    Architecture:
        Portfolio+regime features (15d) ─┐
        Ticker features (40d) → Attention ─┤→ concat → trunk → actor_head
        Time features (2d) ──────────────┘              → critic_head
    """

    def __init__(
        self,
        obs_dim: int = 57,
        n_actions: int = 5,
        hidden_sizes: List[int] | None = None,
        activation: str = "relu",
        use_attention: bool = True,
    ):
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = [256, 128, 64]

        self.obs_dim = obs_dim
        self.use_attention = use_attention and obs_dim >= 57

        act_fn = {"relu": nn.ReLU, "tanh": nn.Tanh, "elu": nn.ELU}.get(
            activation, nn.ReLU
        )

        # Ticker attention (dims 15-54 = 40 dims = 10 tickers × 4 features)
        if self.use_attention:
            self.ticker_attn = TickerAttention(
                n_tickers=10, ticker_dim=4, n_heads=2, embed_dim=16
            )
            # trunk input: 15 (portfolio+regime) + 160 (10*16 attended) + 2 (time)
            trunk_in = 15 + self.ticker_attn.output_dim + 2
        else:
            trunk_in = obs_dim

        # Shared trunk
        layers: list[nn.Module] = []
        in_dim = trunk_in
        for h in hidden_sizes:
            layers.append(nn.Linear(in_dim, h))
            layers.append(act_fn())
            in_dim = h
        self.trunk = nn.Sequential(*layers)

        # Actor head: outputs logits for each action
        self.actor_head = nn.Linear(in_dim, n_actions)

        # Critic head: outputs scalar state value
        self.critic_head = nn.Linear(in_dim, 1)

        self._init_weights()

    def _init_weights(self) -> None:
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=0.01)
                nn.init.zeros_(m.bias)

    def _process_obs(self, x: torch.Tensor) -> torch.Tensor:
        """Split observation and apply attention to ticker features."""
        if not self.use_attention:
            return x

        # Split: [0:15] portfolio+regime, [15:55] tickers, [55:57] time
        if x.dim() == 1:
            x = x.unsqueeze(0)
        port_regime = x[:, :15]
        ticker_raw = x[:, 15:55]
        time_feats = x[:, 55:57]

        ticker_attended = self.ticker_attn(ticker_raw)
        return torch.cat([port_regime, ticker_attended, time_feats], dim=-1)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Returns (action_logits, state_value)."""
        processed = self._process_obs(x)
        features = self.trunk(processed)
        logits = self.actor_head(features)
        value = self.critic_head(features).squeeze(-1)
        return logits, value

    def get_action_and_value(
        self, x: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Sample action, return (action, log_prob, entropy, value)."""
        logits, value = self.forward(x)
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()
        return action, dist.log_prob(action), dist.entropy(), value

    def evaluate_actions(
        self, x: torch.Tensor, actions: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Evaluate given actions, return (log_prob, entropy, value)."""
        logits, value = self.forward(x)
        dist = torch.distributions.Categorical(logits=logits)
        return dist.log_prob(actions), dist.entropy(), value

    def get_policy(self, x: torch.Tensor) -> torch.Tensor:
        """Return action probabilities."""
        logits, _ = self.forward(x)
        return F.softmax(logits, dim=-1)

    def param_vector(self) -> torch.Tensor:
        """Flatten all parameters into a single 1D tensor."""
        return torch.cat([p.data.view(-1) for p in self.parameters()])

    def load_param_vector(self, vec: torch.Tensor) -> None:
        """Load parameters from a flat 1D tensor."""
        offset = 0
        for p in self.parameters():
            n = p.numel()
            p.data.copy_(vec[offset : offset + n].view(p.shape))
            offset += n

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())
