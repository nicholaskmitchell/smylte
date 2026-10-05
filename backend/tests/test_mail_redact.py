"""Log redaction — the record factory scrubs every logger's records, not just ours.

The point of installing redaction at the record factory is that a secret is
removed from records written by code that never knew it held one (uvicorn,
asyncio, the SDK). So these tests log through `uvicorn.error`, format with a
plain handler, and check the text a journal would receive.
"""
from __future__ import annotations

import io
import logging

import pytest

from smylted.mail import redact

SECRET = "bridge-pass-Q7w9e2"


@pytest.fixture(autouse=True)
def _registry():
    redact.install_log_redaction()
    redact.forget_all_for_tests()
    redact.register_secret(SECRET)
    yield
    redact.forget_all_for_tests()


@pytest.fixture
def uvicorn_log():
    """`uvicorn.error` with a formatting handler attached; yields (logger, buffer, records)."""
    log = logging.getLogger("uvicorn.error")
    buf = io.StringIO()
    stream = logging.StreamHandler(buf)
    stream.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    collect = Collect()
    old_level = log.level
    log.setLevel(logging.DEBUG)
    log.addHandler(stream)
    log.addHandler(collect)
    try:
        yield log, buf, records
    finally:
        log.removeHandler(stream)
        log.removeHandler(collect)
        log.setLevel(old_level)


def test_unrelated_logger_records_are_scrubbed(uvicorn_log):
    log, buf, _ = uvicorn_log
    log.warning("connecting with %s", SECRET)
    try:
        raise RuntimeError(f"login failed for password {SECRET}")
    except RuntimeError:
        log.exception("background task crashed")
    log.warning("about to send %s", SECRET, stack_info=True)

    out = buf.getvalue()
    assert SECRET not in out
    assert out.count(redact.REDACTED) >= 3
    assert "Traceback" in out and "RuntimeError: login failed for password <redacted>" in out
    assert "Stack (most recent call last)" in out


def test_record_without_a_secret_is_left_alone(uvicorn_log):
    log, buf, records = uvicorn_log
    try:
        raise ValueError("nothing sensitive here")
    except ValueError:
        log.exception("ordinary failure %d", 42)

    (record,) = records
    assert record.exc_info is not None
    assert record.msg == "ordinary failure %d" and record.args == (42,)
    assert "ValueError: nothing sensitive here" in buf.getvalue()


def test_unregistered_anthropic_key_is_redacted_by_shape():
    out = redact.redact("auth failed for sk-ant-api03-Zx9_y8-W7v6U5t4 (401)")
    assert "Zx9_y8" not in out
    assert out == "auth failed for sk-ant-<redacted> (401)"


def test_imap_login_password_is_redacted_but_not_the_user():
    assert redact.redact('a001 LOGIN me@x.org "p a s s"') == "a001 LOGIN me@x.org <redacted>"
    assert redact.redact("a002 LOGIN me@x.org hunter2") == "a002 LOGIN me@x.org <redacted>"
    sentence = "the server rejected the login for 'me'"
    assert redact.redact(sentence) == sentence


def test_short_values_are_not_registered():
    redact.register_secret("abc12")
    assert redact.redact("code abc12") == "code abc12"
    redact.register_secret("abc123")
    assert redact.redact("code abc123") == "code <redacted>"


def test_redact_exc():
    assert redact.redact_exc(RuntimeError(f"bad {SECRET}")) == "RuntimeError: bad <redacted>"
