"""The focus session: the clock's settings, and (below) the session itself.

Everything here runs with NO Radicale, the way `test_day_plan.py` does: a focus
session is app-only state that exists nowhere on the wire, so the service reads
the cache and writes SQLite, and seeding `items` directly exercises the real
code with none of the round trips.
"""
from __future__ import annotations

from tasksd.service import FOCUS_DEFAULTS, focus_settings


# ── the clock's settings ─────────────────────────────────────────────────────

def test_focus_settings_fill_every_absent_key():
    """An account that never touched the section gets the whole table, so no
    reader of it has to know a default of its own."""
    assert focus_settings({}) == FOCUS_DEFAULTS
    assert focus_settings({"theme": "dark"}) == FOCUS_DEFAULTS


def test_focus_settings_clamp_and_refuse_junk():
    """A settings blob is hand-editable. An out-of-range int is clamped rather
    than obeyed (a zero-length interval would end before it began), a string is
    the default, and JSON `true` — an int subclass in Python — is NOT one
    minute: the same guard `_effective_capacity` keeps, for the same reason."""
    got = focus_settings({
        "focus_interval_minutes": 0,
        "focus_break_minutes": 999,
        "focus_long_break_minutes": "long",
        "focus_long_break_every": True,
        "focus_auto_continue": "yes",
        "focus_chime": False,
    })
    assert got["focus_interval_minutes"] == 1
    assert got["focus_break_minutes"] == 60
    assert got["focus_long_break_minutes"] == 15
    assert got["focus_long_break_every"] == 4
    assert got["focus_auto_continue"] is False
    assert got["focus_chime"] is False
    # Untouched keys still come back, at their defaults.
    assert got["focus_cap_default"] is False and got["focus_notify"] is False
