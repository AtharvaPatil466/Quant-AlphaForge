"""Action space definitions for the MARL trading environment.

Discrete only (5 actions). Continuous action space is not implemented.
"""

from __future__ import annotations

from enum import IntEnum


class Action(IntEnum):
    HOLD = 0
    LONG_STRONG = 1
    LONG_MILD = 2
    SHORT_STRONG = 3
    SHORT_MILD = 4


# Position size multipliers per action
ACTION_POSITION = {
    Action.HOLD: 0.0,
    Action.LONG_STRONG: 1.0,
    Action.LONG_MILD: 0.5,
    Action.SHORT_STRONG: -1.0,
    Action.SHORT_MILD: -0.5,
}

N_ACTIONS = len(Action)
