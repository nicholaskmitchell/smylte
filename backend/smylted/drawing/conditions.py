"""When a mark is on: a tuple of atoms, ANDed; an empty tuple is always on.

Atoms are tuples here and JSON lists on the wire. The client evaluates the same
atoms against its own copy of the day's state, so a drawing can react to a task
being finished without asking the server again.
"""
from __future__ import annotations

from .state import MAX_REWARDS, OVERDUE_LEVELS, DayState

# The number of arguments each atom takes.
_ARITY = {
    'reward': 1,
    'focus': 0,
    'allDone': 0,
    'notAllDone': 0,
    'nothingPlanned': 0,
    'planned': 0,
    'overdue': 1,
    'calm': 0,
    'progress': 1,
    'hour': 2,
}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_atom(atom) -> tuple:
    if not isinstance(atom, (list, tuple)) or not atom:
        raise ValueError(f"a condition atom must be a non-empty list, not {atom!r}")
    name, args = atom[0], tuple(atom[1:])
    if not isinstance(name, str) or name not in _ARITY:
        raise ValueError(f"unknown condition atom {name!r}")
    if len(args) != _ARITY[name]:
        raise ValueError(
            f"condition {name!r} takes {_ARITY[name]} argument(s), not {len(args)}")
    if name == 'reward':
        (i,) = args
        if not _is_int(i) or not 0 <= i < MAX_REWARDS:
            raise ValueError(f"reward index must be an int in 0..{MAX_REWARDS - 1}")
    elif name == 'overdue':
        (n,) = args
        if not _is_int(n) or not 1 <= n <= OVERDUE_LEVELS:
            raise ValueError(f"overdue level must be an int in 1..{OVERDUE_LEVELS}")
    elif name == 'progress':
        (p,) = args
        if not _is_number(p) or not 0 <= p <= 1:
            raise ValueError("progress must be a number in 0..1")
    elif name == 'hour':
        for h in args:
            if not _is_int(h) or not 0 <= h <= 24:
                raise ValueError("hour bounds must be ints in 0..24")
    return (name, *args)


def validate(when) -> tuple:
    """`when` as a tuple of tuples, or ValueError."""
    if not isinstance(when, (list, tuple)):
        raise ValueError(f"a condition list must be a list, not {when!r}")
    return tuple(_check_atom(atom) for atom in when)


def _atom_on(atom: tuple, state: DayState) -> bool:
    name = atom[0]
    if name == 'reward':
        return state.rewards > atom[1]
    if name == 'focus':
        return state.focus_active
    if name == 'allDone':
        return state.all_done
    if name == 'notAllDone':
        return not state.all_done
    if name == 'nothingPlanned':
        return state.nothing_planned
    if name == 'planned':
        return not state.nothing_planned
    if name == 'overdue':
        return min(state.overdue, OVERDUE_LEVELS) >= atom[1]
    if name == 'calm':
        return state.overdue == 0
    if name == 'progress':
        return state.progress >= atom[1]
    # 'hour': a window that wraps midnight when a >= b.
    a, b = atom[1], atom[2]
    if a < b:
        return a <= state.hour < b
    return state.hour >= a or state.hour < b


def evaluate(when, state: DayState) -> bool:
    return all(_atom_on(atom, state) for atom in validate(when))


def to_json(when) -> list[list]:
    return [list(atom) for atom in validate(when)]
