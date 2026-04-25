"""Experience replay buffer for DQN training."""

from __future__ import annotations

import random
from collections import deque
from typing import List, NamedTuple

import numpy as np
import torch


class Experience(NamedTuple):
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class ReplayBuffer:
    """Fixed-size circular replay buffer with uniform sampling."""

    def __init__(self, capacity: int = 50000):
        self._buffer: deque[Experience] = deque(maxlen=capacity)

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        self._buffer.append(Experience(state, action, reward, next_state, done))

    def sample(self, batch_size: int) -> dict[str, torch.Tensor]:
        """Sample a random batch, returned as tensors."""
        batch = random.sample(self._buffer, min(batch_size, len(self._buffer)))
        states = torch.FloatTensor(np.array([e.state for e in batch]))
        actions = torch.LongTensor([e.action for e in batch])
        rewards = torch.FloatTensor([e.reward for e in batch])
        next_states = torch.FloatTensor(np.array([e.next_state for e in batch]))
        dones = torch.FloatTensor([float(e.done) for e in batch])
        return {
            "states": states,
            "actions": actions,
            "rewards": rewards,
            "next_states": next_states,
            "dones": dones,
        }

    def __len__(self) -> int:
        return len(self._buffer)
