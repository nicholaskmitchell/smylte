"""Passive displays: what a screen on a wall is shown, and how it is drawn.

A display is a screen that takes no input. It has no session, no controls and no
way to change anything it shows — which is not a limitation to be worked around
but the whole specification. Everything here follows from it.

`frame.py` builds the CONTENT, once, as plain data: a month grid, or a day's
habits and tasks, with every string already formatted in the owner's language
and clock. `render.py` turns that content into pixels for a panel that has no
browser. The browser page (frontend/src/components/DisplayView.tsx) renders the
same frame in HTML. Three surfaces, one content model — so a fix to what a
display SAYS lands on all of them, and only how it LOOKS is written twice.

The frame carries formatted labels rather than raw dates for exactly that
reason. The obvious alternative — ship ISO strings and let each renderer
localize — means the image endpoint and the browser page each own a copy of the
weekday names, the month names and the clock, and they drift the first time one
is fixed. Formatting once, server-side, is what keeps a panel and a browser
showing the same words.
"""
from .frame import TREATMENTS, build_frame

__all__ = ["TREATMENTS", "build_frame"]
