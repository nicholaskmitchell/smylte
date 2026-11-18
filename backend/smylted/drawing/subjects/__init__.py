"""The subjects the daily drawing rotates through, one import line each."""
from __future__ import annotations

from .base import DayDrawing, assert_declarative, joins_of

__all__ = ["ROSTER", "VIEW_DRAWINGS", "DayDrawing", "assert_declarative",
           "joins_of"]

from .bicycle import Bicycle
from .bookshelf import Bookshelf
from .clipboard import Clipboard
from .desk import DeskWithKettle
from .feeder import BirdFeeder
from .kite import Kite
from .kitchen import KitchenCounter
from .lighthouse import Lighthouse
from .pond import LilyPond
from .radio import Radio
from .seedlings import WindowsillSeedlings
from .tent import Tent
from .tidepool import TidePool
from .tree import PottedTree
from .vegpatch import VegetablePatch
from .wall_calendar import WallCalendar
from .washing_line import WashingLine

ROSTER: list[DayDrawing] = [
    PottedTree(), DeskWithKettle(), WashingLine(),
    WindowsillSeedlings(), Bookshelf(), Kite(), BirdFeeder(), TidePool(),
    Lighthouse(), VegetablePatch(), Tent(), LilyPond(), Bicycle(), KitchenCounter(),
]

# Static drawings for the 'tasks', 'calendar' and 'settings' views.
VIEW_DRAWINGS: dict[str, DayDrawing] = {
    'tasks': Clipboard(),
    'calendar': WallCalendar(),
    'settings': Radio(),
}
