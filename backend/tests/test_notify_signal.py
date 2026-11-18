"""The signal-bot transport — pure httpx.MockTransport, no network, no Radicale.

What this covers: the request the bot expects, the retry table (including the
AMBIGUOUS failure, where the bot may already have sent the message), what fails
at once, that the token never reaches a returned error, and the loopback rule
for the bot's URL.
"""
from __future__ import annotations

import json

import httpx
import pytest

from smylted.notify import signal as sg
from smylted.notify import transport as tp

TOKEN = "sig-src-token-VerySecretValueThatMustNotLeak_x"
TS = 1791055942166


class _Script:
    """A fake bot that answers each request with the next item of `steps`: an
    httpx.Response, or an exception class to raise for that request."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, type) and issubclass(step, Exception):
            raise step(f"{step.__name__} talking to {request.url}", request=request)
        return step


def _sender(handler, *, token: str = TOKEN, sleeps: list | None = None, **kw):
    """A sender wired to a fake bot. `sleep` records the delays instead of waiting."""
    record = sleeps if sleeps is not None else []
    return sg.SignalSender(token=token, transport=httpx.MockTransport(handler),
                           sleep=record.append, **kw)


def _ok(ts=TS):
    return httpx.Response(200, json={"ok": True, "result": {
        "sent": True, "source": "Smylte", "chat_id": "owner",
        "timestamp": ts, "text": "Smylte: x"}})


def _fail(status: int, code: str, error: str):
    return httpx.Response(status, json={"ok": False, "code": code, "error": error})


# ── the request ──────────────────────────────────────────────────────────────

def test_a_send_posts_to_the_bot_and_reports_the_timestamp():
    bot = _Script(_ok())
    result = _sender(bot).send(sg.OWNER, "Dentist at 3pm.")
    assert result.ok and result.message_id == TS and result.attempts == 1
    assert result.error is None
    [req] = bot.requests
    assert str(req.url) == "http://127.0.0.1:8801/v1/send"
    assert req.method == "POST"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req.read()) == {"text": "Dentist at 3pm.", "chat_id": "owner",
                                      "silent": False}


def test_silent_is_sent_as_silent_true():
    # The loud/quiet split is the whole volume control; it has to reach the wire.
    bot = _Script(_ok())
    _sender(bot).send(sg.OWNER, "recorded, not urgent", silent=True)
    assert json.loads(bot.requests[0].read())["silent"] is True


def test_a_timestamp_that_is_not_an_int_is_no_message_id():
    for ts in (True, "1791055942166", None):
        assert _sender(_Script(_ok(ts))).send(sg.OWNER, "x").message_id is None


def test_a_timestamp_the_ledger_cannot_hold_is_no_message_id():
    for ts in (2**63, 0, -1):
        assert _sender(_Script(_ok(ts))).send(sg.OWNER, "x").message_id is None
    assert _sender(_Script(_ok(2**63 - 1))).send(sg.OWNER, "x").message_id == 2**63 - 1


def test_the_status_is_the_last_responses():
    assert _sender(_Script(_ok())).send(sg.OWNER, "x").status == 200
    assert _sender(_Script(_fail(401, "unauthorized", "no"))).send(sg.OWNER, "x").status == 401
    assert _sender(_Script(_fail(502, "unavailable", "down"))).send(sg.OWNER, "x").status == 502
    bot = _Script(_fail(502, "unavailable", "down"), httpx.ConnectError)
    assert _sender(bot).send(sg.OWNER, "x").status == 502
    assert _sender(_Script(httpx.ConnectError)).send(sg.OWNER, "x").status is None


# ── retries ──────────────────────────────────────────────────────────────────

def test_a_connect_error_is_retried_with_the_shipped_delays():
    sleeps: list = []
    bot = _Script(httpx.ConnectError, httpx.ConnectError, _ok())
    result = _sender(bot, sleeps=sleeps).send(sg.OWNER, "x")
    assert result.ok and result.attempts == 3
    assert sleeps == [1.0, 2.0]


def test_retries_are_bounded_and_not_permanent():
    bot = _Script(httpx.ConnectError)
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and not result.permanent
    assert result.attempts == 3 and len(bot.requests) == 3
    assert "ConnectError" in result.error


def test_a_connect_timeout_is_retried_too():
    bot = _Script(httpx.ConnectTimeout, _ok())
    assert _sender(bot).send(sg.OWNER, "x").ok
    assert len(bot.requests) == 2


def test_a_5xx_is_retried_and_can_still_succeed():
    bot = _Script(_fail(502, "unavailable", "signal-cli is restarting"), _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert result.ok and result.attempts == 2


def test_a_2xx_that_is_not_ok_is_retried():
    bot = _Script(httpx.Response(200, text="<html>not the bot</html>"), _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert result.ok and result.attempts == 2


def test_a_body_nested_too_deep_to_parse_is_an_unexpected_response():
    bot = _Script(httpx.Response(200, text="[" * 100000))
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and not result.permanent
    assert result.error == "HTTP 200: unexpected response"


def test_out_of_attempts_on_an_odd_2xx_says_so():
    bot = _Script(httpx.Response(200, json={"ok": False}))
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and not result.permanent
    assert result.error == "HTTP 200: unexpected response"


# ── the ambiguous failure ────────────────────────────────────────────────────

def test_a_refused_duplicate_after_a_lost_answer_was_delivered():
    # The read timed out after the bot may have sent it; the bot refuses the
    # same text within 60 s, so the 422 says the first attempt landed.
    bot = _Script(httpx.ReadTimeout, _fail(422, "refused", "a duplicate of a message sent 2 s ago"))
    result = _sender(bot).send(sg.OWNER, "x")
    assert result.ok and result.message_id is None and result.attempts == 2


def test_a_lost_answer_then_a_success_is_a_success():
    bot = _Script(httpx.ReadTimeout, _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert result.ok and result.message_id == TS


def test_after_an_ambiguous_failure_only_one_further_attempt_is_made():
    bot = _Script(httpx.ReadTimeout, httpx.ReadTimeout, _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and not result.permanent
    assert result.attempts == 2 and len(bot.requests) == 2


def test_an_ambiguous_failure_late_does_not_extend_the_budget():
    bot = _Script(httpx.ConnectError, httpx.ReadTimeout, httpx.ReadTimeout, _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and result.attempts == 3 and len(bot.requests) == 3


@pytest.mark.parametrize("first", [httpx.ConnectError, _fail(502, "unavailable", "down")],
                         ids=["connect-error", "502"])
def test_a_422_after_a_failure_that_was_not_ambiguous_is_a_refusal(first):
    # Neither a refused connection nor a 5xx can have sent the message, so a
    # 422 after one is the bot refusing this request, not a duplicate.
    sentence = "Smylte has sent 30 messages this hour, its limit."
    bot = _Script(first, _fail(422, "refused", sentence))
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and result.permanent
    assert sentence in result.error


def test_a_5xx_after_an_ambiguous_failure_was_the_one_further_attempt():
    bot = _Script(httpx.ReadTimeout, _fail(502, "unavailable", "down"), _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and result.attempts == 2 and len(bot.requests) == 2


# ── what fails at once ───────────────────────────────────────────────────────

def test_a_422_on_the_first_attempt_is_permanent():
    sentence = "Smylte has sent 30 messages this hour, its limit."
    bot = _Script(_fail(422, "refused", sentence), _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and result.permanent
    assert len(bot.requests) == 1
    assert sentence in result.error and result.error.startswith("HTTP 422 refused: ")


@pytest.mark.parametrize("status,code", [(400, "invalid"), (401, "unauthorized"),
                                         (403, "forbidden"), (404, "unknown")])
def test_a_configuration_failure_is_permanent_and_tried_once(status, code):
    bot = _Script(_fail(status, code, "a sentence"), _ok())
    result = _sender(bot).send(sg.OWNER, "x")
    assert not result.ok and result.permanent
    assert len(bot.requests) == 1
    assert result.error == f"HTTP {status} {code}: a sentence"


def test_a_non_json_4xx_says_so():
    bot = _Script(httpx.Response(401, text="nope"))
    result = _sender(bot).send(sg.OWNER, "x")
    assert result.permanent and result.error == "HTTP 401: non-JSON response"


def test_a_long_sentence_is_cut():
    bot = _Script(_fail(400, "invalid", "y" * 1000))
    result = _sender(bot).send(sg.OWNER, "x")
    assert result.error == "HTTP 400 invalid: " + "y" * 300


@pytest.mark.parametrize("token", ["", "   "])
def test_no_token_fails_permanently_without_a_request(token):
    bot = _Script(_ok())
    result = _sender(bot, token=token).send(sg.OWNER, "x")
    assert not result.ok and result.permanent
    assert result.error == "no signal-bot token configured"
    assert bot.requests == []


@pytest.mark.parametrize("token", ["sig token", "sig\ntoken", "sig\ttoken", "sigé"])
def test_a_token_that_cannot_go_in_a_header_is_refused_without_a_request(token):
    bot = _Script(_ok())
    result = _sender(bot, token=token).send(sg.OWNER, "x")
    assert not result.ok and result.permanent
    assert "cannot go in a header" in result.error
    assert bot.requests == []


def test_an_empty_message_is_refused_rather_than_sent():
    bot = _Script(_ok())
    result = _sender(bot).send(sg.OWNER, "   ")
    assert not result.ok and result.permanent
    assert result.error == "refusing to send an empty message"
    assert bot.requests == []


def test_the_token_setter_strips():
    sender = _sender(_Script(_ok()), token="")
    assert sender.configured is False
    sender.token = "  abc  \n"
    assert sender.token == "abc" and sender.configured is True


# ── the token never escapes ──────────────────────────────────────────────────

@pytest.mark.parametrize("exc", [httpx.ConnectError, httpx.ReadTimeout,
                                 httpx.RemoteProtocolError, httpx.LocalProtocolError])
def test_an_exception_carrying_the_token_is_redacted(exc):
    def handler(request):
        raise exc(f"refused with {TOKEN} in hand", request=request)

    result = _sender(handler).send(sg.OWNER, "x")
    assert not result.ok
    assert TOKEN not in result.error and "<redacted>" in result.error


def test_an_error_body_echoing_the_token_is_redacted():
    bot = _Script(_fail(401, "unauthorized", f"{TOKEN} belongs to no source"))
    result = _sender(bot).send(sg.OWNER, "x")
    assert TOKEN not in result.error and "<redacted>" in result.error


def test_a_bearer_header_in_a_body_is_redacted():
    other = "someone-elses-token-0123456789"
    bot = _Script(_fail(400, "invalid", f"saw Authorization: Bearer {other} in the request"))
    result = _sender(bot).send(sg.OWNER, "x")
    assert other not in result.error and "Bearer <redacted>" in result.error


def test_a_token_straddling_the_cut_leaves_no_prefix():
    bot = _Script(_fail(400, "invalid", "z" * 290 + TOKEN))
    result = _sender(bot).send(sg.OWNER, "x")
    assert TOKEN[:10] not in result.error


def test_the_client_ignores_proxy_settings_in_the_environment(monkeypatch):
    # With trust_env on, HTTP(S)_PROXY would route the bearer token through it.
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    sender = _sender(_Script(_ok()))
    assert sender._http.trust_env is False


# ── the loopback rule ────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,normalised", [
    ("http://127.0.0.1:8801", "http://127.0.0.1:8801"),
    ("http://localhost:9000/", "http://localhost:9000"),
    ("http://[::1]:8801", "http://[::1]:8801"),
    ("https://LOCALHOST", "https://localhost"),
])
def test_loopback_urls_are_accepted(url, normalised):
    assert sg.loopback_url(url) == normalised


@pytest.mark.parametrize("url", [
    "http://example.com",
    "http://127.0.0.1.example.com",
    "http://user:pw@127.0.0.1",
    "http://10.0.0.1:8801",
    "ftp://127.0.0.1",
    "http://127.0.0.1/v1",
    "http://127.0.0.1/?a=1",
])
def test_anything_else_is_refused(url):
    with pytest.raises(ValueError) as err:
        sg.loopback_url(url)
    assert "signal-bot URL" in str(err.value)
    assert "pw" not in str(err.value)


def test_a_bad_url_refuses_to_build_a_sender():
    with pytest.raises(ValueError):
        sg.SignalSender("http://example.com:8801")


# ── the ceiling ──────────────────────────────────────────────────────────────

def test_an_over_long_message_is_clipped_rather_than_dropped():
    bot = _Script(_ok())
    body = "\n".join(f"line {i} with some padding to make it long" for i in range(500))
    assert len(body) > tp.MAX_MESSAGE_CHARS
    assert _sender(bot).send(sg.OWNER, body).ok
    text = json.loads(bot.requests[0].read())["text"]
    assert len(text) <= tp.MAX_MESSAGE_CHARS
    assert text.endswith("(clipped)")


def test_a_message_at_the_limit_is_untouched():
    body = "x" * tp.MAX_MESSAGE_CHARS
    assert tp.clip(body) == body
    assert tp.clip("short") == "short"


def test_clipping_prefers_a_line_break():
    body = ("a" * 100 + "\n") * 60          # comfortably over the cap
    out = tp.clip(body)
    assert out.endswith(tp._CLIP_MARKER)
    assert out[: -len(tp._CLIP_MARKER)].endswith("a")
