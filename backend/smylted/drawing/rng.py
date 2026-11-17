"""A seeded random stream for the daily drawing.

cyrb128 turns a path string into four 32-bit words and sfc32 runs from them, so
the same path always gives the same stream on every device. A stream is named by
its path, never by how far another stream has been read: `fork` builds a new
path, which is what keeps one part of a drawing from shifting when another part
draws one more point.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import TypeVar

T = TypeVar("T")

MASK = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & MASK


_SEED = (1779033703, 3144134277, 1013904242, 2773480762)


def _absorb(state: tuple[int, int, int, int], data: bytes) -> tuple[int, int, int, int]:
    """cyrb128's loop over `data`, from `state`: the hash of a path is its
    prefix's state carried on, which is what lets `fork` hash only its label."""
    h1, h2, h3, h4 = state
    # `_imul` inlined: a drawing forks a few hundred streams, and the call per
    # byte was most of the cost of each. Same arithmetic, same numbers.
    m = MASK
    for k in data:
        h1 = h2 ^ (((h1 ^ k) * 597399067) & m)
        h2 = h3 ^ (((h2 ^ k) * 2869860233) & m)
        h3 = h4 ^ (((h3 ^ k) * 951274213) & m)
        h4 = h1 ^ (((h4 ^ k) * 2716044179) & m)
    return h1, h2, h3, h4


def _finish(state: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    h1, h2, h3, h4 = state
    h1 = _imul(h3 ^ (h1 >> 18), 597399067)
    h2 = _imul(h4 ^ (h2 >> 22), 2869860233)
    h3 = _imul(h1 ^ (h3 >> 17), 951274213)
    h4 = _imul(h2 ^ (h4 >> 19), 2716044179)
    h1 ^= (h2 ^ h3 ^ h4)
    h2 ^= h1
    h3 ^= h1
    h4 ^= h1
    return h1 & MASK, h2 & MASK, h3 & MASK, h4 & MASK


def cyrb128(text: str) -> tuple[int, int, int, int]:
    """The cyrb128 hash over the UTF-8 bytes of `text`."""
    return _finish(_absorb(_SEED, text.encode("utf-8")))


class Rng:
    """sfc32 seeded from `cyrb128(path)`."""

    def __init__(self, path: str, _state: tuple[int, int, int, int] | None = None):
        self.path = path
        # The hash loop's state after `path`, kept so a fork carries it on.
        # `_state` is only ever `fork`'s: the state that `path` itself gives.
        self._h = _absorb(_SEED, path.encode("utf-8")) if _state is None else _state
        a, b, c, d = _finish(self._h)
        # The twelve warm-up steps of `_next32`, inlined: a drawing makes a few
        # hundred streams, and the method call was a large part of each.
        m = MASK
        for _ in range(12):
            t = (a + b) & m
            a = b ^ (b >> 9)
            b = (c + (c << 3)) & m
            c = ((c << 21) | (c >> 11)) & m
            d = (d + 1) & m
            t = (t + d) & m
            c = (c + t) & m
        self._a, self._b, self._c, self._d = a, b, c, d

    def _next32(self) -> int:
        a, b, c, d = self._a, self._b, self._c, self._d
        t = (a + b) & MASK
        a = b ^ (b >> 9)
        b = (c + (c << 3)) & MASK
        c = ((c << 21) | (c >> 11)) & MASK
        d = (d + 1) & MASK
        t = (t + d) & MASK
        c = (c + t) & MASK
        self._a, self._b, self._c, self._d = a, b, c, d
        return t

    def random(self) -> float:
        """A float in [0, 1)."""
        return self._next32() / 4294967296

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.random()

    def randint(self, lo: int, hi: int) -> int:
        """An int in [lo, hi], both ends included."""
        return lo + int(self.random() * (hi - lo + 1))

    def choice(self, seq: Sequence[T]) -> T:
        return seq[self.randint(0, len(seq) - 1)]

    def chance(self, p: float) -> bool:
        return self.random() < p

    def jitter(self, amount: float) -> float:
        """A float in [-amount, amount]."""
        return self.uniform(-amount, amount)

    def shuffled(self, seq: Sequence[T]) -> list[T]:
        """A Fisher-Yates shuffle of a copy of `seq`."""
        out = list(seq)
        random = self.random              # `randint(0, i)`, with the lookups hoisted
        for i in range(len(out) - 1, 0, -1):
            j = int(random() * (i + 1))
            out[i], out[j] = out[j], out[i]
        return out

    def fork(self, label: str) -> Rng:
        """A child stream named by this path and `label` alone, so it never
        depends on how much of this stream was consumed."""
        tail = f"|{label}"
        return Rng(self.path + tail, _absorb(self._h, tail.encode("utf-8")))

    @classmethod
    def for_day(cls, day: date, salt: str, purpose: str) -> Rng:
        return cls(f"{day.isoformat()}|{salt}|{purpose}")
