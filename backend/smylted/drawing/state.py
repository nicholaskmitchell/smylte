"""The part of a day the drawing reacts to."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Theme = Literal['light', 'dark']
# What a subject can be asked to draw: a theme, or 'paper', the composition the
# desk unit prints (drawn for ink; never served to a client).
Composition = Literal['light', 'dark', 'paper']

MAX_REWARDS = 12
OVERDUE_LEVELS = 3


@dataclass(frozen=True)
class DayState:
    progress: float = 0.0        # done / planned today, 0..1
    rewards: int = 0             # tasks finished today
    focus_active: bool = False
    all_done: bool = False
    nothing_planned: bool = False
    overdue: int = 0
    hour: int = 12               # 0..23
