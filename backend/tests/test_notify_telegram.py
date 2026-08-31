"""The Telegram transport — pure httpx.MockTransport, no network, no Radicale.

The three things this covers are the three reasons the module is not just
Søren's file copied across: it retries what is worth retrying, it gives up
immediately on what is not, and it never lets the bot token reach a log line or
the delivery ledger.
"""
from __future__ import annotations

import httpx
import pytest

from tasksd.notify import telegram as tg

TOKEN = "123456789:AAHverySecretTokenValueThatMustNotLeak_x"


def _sender(handler, **kw):
    """A sender wired to a fake Bot API. `sleep` is a no-op so retries are free."""
    kw.setdefault("sleep", lambda _s: None)
    return tg.TelegramSender(TOKEN, transport=httpx.MockTransport(handler), **kw)


def _ok(message_id: int = 42):
    return httpx.Response(200, json={"ok": True, "result": {"message_id": message_id}})


def _fail(status: int, description: str, **params):
    body = {"ok": False, "error_code": status, "description": description}
    if params:
        body["parameters"] = params
    return httpx.Response(status, json=body)


# ── the happy path ───────────────────────────────────────────────────────────

def test_a_send_reports_the_message_id():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return _ok(7)

    result = _sender(handler).send(555, "Backup finished — 412 GB, no errors.")
    assert result.ok and result.message_id == 7 and result.attempts == 1
    assert result.error is None
    assert seen["url"].endswith(f"/bot{TOKEN}/sendMessage")


def test_silent_is_sent_as_disable_notification():
    # The loud/quiet split is the whole volume control; it has to reach the wire.
    captured = {}

    def handler(request):
        import json
        captured.update(json.loads(request.read()))
        return _ok()

    _sender(handler).send(555, "recorded, not urgent", silent=True)
    assert captured["disable_notification"] is True

    _sender(handler).send(555, "act on this")
    assert captured["disable_notification"] is False


def test_a_reply_may_outlive_its_parent():
    # Losing an alert because the thread it belonged to was deleted is the wrong
    # trade, so the send opts out of that failure.
    captured = {}

    def handler(request):
        import json
        captured.update(json.loads(request.read()))
        return _ok()

    _sender(handler).send(555, "step two", reply_to=11)
    assert captured["reply_to_message_id"] == 11
    assert captured["allow_sending_without_reply"] is True


# ── retrying what is worth retrying ──────────────────────────────────────────

def test_a_5xx_is_retried_and_can_still_succeed():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _ok() if calls["n"] == 3 else httpx.Response(502, json={"ok": False,
                                                                       "error_code": 502,
                                                                       "description": "Bad Gateway"})

    result = _sender(handler).send(555, "x")
    assert result.ok and result.attempts == 3 and calls["n"] == 3


def test_a_network_error_is_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("connection reset", request=request)
        return _ok()

    result = _sender(handler).send(555, "x")
    assert result.ok and result.attempts == 2


def test_retries_are_bounded_and_report_the_last_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _fail(500, "Internal Server Error")

    result = _sender(handler, max_attempts=3).send(555, "x")
    assert not result.ok and result.attempts == 3 and calls["n"] == 3
    assert "500" in result.error


def test_a_429_waits_exactly_as_long_as_telegram_asked():
    # Telegram states the delay; guessing at one either hammers it or sits on a
    # worker thread longer than the notification is worth.
    slept: list[float] = []
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _ok() if calls["n"] > 1 else _fail(429, "Too Many Requests", retry_after=7)

    s = tg.TelegramSender(TOKEN, transport=httpx.MockTransport(handler), sleep=slept.append)
    assert s.send(555, "x").ok
    assert slept == [7.0]


def test_an_absurd_retry_after_is_capped():
    slept: list[float] = []
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _ok() if calls["n"] > 1 else _fail(429, "Too Many Requests", retry_after=8000)

    s = tg.TelegramSender(TOKEN, transport=httpx.MockTransport(handler), sleep=slept.append)
    s.send(555, "x")
    assert slept == [tg.MAX_RETRY_AFTER_S]


# ── giving up immediately on what cannot succeed ─────────────────────────────

@pytest.mark.parametrize(
    "code,desc",
    [
        (400, "Bad Request: chat not found"),
        (401, "Unauthorized"),
        (403, "Forbidden: bot was blocked by the user"),
        (404, "Not Found"),
    ],
)
def test_a_configuration_failure_is_permanent_and_tried_once(code, desc):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _fail(code, desc)

    result = _sender(handler).send(555, "x")
    assert not result.ok and result.permanent and result.attempts == 1
    assert calls["n"] == 1, "a permanent failure retried is a rate-limit ban earned for nothing"


def test_an_unconfigured_sender_fails_permanently_without_a_request():
    def handler(request):  # pragma: no cover - must never run
        raise AssertionError("no token, so no request may be made")

    s = tg.TelegramSender("", transport=httpx.MockTransport(handler))
    result = s.send(555, "x")
    assert not result.ok and result.permanent and not s.configured


def test_an_empty_message_is_refused_rather_than_sent():
    def handler(request):  # pragma: no cover - must never run
        raise AssertionError("an empty notification is a bug, not a message")

    result = tg.TelegramSender(TOKEN, transport=httpx.MockTransport(handler)).send(555, "   ")
    assert not result.ok and result.permanent


# ── the token never escapes ──────────────────────────────────────────────────

def test_a_transport_error_never_carries_the_token():
    # httpx puts the request URL in the exception text, and the URL contains the
    # token. This string is written to the log AND to the delivery ledger.
    def handler(request):
        raise httpx.ConnectError(f"failed to connect to {request.url}", request=request)

    result = _sender(handler, max_attempts=1).send(555, "x")
    assert not result.ok
    assert TOKEN not in result.error
    assert "AAHverySecretTokenValueThatMustNotLeak" not in result.error
    assert "<redacted>" in result.error


def test_an_api_error_echoing_the_token_is_redacted():
    def handler(request):
        return _fail(400, f"Bad Request: something about /bot{TOKEN}/sendMessage")

    result = _sender(handler).send(555, "x")
    assert TOKEN not in result.error and "<redacted>" in result.error


def test_redaction_catches_a_bare_token_outside_a_url():
    assert TOKEN not in tg._redact(f"leaked {TOKEN} here")
    assert tg._redact("nothing to see") == "nothing to see"


# ── the 4096 ceiling ─────────────────────────────────────────────────────────

def test_an_over_long_message_is_clipped_rather_than_dropped():
    captured = {}

    def handler(request):
        import json
        captured.update(json.loads(request.read()))
        return _ok()

    body = "\n".join(f"line {i} with some padding to make it long" for i in range(500))
    assert len(body) > tg.MAX_MESSAGE_CHARS
    result = _sender(handler).send(555, body)
    assert result.ok
    assert len(captured["text"]) <= tg.MAX_MESSAGE_CHARS
    assert captured["text"].endswith("(clipped)")


def test_a_message_at_the_limit_is_untouched():
    body = "x" * tg.MAX_MESSAGE_CHARS
    assert tg.clip(body) == body
    assert tg.clip("short") == "short"


def test_clipping_prefers_a_line_break():
    body = ("a" * 100 + "\n") * 60          # comfortably over the cap
    out = tg.clip(body)
    assert out.endswith(tg._CLIP_MARKER)
    assert out[: -len(tg._CLIP_MARKER)].endswith("a")


# ── html escaping ────────────────────────────────────────────────────────────

def test_escape_html_covers_the_three_characters_that_reject_a_send():
    assert tg.escape_html("a & b <tag> c") == "a &amp; b &lt;tag&gt; c"
