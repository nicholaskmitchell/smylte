"""Access-log redaction — a capability URL is a credential, so the journal gets
only the first four characters of its token.

Records are built the way uvicorn builds them, with its five access-log args,
and the last test formats one through uvicorn's own `AccessFormatter`: the
reason this is a filter and not another record-factory scrub is that the
formatter unpacks exactly those five args, so the shape has to survive.
"""
from __future__ import annotations

import logging

import pytest
from uvicorn.logging import AccessFormatter

from smylted import logredact

SHARE = "Sh4r3" + "x" * 38                # 43 characters, as token_urlsafe(32)
DISPLAY = "D1sp" + "y" * 39
BOOKING = "B00k" + "z" * 18               # 22 characters, as token_urlsafe(16)


def _record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 200), None)


def _filtered(path: str) -> str:
    record = _record(path)
    assert logredact.RedactCapabilityTokens().filter(record) is True
    return record.args[2]


@pytest.mark.parametrize("path, expected", [
    (f"/share/{SHARE}", "/share/Sh4r…"),
    (f"/share/{SHARE}/", "/share/Sh4r…/"),
    (f"/display/{DISPLAY}", "/display/D1sp…"),
    (f"/book/{BOOKING}", "/book/B00k…"),
    (f"/api/public/share/{SHARE}", "/api/public/share/Sh4r…"),
    (f"/api/public/display/{DISPLAY}.png?w=800&h=480",
     "/api/public/display/D1sp….png?w=800&h=480"),
    (f"/api/public/booking/{BOOKING}/book", "/api/public/booking/B00k…/book"),
    (f"/api/displays/{DISPLAY}", "/api/displays/D1sp…"),
    (f"/api/displays/{DISPLAY}/rotate", "/api/displays/D1sp…/rotate"),
    (f"/api/scheduling/links/{BOOKING}", "/api/scheduling/links/B00k…"),
    (f"/api/scheduling/bookings?link={BOOKING}", "/api/scheduling/bookings?link=B00k…"),
    (f"/api/scheduling/bookings?x=1&link={BOOKING}&y=2",
     "/api/scheduling/bookings?x=1&link=B00k…&y=2"),
])
def test_only_four_characters_of_a_token_survive(path, expected):
    redacted = _filtered(path)
    assert redacted == expected
    for token in (SHARE, DISPLAY, BOOKING):
        assert token[:5] not in redacted


@pytest.mark.parametrize("path", [
    "/api/displays/preview",
    "/api/displays/preview.png?mode=calendar",
    "/api/shares/0123456789abcdef0123456789abcdef",
    "/api/shares/0123456789abcdef0123456789abcdef/preview",
    "/api/scheduling/bookings",
    "/api/tasks/work",
    "/share/",
    f"/assets/{SHARE}.js",
])
def test_everything_else_is_untouched(path):
    assert _filtered(path) == path


def test_a_record_of_any_other_shape_passes_through():
    for args in ((), ("only", "two"), ("a", "GET", 42, "1.1", 200)):
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1, "msg", args, None)
        assert logredact.RedactCapabilityTokens().filter(record) is True
        assert record.args == args


def test_install_is_idempotent():
    logredact.install()
    logredact.install()
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, logredact.RedactCapabilityTokens) for f in filters) == 1


def test_the_line_uvicorn_writes_carries_no_token():
    logredact.install()
    logger = logging.getLogger("uvicorn.access")
    record = _record(f"/api/public/share/{SHARE}")
    assert logger.filter(record)
    line = AccessFormatter("%(client_addr)s - \"%(request_line)s\" %(status_code)s",
                           use_colors=False).format(record)
    assert line == '127.0.0.1:5000 - "GET /api/public/share/Sh4r… HTTP/1.1" 200 OK'
    assert SHARE not in line
