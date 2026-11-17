"""The subjects the daily drawing rotates through, one import line each."""
from __future__ import annotations

from .base import DayDrawing, assert_declarative, joins_of

__all__ = ["ROSTER", "VIEW_DRAWINGS", "DayDrawing", "assert_declarative",
           "joins_of"]

from .desk import DeskWithKettle
from .tree import PottedTree
from .washing_line import WashingLine

ROSTER: list[DayDrawing] = [PottedTree(), DeskWithKettle(), WashingLine()]

# Static drawings for the 'tasks', 'calendar' and 'settings' views.
VIEW_DRAWINGS: dict[str, DayDrawing] = {}
