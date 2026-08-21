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


class MalformedResponse(DavError):
    """The server answered, and the body is not XML we can read.

    Distinct from the transport failures above because the remedy is different:
    a 4xx/5xx or a dropped connection says "ask again later", while this says
    "this particular BATCH is unreadable" — Radicale copies item bytes verbatim
    into <C:calendar-data>, so one resource carrying a character XML forbids
    (U+FFFE/U+FFFF) makes the whole multistatus unparseable while every other
    resource in it is fine. `SyncEngine._multiget` keys its per-href fallback on
    this specifically, so a network blip does not become fifty retries."""
