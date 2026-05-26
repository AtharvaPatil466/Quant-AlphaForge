"""Tests for MARL agents (Phase 1)."""

from __future__ import annotations

import numpy as np
import torch
import pytest

from agents.actor_critic import ActorCriticNetwork
from agents.dqn_head import DQNHead
from agents.replay_buffer import ReplayBuffer
from agents.ppo_trainer import PPOTrainer, TrajectoryBatch, compute_gae
from agents.base_agent import BaseAgent, AgentType
from agents.agent_pool import AgentPool


# ── Actor-Critic ────────────────────────────────────────────────


class TestActorCritic:
    def test_output_shapes(self):
        net = ActorCriticNetwork(obs_dim=57, n_actions=5)
        x = torch.randn(4, 57)
        logits, values = net(x)
        assert logits.shape == (4, 5)
        assert values.shape == (4,)

    def test_get_action_and_value(self):
        net = ActorCriticNetwork()
        x = torch.randn(1, 57)
        action, log_prob, entropy, value = net.get_action_and_value(x)
        assert action.shape == (1,)
        assert 0 <= action.item() < 5
        assert log_prob.shape == (1,)
        assert entropy.shape == (1,)

    def test_evaluate_actions(self):
        net = ActorCriticNetwork()
        x = torch.randn(8, 57)
        actions = torch.randint(0, 5, (8,))
        log_probs, entropy, values = net.evaluate_actions(x, actions)
        assert log_probs.shape == (8,)
        assert entropy.shape == (8,)
        assert values.shape == (8,)

    def test_get_policy_sums_to_one(self):
        net = ActorCriticNetwork()
        x = torch.randn(3, 57)
        probs = net.get_policy(x)
        assert probs.shape == (3, 5)
        assert torch.allclose(probs.sum(dim=-1), torch.ones(3), atol=1e-5)

    def test_param_vector_roundtrip(self):
        net = ActorCriticNetwork()
        vec = net.param_vector()
        assert vec.dim() == 1
        assert vec.shape[0] == net.n_params()

        # Modify and reload
        new_vec = vec.clone() + 0.1
        net.load_param_vector(new_vec)
        assert torch.allclose(net.param_vector(), new_vec)

    def test_custom_hidden_sizes(self):
        net = ActorCriticNetwork(hidden_sizes=[64, 32])
        x = torch.randn(1, 57)
        logits, values = net(x)
        assert logits.shape == (1, 5)


# ── DQN Head ────────────────────────────────────────────────────


class TestDQNHead:
    def test_output_shape(self):
        dqn = DQNHead(obs_dim=57, n_actions=5)
        x = torch.randn(4, 57)
        q = dqn(x)
        assert q.shape == (4, 5)

    def test_target_network(self):
        dqn = DQNHead()
        x = torch.randn(2, 57)
        q = dqn(x)
        target_q = dqn.get_target_q(x)
        # After init they should be the same
        assert torch.allclose(q, target_q, atol=1e-6)

    def test_target_update(self):
        dqn = DQNHead()
        # Modify Q-network
        for p in dqn.q_net.parameters():
            p.data += 1.0
        # Target should differ now
        x = torch.randn(1, 57)
        assert not torch.allclose(dqn(x), dqn.get_target_q(x))
        # After update they should match again
        dqn.update_target()
        assert torch.allclose(dqn(x), dqn.get_target_q(x), atol=1e-6)

    def test_epsilon_greedy(self):
        dqn = DQNHead()
        x = torch.randn(1, 57)
        # With epsilon=0, should always pick greedy
        a1 = dqn.select_action(x, epsilon=0.0)
        a2 = dqn.select_action(x, epsilon=0.0)
        assert a1 == a2

    def test_param_vector_roundtrip(self):
        dqn = DQNHead()
        vec = dqn.param_vector()
        new_vec = vec.clone() + 0.1
        dqn.load_param_vector(new_vec)
        assert torch.allclose(dqn.param_vector(), new_vec)


# ── Replay Buffer ───────────────────────────────────────────────


class TestReplayBuffer:
    def test_push_and_len(self):
        buf = ReplayBuffer(capacity=100)
        assert len(buf) == 0
        buf.push(np.zeros(57), 0, 1.0, np.zeros(57), False)
        assert len(buf) == 1

    def test_capacity_limit(self):
        buf = ReplayBuffer(capacity=10)
        for i in range(20):
            buf.push(np.ones(57) * i, 0, 0.0, np.zeros(57), False)
        assert len(buf) == 10

    def test_sample_batch(self):
        buf = ReplayBuffer(capacity=100)
        for i in range(50):
            buf.push(np.random.randn(57), i % 5, 0.1, np.random.randn(57), False)
        batch = buf.sample(16)
        assert batch["states"].shape == (16, 57)
        assert batch["actions"].shape == (16,)
        assert batch["rewards"].shape == (16,)
        assert batch["next_states"].shape == (16, 57)
        assert batch["dones"].shape == (16,)


# ── PPO / GAE ───────────────────────────────────────────────────


class TestGAE:
    def test_gae_shape(self):
        rewards = [1.0, 0.5, 0.3, -0.1, 0.2]
        values = [10.0, 9.5, 9.0, 8.5, 8.0]
        dones = [False, False, False, False, True]
        advantages, returns = compute_gae(rewards, values, dones, last_value=7.5)
        assert advantages.shape == (5,)
        assert returns.shape == (5,)

    def test_gae_terminal_state(self):
        """At terminal state, advantage = reward - value (no bootstrap)."""
        rewards = [1.0]
        values = [0.5]
        dones = [True]
        advantages, returns = compute_gae(rewards, values, dones, last_value=0.0)
        # delta = reward + gamma*0*next_val - value = 1.0 - 0.5 = 0.5
        assert abs(advantages[0].item() - 0.5) < 1e-5


class TestPPOTrainer:
    def test_update_returns_metrics(self):
        net = ActorCriticNetwork()
        trainer = PPOTrainer(net, ppo_epochs=1, minibatch_size=4)
        batch = TrajectoryBatch()
        for _ in range(10):
            state = np.random.randn(57).astype(np.float32)
            batch.append(
                state=state,
                action=np.random.randint(0, 5),
                reward=np.random.randn(),
                value=np.random.randn(),
                log_prob=-1.5,
                done=False,
            )
        batch.dones[-1] = True
        metrics = trainer.update(batch)
        assert "policy_loss" in metrics
        assert "value_loss" in metrics
        assert "entropy" in metrics

    def test_empty_batch(self):
        net = ActorCriticNetwork()
        trainer = PPOTrainer(net)
        metrics = trainer.update(TrajectoryBatch())
        assert metrics["policy_loss"] == 0.0


# ── Base Agent ──────────────────────────────────────────────────


class TestBaseAgent:
    def test_ac_agent_select_action(self):
        agent = BaseAgent(agent_type=AgentType.ACTOR_CRITIC)
        state = np.random.randn(57).astype(np.float32)
        action = agent.select_action(state)
        assert 0 <= action < 5

    def test_dqn_agent_select_action(self):
        agent = BaseAgent(agent_type=AgentType.DQN)
        state = np.random.randn(57).astype(np.float32)
        action = agent.select_action(state)
        assert 0 <= action < 5

    def test_hybrid_agent(self):
        agent = BaseAgent(agent_type=AgentType.HYBRID)
        assert agent.ac_network is not None
        assert agent.dqn_head is not None
        state = np.random.randn(57).astype(np.float32)
        action = agent.select_action(state)
        assert 0 <= action < 5

    def test_store_and_train(self):
        agent = BaseAgent(agent_type=AgentType.ACTOR_CRITIC)
        state = np.random.randn(57).astype(np.float32)
        for _ in range(10):
            action = agent.select_action(state)
            next_state = np.random.randn(57).astype(np.float32)
            agent.store_transition(state, action, 0.1, next_state, False)
            state = next_state
        agent.store_transition(state, 0, 0.5, state, True)
        metrics = agent.train_step()
        assert "policy_loss" in metrics

    def test_fitness_tracking(self):
        agent = BaseAgent()
        agent.update_fitness(1.5)
        assert agent.fitness == 1.5
        assert agent.fitness_history == [1.5]
        agent.update_fitness(2.0)
        assert agent.fitness == 2.0
        assert len(agent.fitness_history) == 2

    def test_clone(self):
        agent = BaseAgent(agent_type=AgentType.ACTOR_CRITIC)
        agent.update_fitness(3.0)
        clone = agent.clone(new_id="clone_001")
        assert clone.agent_id == "clone_001"
        assert torch.allclose(
            agent.get_param_vector(), clone.get_param_vector()
        )

    def test_param_vector_set(self):
        agent = BaseAgent(agent_type=AgentType.ACTOR_CRITIC)
        vec = agent.get_param_vector()
        new_vec = vec + 0.5
        agent.set_param_vector(new_vec)
        assert torch.allclose(agent.get_param_vector(), new_vec)


# ── Agent Pool ──────────────────────────────────────────────────


class TestAgentPool:
    def test_pool_creation(self):
        pool = AgentPool(n_agents=10)
        assert len(pool.agents) == 10

    def test_ranking(self):
        pool = AgentPool(n_agents=5)
        for i, a in enumerate(pool.agents):
            a.fitness = float(i)
        ranked = pool.ranked()
        fitnesses = [a.fitness for a in ranked]
        assert fitnesses == sorted(fitnesses, reverse=True)

    def test_elites(self):
        pool = AgentPool(n_agents=10, elite_fraction=0.20)
        for i, a in enumerate(pool.agents):
            a.fitness = float(i)
        elites = pool.elites()
        assert len(elites) == 2

    def test_survivors(self):
        pool = AgentPool(n_agents=10, survivor_fraction=0.50)
        for i, a in enumerate(pool.agents):
            a.fitness = float(i)
        survivors = pool.survivors()
        assert len(survivors) == 5

    def test_best(self):
        pool = AgentPool(n_agents=5)
        pool.agents[2].fitness = 99.0
        assert pool.best().agent_id == pool.agents[2].agent_id

    def test_stats(self):
        pool = AgentPool(n_agents=4)
        for i, a in enumerate(pool.agents):
            a.fitness = float(i)
        assert pool.mean_fitness() == 1.5
        assert pool.max_fitness() == 3.0
        assert pool.fitness_std() > 0

    def test_replace(self):
        pool = AgentPool(n_agents=5)
        old_id = pool.agents[0].agent_id
        new_agent = BaseAgent(agent_id="new_agent")
        pool.replace(old_id, new_agent)
        assert pool.agents[0].agent_id == "new_agent"
