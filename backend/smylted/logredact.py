"""Keep capability tokens out of the access log.

A share, display or booking link is its own credential: whoever holds the URL
holds what it reaches. `uvicorn.run(..., log_level="info")` keeps uvicorn's
access log, so every one of those URLs, and the owner routes that name a
display or booking link by its token, was written to journald whole, where
anyone who can read the journal could copy it.

`mail/redact.py` cannot be stretched to cover this. Its record-factory scrub
rewrites `record.args = ()` when it matches, and uvicorn's
`AccessFormatter.formatMessage` unpacks exactly five args, so every matching
access line would fail to format. So this is a filter on the `uvicorn.access`
logger alone, and it rewrites only the path argument, keeping the record's
shape. uvicorn applies its dictConfig in `Config.__init__`, before the app
factory runs, so a filter installed from `create_app` is not replaced.

The first four characters of a token survive, which is enough for the owner to
match a log line to a link in Settings and nowhere near enough to use it. The
`{16,}` tail is what keeps `/api/displays/preview` whole: no route word is that
long, and every token is (booking tokens are 22 characters, display and share
tokens 43). Share owner routes are keyed by the share's id, not its token, so
they need nothing here.
"""
from __future__ import annotations

import logging
import re

_CAPABILITY_PATH = re.compile(
    r"^(/(?:share|display|book)/|/api/public/(?:share|display|booking)/"
    r"|/api/displays/|/api/scheduling/links/)([A-Za-z0-9_-]{4})[A-Za-z0-9_-]{16,}")
# The owner's bookings list filtered to one link names that link by its token in
# the query string.
_LINK_QUERY = re.compile(
    r"^(/api/scheduling/bookings\?(?:[^#]*&)?link=)([A-Za-z0-9_-]{4})[A-Za-z0-9_-]{16,}")


def redact_path(path: str) -> str:
    """`path` with every capability token cut to its first four characters."""
    path = _CAPABILITY_PATH.sub(r"\1\2…", path)
    return _LINK_QUERY.sub(r"\1\2…", path)


class RedactCapabilityTokens(logging.Filter):
    """Shorten the token in an access-log line's path. Never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn's args are (client_addr, method, full_path, http_version,
        # status_code). Any other shape is somebody else's record, or one the
        # mail scrub already emptied, and is left exactly as it is.
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = redact_path(args[2])
            if path != args[2]:
                record.args = (*args[:2], path, *args[3:])
        return True


def install() -> None:
    """Add the filter to `uvicorn.access`. Idempotent, so every `create_app`
    in a process (the tests build many) can call it."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactCapabilityTokens) for f in logger.filters):
        logger.addFilter(RedactCapabilityTokens())
