"""DAV error taxonomy.

These map HTTP conditions to Python exceptions the sync engine and write path
reason about explicitly. Note which are *expected conditions*, not failures:

  - PreconditionFailed (412): expected on a concurrent write (invariant #5).
    Refetch, re-apply field-level intent, retry once.
  - InvalidSyncToken: expected when Radicale prunes a token or drops its cache
    (invariant #6). Fall back to a full resync.
"""
from __future__ import annotations


class DavError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class AuthError(DavError):
    """401/403 that is not a sync-token precondition."""


class NotFound(DavError):
    """404 — resource gone (a foreign client may have deleted it)."""


class Conflict(DavError):
    """409 — e.g. MKCALENDAR on an existing path, or a parent that doesn't exist."""


class PreconditionFailed(DavError):
    """412 — If-Match etag mismatch. EXPECTED on concurrent edits; not an error."""


class InvalidSyncToken(DavError):
    """sync-collection token no longer valid. EXPECTED; fall back to full resync."""
