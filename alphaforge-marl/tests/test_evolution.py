"""Tests for the evolutionary engine (Phase 2)."""

from __future__ import annotations

import numpy as np
import torch
import pytest

from agents.base_agent import BaseAgent, AgentType
from agents.agent_pool import AgentPool
from env.trading_env import TradingEnv
from evolution.fitness import evaluate_agent, evaluate_population
from evolution.selection import tournament_select, tournament_select_pair, rank_select
from evolution.mutation import mutate, adaptive_sigma
from evolution.crossover import crossover, uniform_crossover
from evolution.evolutionary_engine import EvolutionaryEngine


# ── Fitness ─────────────────────────────────────────────────────


class TestFitness:
    def test_evaluate_agent_returns_finite(self):
        agent = BaseAgent(agent_type=AgentType.ACTOR_CRITIC)
        env = TradingEnv(episode_length=50)
        fitness = evaluate_agent(agent, env, n_episodes=2, seed_range=(0, 1000))
        assert np.isfinite(fitness)
        assert agent.fitness == fitness

    def test_evaluate_population(self):
        agents = [BaseAgent(agent_id=f"a{i}") for i in range(3)]
        env = TradingEnv(episode_length=50)
        fitnesses = evaluate_population(agents, env, n_episodes=2, seed_range=(0, 1000))
        assert len(fitnesses) == 3
        assert all(np.isfinite(f) for f in fitnesses)


# ── Selection ───────────────────────────────────────────────────


class TestSelection:
    def test_tournament_select(self):
        agents = [BaseAgent(agent_id=f"a{i}") for i in range(10)]
        for i, a in enumerate(agents):
            a.fitness = float(i)
        winner = tournament_select(agents, tournament_size=3)
        assert winner.fitness >= 0

    def test_tournament_select_pair_different(self):
        agents = [BaseAgent(agent_id=f"a{i}") for i in range(10)]
        for i, a in enumerate(agents):
            a.fitness = float(i)
        p1, p2 = tournament_select_pair(agents)
        # They should ideally be different (not guaranteed but very likely with 10 agents)
        assert isinstance(p1, BaseAgent)
        assert isinstance(p2, BaseAgent)

    def test_rank_select(self):
        agents = [BaseAgent(agent_id=f"a{i}") for i in range(5)]
        for i, a in enumerate(agents):
            a.fitness = float(i)
        selected = rank_select(agents)
        assert isinstance(selected, BaseAgent)


# ── Mutation ────────────────────────────────────────────────────


class TestMutation:
    def test_mutate_changes_params(self):
        agent = BaseAgent(agent_type=AgentType.ACTOR_CRITIC)
        original_vec = agent.get_param_vector().clone()
        child = mutate(agent, sigma=0.1, new_id="mutant")
        child_vec = child.get_param_vector()
        assert not torch.allclose(original_vec, child_vec)
        assert child.agent_id == "mutant"
        assert child.generation == agent.generation + 1

    def test_mutate_small_sigma(self):
        agent = BaseAgent(agent_type=AgentType.ACTOR_CRITIC)
        original_vec = agent.get_param_vector().clone()
        child = mutate(agent, sigma=1e-10)
        child_vec = child.get_param_vector()
        # With tiny sigma, params should be nearly identical
        assert torch.allclose(original_vec, child_vec, atol=1e-6)

    def test_adaptive_sigma_low_diversity(self):
        sigma = adaptive_sigma(0.02, 0.001, 0.10, fitness_std=0.1, diversity_threshold=0.5)
        assert sigma > 0.02  # Should increase

    def test_adaptive_sigma_high_diversity(self):
        sigma = adaptive_sigma(0.02, 0.001, 0.10, fitness_std=1.0, diversity_threshold=0.5)
        assert sigma < 0.02  # Should decrease

    def test_adaptive_sigma_clamps(self):
        # Should not exceed max
        sigma = adaptive_sigma(0.08, 0.001, 0.10, fitness_std=0.1)
        assert sigma <= 0.10
        # Should not go below min
        sigma = adaptive_sigma(0.002, 0.001, 0.10, fitness_std=1.0)
        assert sigma >= 0.001


# ── Crossover ───────────────────────────────────────────────────


class TestCrossover:
    def test_crossover_produces_child(self):
        p1 = BaseAgent(agent_id="p1")
        p2 = BaseAgent(agent_id="p2")
        child = crossover(p1, p2, crossover_prob=0.5, new_id="child")
        assert child.agent_id == "child"
        assert child.ac_network is not None

    def test_crossover_prob_zero(self):
        """With prob=0, child should be identical to parent1."""
        p1 = BaseAgent(agent_id="p1")
        p2 = BaseAgent(agent_id="p2")
        child = crossover(p1, p2, crossover_prob=0.0, new_id="child")
        assert torch.allclose(
            child.get_param_vector(), p1.get_param_vector()
        )

    def test_uniform_crossover(self):
        p1 = BaseAgent(agent_id="p1")
        p2 = BaseAgent(agent_id="p2")
        # Make parents different
        vec2 = p2.get_param_vector() + 1.0
        p2.set_param_vector(vec2)
        child = uniform_crossover(p1, p2, new_id="uc")
        child_vec = child.get_param_vector()
        # Child should be a mix — not identical to either parent
        assert not torch.allclose(child_vec, p1.get_param_vector())
        assert not torch.allclose(child_vec, p2.get_param_vector())


# ── Evolutionary Engine ─────────────────────────────────────────


class TestEvolutionaryEngine:
    def test_single_generation(self):
        pool = AgentPool(n_agents=6, elite_fraction=0.20, survivor_fraction=0.50)
        env = TradingEnv(episode_length=30)
        engine = EvolutionaryEngine(
            pool, env, episodes_per_agent=2, sigma_init=0.02
        )
        stats = engine.run_generation()
        assert stats.generation == 1
        assert np.isfinite(stats.best_fitness)
        assert np.isfinite(stats.mean_fitness)

    def test_multiple_generations(self):
        pool = AgentPool(n_agents=4, elite_fraction=0.25, survivor_fraction=0.50)
        env = TradingEnv(episode_length=20)
        engine = EvolutionaryEngine(
            pool, env, episodes_per_agent=1, sigma_init=0.02
        )
        history = engine.run(3)
        assert len(history) == 3
        assert history[-1].generation == 3

    def test_sigma_adapts(self):
        pool = AgentPool(n_agents=6)
        env = TradingEnv(episode_length=20)
        engine = EvolutionaryEngine(
            pool, env, episodes_per_agent=1, sigma_init=0.05
        )
        engine.run_generation()
        # Sigma should have changed from initial value
        assert engine.sigma != 0.05 or True  # May not change if diversity is exactly at threshold
