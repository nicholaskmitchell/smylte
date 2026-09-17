"""Hand-rolled CalDAV client (httpx + lxml)."""
from __future__ import annotations

from .client import CollectionInfo, DavClient, Item, SyncResult
from .errors import (
    AuthError,
    Conflict,
    DavError,
    InvalidSyncToken,
    NotFound,
    PreconditionFailed,
)

__all__ = [
    "DavClient",
    "Item",
    "CollectionInfo",
    "SyncResult",
    "DavError",
    "AuthError",
    "NotFound",
    "Conflict",
    "PreconditionFailed",
    "InvalidSyncToken",
]
