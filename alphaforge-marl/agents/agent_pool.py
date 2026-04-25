"""Agent pool: manages a population of agents for evolutionary training."""

from __future__ import annotations

from typing import List, Optional

from agents.base_agent import BaseAgent, AgentType


class AgentPool:
    """Manages a population of trading agents.

    Provides sorted access by fitness, elite/survivor selection,
    and population-level statistics.
    """

    def __init__(
        self,
        n_agents: int = 30,
        agent_type: AgentType = AgentType.ACTOR_CRITIC,
        obs_dim: int = 57,
        n_actions: int = 5,
        hidden_sizes: list[int] | None = None,
        activation: str = "relu",
        use_attention: bool = True,
        elite_fraction: float = 0.10,
        survivor_fraction: float = 0.50,
        ppo_kwargs: dict | None = None,
    ):
        self.n_agents = n_agents
        self.elite_fraction = elite_fraction
        self.survivor_fraction = survivor_fraction
        self._ppo_kwargs = ppo_kwargs or {}

        self.agents: List[BaseAgent] = [
            BaseAgent(
                agent_type=agent_type,
                obs_dim=obs_dim,
                n_actions=n_actions,
                hidden_sizes=hidden_sizes,
                activation=activation,
                use_attention=use_attention,
                agent_id=f"agent_{i:03d}",
                **self._ppo_kwargs,
            )
            for i in range(n_agents)
        ]

    def ranked(self) -> List[BaseAgent]:
        """Return agents sorted by fitness (descending)."""
        return sorted(self.agents, key=lambda a: a.fitness, reverse=True)

    def elites(self) -> List[BaseAgent]:
        """Return top elite agents."""
        n = max(1, int(self.n_agents * self.elite_fraction))
        return self.ranked()[:n]

    def survivors(self) -> List[BaseAgent]:
        """Return top survivor agents (includes elites)."""
        n = max(1, int(self.n_agents * self.survivor_fraction))
        return self.ranked()[:n]

    def worst(self) -> List[BaseAgent]:
        """Return agents that didn't survive (to be replaced)."""
        n_survive = max(1, int(self.n_agents * self.survivor_fraction))
        return self.ranked()[n_survive:]

    def replace(self, old_id: str, new_agent: BaseAgent) -> None:
        """Replace an agent by ID."""
        for i, a in enumerate(self.agents):
            if a.agent_id == old_id:
                self.agents[i] = new_agent
                return

    def best(self) -> BaseAgent:
        """Return the best agent by fitness."""
        return max(self.agents, key=lambda a: a.fitness)

    def mean_fitness(self) -> float:
        if not self.agents:
            return 0.0
        return sum(a.fitness for a in self.agents) / len(self.agents)

    def max_fitness(self) -> float:
        if not self.agents:
            return 0.0
        return max(a.fitness for a in self.agents)

    def fitness_std(self) -> float:
        if len(self.agents) < 2:
            return 0.0
        mean = self.mean_fitness()
        var = sum((a.fitness - mean) ** 2 for a in self.agents) / len(self.agents)
        return var ** 0.5

    def set_generation(self, gen: int) -> None:
        for a in self.agents:
            a.generation = gen
