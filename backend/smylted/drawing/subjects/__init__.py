"""The subjects the daily drawing rotates through, one import line each."""
from __future__ import annotations

from .base import DayDrawing, assert_declarative, joins_of

__all__ = ["MONTH_DRAWINGS", "ROSTER", "VIEW_DRAWINGS", "DayDrawing",
           "assert_declarative", "joins_of"]

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

from .months.january import January
from .months.february import February
from .months.march import March
from .months.april import April
from .months.may import May
from .months.june import June
from .months.july import July
from .months.august import August
from .months.september import September
from .months.october import October
from .months.november import November
from .months.december import December

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

# The Calendar's page top under Field notes: one still drawing per month of the
# year (1-12), northern seasons, landscape (months/_page.py). Served as view 'month'.
MONTH_DRAWINGS: dict[int, DayDrawing] = {
    1: January(),
    2: February(),
    3: March(),
    4: April(),
    5: May(),
    6: June(),
    7: July(),
    8: August(),
    9: September(),
    10: October(),
    11: November(),
    12: December(),
}
