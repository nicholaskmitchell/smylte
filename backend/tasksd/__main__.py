"""`python -m tasksd` -> `python -m smylted`.

Kept so the pre-rename systemd unit boots. See `__init__.py` for why this
exists and when to delete it.
"""
from __future__ import annotations

from smylted.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
