"""Transitional shim — the backend package is now `smylted`.

Autopull deploys new code to the Pi every minute, but the one-time
`deploy/migrate.sh` run that swaps the systemd unit is a human action. In the
window between those two moments the *old* unit is still on disk, and its
`ExecStart` is `python -m tasksd`. Without this package that window is a restart
crash-loop on the live deployment; with it, the old unit keeps booting cleanly
until the migration lands.

That is the whole job. There is no other reason to import `tasksd`, and nothing
new should. Delete this directory once the deployment is confirmed migrated —
`docs/DEPLOY.md` says when.
"""
from __future__ import annotations

import sys
import warnings

_NOTICE = (
    "tasksd: this package was renamed to `smylted`. You are running the "
    "pre-rename entry point; it still works, but run deploy/migrate.sh to "
    "finish the Smylte rename and this shim will go away."
)

# Two channels on purpose. The warning is what tests assert on; the stderr line
# is what an operator actually sees, because DeprecationWarning is silent by
# default and systemd puts stderr straight into the journal.
warnings.warn(_NOTICE, DeprecationWarning, stacklevel=2)
print(_NOTICE, file=sys.stderr)

from smylted import __version__  # noqa: E402,F401  (re-export: the shim is an alias)

__all__ = ["__version__"]
