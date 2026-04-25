"""Base agent wrapper: combines Actor-Critic + optional DQN into a unified interface."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Dict, Optional

import numpy as np
import torch

from agents.actor_critic import ActorCriticNetwork
from agents.dqn_head import DQNHead
from agents.ppo_trainer import PPOTrainer, TrajectoryBatch
from agents.replay_buffer import ReplayBuffer


class AgentType(Enum):
    ACTOR_CRITIC = "actor_critic"
    DQN = "dqn"
    HYBRID = "hybrid"  # Uses AC for policy, DQN for value backup


class BaseAgent:
    """Unified agent wrapper with fitness tracking and evolution support."""

    def __init__(
        self,
        agent_type: AgentType = AgentType.ACTOR_CRITIC,
        obs_dim: int = 57,
        n_actions: int = 5,
        hidden_sizes: list[int] | None = None,
        activation: str = "relu",
        use_attention: bool = True,
        agent_id: str | None = None,
        # PPO params
        lr: float = 1e-3,
        clip_epsilon: float = 0.20,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        ppo_epochs: int = 4,
        minibatch_size: int = 32,
        entropy_coeff: float = 0.01,
        value_loss_coeff: float = 0.5,
        # DQN params
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay_steps: int = 10000,
        replay_buffer_size: int = 50000,
        target_update_freq: int = 100,
    ):
        self.agent_id = agent_id or str(uuid.uuid4())[:8]
        self.agent_type = agent_type
        self.obs_dim = obs_dim
        self.n_actions = n_actions
        self.hidden_sizes = hidden_sizes or [256, 128, 64]
        self.activation = activation
        self.use_attention = use_attention

        # Actor-Critic (used by AC and HYBRID)
        self.ac_network: Optional[ActorCriticNetwork] = None
        self.ppo_trainer: Optional[PPOTrainer] = None

        # DQN (used by DQN and HYBRID)
        self.dqn_head: Optional[DQNHead] = None
        self.replay_buffer: Optional[ReplayBuffer] = None

        # DQN epsilon schedule
        self._epsilon = epsilon_start
        self._epsilon_start = epsilon_start
        self._epsilon_end = epsilon_end
        self._epsilon_decay_steps = epsilon_decay_steps
        self._target_update_freq = target_update_freq
        self._step_count = 0

        # Fitness tracking
        self.fitness: float = 0.0
        self.fitness_history: list[float] = []
        self.generation: int = 0

        # Trajectory buffer for PPO
        self.trajectory = TrajectoryBatch()

        # Build networks
        hs = hidden_sizes or [256, 128, 64]
        if agent_type in (AgentType.ACTOR_CRITIC, AgentType.HYBRID):
            self.ac_network = ActorCriticNetwork(
                obs_dim,
                n_actions,
                hs,
                activation,
                use_attention=use_attention,
            )
            self.ppo_trainer = PPOTrainer(
                self.ac_network,
                lr=lr,
                clip_epsilon=clip_epsilon,
                gamma=gamma,
                gae_lambda=gae_lambda,
                ppo_epochs=ppo_epochs,
                minibatch_size=minibatch_size,
                entropy_coeff=entropy_coeff,
                value_loss_coeff=value_loss_coeff,
            )

        if agent_type in (AgentType.DQN, AgentType.HYBRID):
            self.dqn_head = DQNHead(obs_dim, n_actions, hs, activation)
            self.replay_buffer = ReplayBuffer(replay_buffer_size)

    def select_action(self, state: np.ndarray, training: bool = True) -> int:
        """Select action based on agent type."""
        state_t = torch.FloatTensor(state).unsqueeze(0)

        if self.agent_type == AgentType.DQN:
            assert self.dqn_head is not None
            eps = self._epsilon if training else 0.0
            return self.dqn_head.select_action(state_t, eps)

        # Actor-Critic or Hybrid
        assert self.ac_network is not None
        if training:
            with torch.no_grad():
                action, log_prob, _, value = self.ac_network.get_action_and_value(
                    state_t
                )
            return action.item()
        else:
            with torch.no_grad():
                probs = self.ac_network.get_policy(state_t)
            return probs.argmax(dim=-1).item()

    def store_transition(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        """Store transition for training."""
        if self.agent_type in (AgentType.ACTOR_CRITIC, AgentType.HYBRID):
            assert self.ac_network is not None
            state_t = torch.FloatTensor(state).unsqueeze(0)
            with torch.no_grad():
                logits, value = self.ac_network(state_t)
                dist = torch.distributions.Categorical(logits=logits)
                log_prob = dist.log_prob(torch.tensor([action]))
            self.trajectory.append(
                state=state,
                action=action,
                reward=reward,
                value=value.item(),
                log_prob=log_prob.item(),
                done=done,
            )

        if self.agent_type in (AgentType.DQN, AgentType.HYBRID):
            assert self.replay_buffer is not None
            self.replay_buffer.push(state, action, reward, next_state, done)

    def train_step(self) -> Dict[str, float]:
        """Run one training step (PPO update or DQN batch)."""
        metrics: Dict[str, float] = {}

        if self.agent_type in (AgentType.ACTOR_CRITIC, AgentType.HYBRID):
            if len(self.trajectory) > 0:
                assert self.ppo_trainer is not None
                metrics.update(self.ppo_trainer.update(self.trajectory))
                self.trajectory = TrajectoryBatch()

        if self.agent_type in (AgentType.DQN, AgentType.HYBRID):
            assert self.dqn_head is not None
            assert self.replay_buffer is not None
            if len(self.replay_buffer) >= 32:
                metrics.update(self._dqn_train_step())

        self._step_count += 1
        self._update_epsilon()
        return metrics

    def _dqn_train_step(self) -> Dict[str, float]:
        """Single DQN training step."""
        assert self.dqn_head is not None
        assert self.replay_buffer is not None

        batch = self.replay_buffer.sample(32)
        q_values = self.dqn_head(batch["states"])
        q_selected = q_values.gather(1, batch["actions"].unsqueeze(1)).squeeze(1)

        with torch.no_grad():
            next_q = self.dqn_head.get_target_q(batch["next_states"])
            next_q_max = next_q.max(dim=1)[0]
            target = batch["rewards"] + 0.99 * next_q_max * (1 - batch["dones"])

        loss = torch.nn.functional.mse_loss(q_selected, target)

        optimizer = torch.optim.Adam(self.dqn_head.q_net.parameters(), lr=1e-3)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if self._step_count % self._target_update_freq == 0:
            self.dqn_head.update_target()

        return {"dqn_loss": loss.item()}

    def _update_epsilon(self) -> None:
        frac = min(1.0, self._step_count / max(1, self._epsilon_decay_steps))
        self._epsilon = self._epsilon_start + frac * (
            self._epsilon_end - self._epsilon_start
        )

    def update_fitness(self, reward: float) -> None:
        """Record episode fitness."""
        self.fitness = reward
        self.fitness_history.append(reward)

    def get_param_vector(self) -> torch.Tensor:
        """Get flat parameter vector for evolution."""
        if self.ac_network is not None:
            return self.ac_network.param_vector()
        if self.dqn_head is not None:
            return self.dqn_head.param_vector()
        raise RuntimeError("No network to get params from")

    def set_param_vector(self, vec: torch.Tensor) -> None:
        """Set parameters from flat vector (for evolution)."""
        if self.ac_network is not None:
            self.ac_network.load_param_vector(vec)
        if self.dqn_head is not None:
            self.dqn_head.load_param_vector(vec)

    def clone(self, new_id: str | None = None) -> "BaseAgent":
        """Create a copy of this agent with the same weights."""
        new_agent = BaseAgent(
            agent_type=self.agent_type,
            obs_dim=self.obs_dim,
            n_actions=self.n_actions,
            hidden_sizes=self.hidden_sizes,
            activation=self.activation,
            use_attention=self.use_attention,
            agent_id=new_id,
        )
        new_agent.set_param_vector(self.get_param_vector().clone())
        new_agent.generation = self.generation
        return new_agent
