"""NSGA-II: Non-dominated Sorting Genetic Algorithm II.

Multi-objective evolution that maintains a Pareto front across Sharpe ratio,
maximum drawdown, and turnover — instead of collapsing everything into a
single scalar fitness.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from agents.base_agent import BaseAgent


def fast_non_dominated_sort(
    objectives: np.ndarray,
) -> List[List[int]]:
    """NSGA-II fast non-dominated sort.

    Args:
        objectives: (n, k) array where higher is better for all objectives.

    Returns:
        List of fronts, each a list of indices. Front 0 is Pareto-optimal.
    """
    n = len(objectives)
    domination_count = np.zeros(n, dtype=int)
    dominated_set: List[List[int]] = [[] for _ in range(n)]
    fronts: List[List[int]] = [[]]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if _dominates(objectives[i], objectives[j]):
                dominated_set[i].append(j)
            elif _dominates(objectives[j], objectives[i]):
                domination_count[i] += 1

        if domination_count[i] == 0:
            fronts[0].append(i)

    current_front = 0
    while fronts[current_front]:
        next_front: List[int] = []
        for i in fronts[current_front]:
            for j in dominated_set[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    next_front.append(j)
        current_front += 1
        fronts.append(next_front)

    # Remove empty last front
    return [f for f in fronts if f]


def crowding_distance(
    objectives: np.ndarray,
    front: List[int],
) -> np.ndarray:
    """Compute crowding distance for individuals in a front.

    Individuals at the boundary get infinite distance (always selected).
    Others are scored by how spread out they are in objective space.
    """
    n = len(front)
    if n <= 2:
        return np.full(n, float("inf"))

    distances = np.zeros(n)
    obj_subset = objectives[front]  # (n, k)

    for m in range(objectives.shape[1]):
        sorted_idx = np.argsort(obj_subset[:, m])
        distances[sorted_idx[0]] = float("inf")
        distances[sorted_idx[-1]] = float("inf")

        obj_range = float(obj_subset[sorted_idx[-1], m] - obj_subset[sorted_idx[0], m])
        if obj_range < 1e-12:
            continue

        for k in range(1, n - 1):
            distances[sorted_idx[k]] += (
                obj_subset[sorted_idx[k + 1], m] - obj_subset[sorted_idx[k - 1], m]
            ) / obj_range

    return distances


def nsga2_select(
    agents: List[BaseAgent],
    objectives: Dict[str, List[float]],
    n_select: int,
) -> List[BaseAgent]:
    """NSGA-II selection: non-dominated sort + crowding distance.

    Args:
        agents: All agents in population.
        objectives: Dict of objective_name -> list of values (same order as agents).
                   Higher is better for all objectives.
        n_select: Number of agents to select (survivors).

    Returns:
        Selected agents.
    """
    obj_names = list(objectives.keys())
    obj_matrix = np.array([objectives[k] for k in obj_names]).T  # (n, k)

    fronts = fast_non_dominated_sort(obj_matrix)

    selected: List[BaseAgent] = []
    for front in fronts:
        if len(selected) + len(front) <= n_select:
            selected.extend(agents[i] for i in front)
        else:
            # Need partial front: use crowding distance
            remaining = n_select - len(selected)
            cd = crowding_distance(obj_matrix, front)
            # Sort by crowding distance (descending)
            sorted_front = sorted(
                zip(front, cd), key=lambda x: -x[1]
            )
            selected.extend(agents[idx] for idx, _ in sorted_front[:remaining])
            break

    return selected


def compute_multi_objectives(
    agents: List[BaseAgent],
    episode_results: Dict[str, Dict[str, float]],
) -> Dict[str, List[float]]:
    """Compute multi-objective fitness for NSGA-II.

    Returns dict with three objectives (higher = better):
    - sharpe: Annualized Sharpe ratio
    - neg_drawdown: Negative of max drawdown (higher = less drawdown)
    - neg_turnover: Negative of mean turnover (higher = less turnover)
    """
    sharpes = []
    neg_drawdowns = []
    neg_turnovers = []

    for agent in agents:
        results = episode_results.get(agent.agent_id, {})
        sharpes.append(results.get("sharpe", agent.fitness))
        neg_drawdowns.append(-results.get("max_drawdown", 0.5))
        neg_turnovers.append(-results.get("mean_turnover", 0.5))

    return {
        "sharpe": sharpes,
        "neg_drawdown": neg_drawdowns,
        "neg_turnover": neg_turnovers,
    }


def _dominates(a: np.ndarray, b: np.ndarray) -> bool:
    """True if a dominates b (a >= b on all, a > b on at least one)."""
    return bool((a >= b).all() and (a > b).any())
