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


def cyrb128(text: str) -> tuple[int, int, int, int]:
    """The cyrb128 hash over the UTF-8 bytes of `text`."""
    h1, h2, h3, h4 = 1779033703, 3144134277, 1013904242, 2773480762
    for k in text.encode("utf-8"):
        h1 = h2 ^ _imul(h1 ^ k, 597399067)
        h2 = h3 ^ _imul(h2 ^ k, 2869860233)
        h3 = h4 ^ _imul(h3 ^ k, 951274213)
        h4 = h1 ^ _imul(h4 ^ k, 2716044179)
    h1 = _imul(h3 ^ (h1 >> 18), 597399067)
    h2 = _imul(h4 ^ (h2 >> 22), 2869860233)
    h3 = _imul(h1 ^ (h3 >> 17), 951274213)
    h4 = _imul(h2 ^ (h4 >> 19), 2716044179)
    h1 ^= (h2 ^ h3 ^ h4)
    h2 ^= h1
    h3 ^= h1
    h4 ^= h1
    return h1 & MASK, h2 & MASK, h3 & MASK, h4 & MASK


class Rng:
    """sfc32 seeded from `cyrb128(path)`."""

    def __init__(self, path: str):
        self.path = path
        self._a, self._b, self._c, self._d = cyrb128(path)
        for _ in range(12):
            self._next32()

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
        for i in range(len(out) - 1, 0, -1):
            j = self.randint(0, i)
            out[i], out[j] = out[j], out[i]
        return out

    def fork(self, label: str) -> Rng:
        """A child stream named by this path and `label` alone, so it never
        depends on how much of this stream was consumed."""
        return Rng(f"{self.path}|{label}")

    @classmethod
    def for_day(cls, day: date, salt: str, purpose: str) -> Rng:
        return cls(f"{day.isoformat()}|{salt}|{purpose}")
