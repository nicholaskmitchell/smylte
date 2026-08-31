"""Telegram Bot API sender — the first notification transport.

Borrowed from Søren's `src/soren/tools/builtin/telegram.py` and adapted, in
three ways that all come from the same difference: Søren's version is a *tool an
agent calls while someone is watching*, and this one runs unattended.

1. **Synchronous.** Søren's is `async` because the agent loop is. Here the house
   pattern for outbound HTTP is `dav.client` — a synchronous `httpx.Client`
   reached from FastAPI through `asyncio.to_thread`. Matching it keeps one
   threading discipline in the process instead of two, and keeps the retry
   sleeps below off the event loop (see tests/test_loop_blocking.py).

2. **Retries.** A tool call that fails is seen by the agent that made it, which
   can try again or say so. A notification that fails at 03:00 is seen by
   nobody, so a 429 or a 502 has to be retried *here* or the alert is simply
   lost. Telegram's 429 carries `parameters.retry_after`; we honour that number
   rather than guessing at a backoff it already told us.

3. **A redacted error surface.** The bot token sits in the request PATH
   (`/bot<TOKEN>/sendMessage`), so an httpx exception string, a logged URL and a
   `repr()` of a response all carry the credential. Søren returns
   `f"{type(exc).__name__}: {exc}"` straight to the model, where a human reads
   it once; the same string here would land in the app log and in the delivery
   ledger — two durable copies of the bot token, in a file the schema header
   promises will not yield a working credential when read. `_redact` is a
   security control, not tidiness.

`silent` is first-class for the reason the whole notification policy exists: a
channel that buzzes for everything gets muted, and then it stops working at all.
Anything worth recording but not worth interrupting for goes out with
`disable_notification`, lands in the chat, and waits to be read.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

API_ORIGIN = "https://api.telegram.org"

# Telegram's hard cap on a message body. Søren *refuses* a longer message, which
# is right for a tool — the agent sees the refusal and rewrites. Unattended, a
# refusal is a dropped alert, so we clip instead and say so in the text. The
# real defence is upstream: a notification that approaches this is a report, and
# a report should be a headline plus where the detail lives.
MAX_MESSAGE_CHARS = 4096
_CLIP_MARKER = "\n… (clipped)"

# Longest we will honour a 429's retry_after. Beyond this the moment the
# notification was about has usually passed, and holding a worker thread for
# minutes to deliver a stale "starting in 10 minutes" is worse than failing.
MAX_RETRY_AFTER_S = 60.0

_TOKEN_IN_URL = re.compile(r"/bot[0-9]{5,}:[A-Za-z0-9_-]{10,}", re.I)
# A bare token, in case one reaches us outside a URL (a JSON error echoing the
# request, a stray f-string). Matches Telegram's `<bot_id>:<secret>` shape.
_BARE_TOKEN = re.compile(r"\b[0-9]{5,}:[A-Za-z0-9_-]{30,}\b")


def _redact(text: str, token: str = "") -> str:
    """Strip anything token-shaped out of a string bound for a log or the ledger."""
    out = _TOKEN_IN_URL.sub("/bot<redacted>", text or "")
    out = _BARE_TOKEN.sub("<redacted>", out)
    if token:
        # Belt and braces: the configured token itself, however it got in.
        out = out.replace(token, "<redacted>")
    return out


def clip(text: str) -> str:
    """Cut `text` to what Telegram will accept, on a line break where possible."""
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    budget = MAX_MESSAGE_CHARS - len(_CLIP_MARKER)
    head = text[:budget]
    # Prefer the last line break in the final fifth, so we cut between thoughts
    # rather than mid-word; fall back to a hard cut if there is none.
    cut = head.rfind("\n", int(budget * 0.8))
    if cut > 0:
        head = head[:cut]
    return head + _CLIP_MARKER


def escape_html(text: str) -> str:
    """Escape a body for `parse_mode=HTML`.

    Telegram rejects the whole send when the markup is malformed, so an
    unescaped `<` in a title is a notification that never arrives. Plain text is
    the default everywhere for exactly this reason; this exists for the few
    places a link or a monospaced path earns the risk.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass(frozen=True)
class SendResult:
    """What happened, in the form the delivery ledger stores.

    `permanent` is the field the scheduler acts on: a 400 ("chat not found") or
    a 403 ("bot was blocked by the user") will fail identically forever, and
    retrying it every minute turns a misconfiguration into a rate-limit ban.
    """
    ok: bool
    message_id: int | None = None
    error: str | None = None          # already redacted; safe to log and store
    attempts: int = 0
    permanent: bool = False


class TelegramSender:
    """A long-lived Bot API client. One per process, held on `app.state`."""

    def __init__(
        self,
        token: str,
        *,
        timeout: float = 15.0,
        max_attempts: int = 4,
        origin: str = API_ORIGIN,
        sleep=time.sleep,          # injected so tests do not actually wait
        transport: httpx.BaseTransport | None = None,   # httpx.MockTransport in tests
    ) -> None:
        self._token = (token or "").strip()
        self._origin = origin.rstrip("/")
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep
        self._http = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "tasksd-notify/0.1"},
            follow_redirects=False,
            transport=transport,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token)

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        """Adopt a new bot token, keeping the connection pool.

        Settable because the token can now be typed into Settings and must take
        effect on the next sweep rather than at the next restart. Rebuilding the
        whole sender per sweep would discard the httpx pool — and the redaction
        below reads `self._token`, so it has to be the one the last request
        actually used, not one captured at construction."""
        self._token = (value or "").strip()

    def close(self) -> None:
        self._http.close()

    # ── the one call the rest of the app makes ───────────────────────────────
    def send(
        self,
        chat_id: int | str,
        text: str,
        *,
        silent: bool = False,
        parse_mode: str | None = None,
        reply_to: int | None = None,
    ) -> SendResult:
        """Deliver one message. Never raises: the caller is a background loop
        whose job is to record an outcome, not to crash on a bad network."""
        if not self._token:
            return SendResult(False, error="no bot token configured", permanent=True)
        body = (text or "").strip()
        if not body:
            return SendResult(False, error="refusing to send an empty message", permanent=True)

        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": clip(body),
            "disable_notification": bool(silent),
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to is not None:
            # allow_sending_without_reply: the thread we were replying into may
            # have been deleted, and losing the alert over a missing parent is
            # the wrong trade.
            payload["reply_to_message_id"] = reply_to
            payload["allow_sending_without_reply"] = True

        return self._post("sendMessage", payload)

    # ── transport ────────────────────────────────────────────────────────────
    def _post(self, method: str, payload: dict[str, object]) -> SendResult:
        url = f"{self._origin}/bot{self._token}/{method}"
        last = "no attempt made"
        for attempt in range(1, self._max_attempts + 1):
            try:
                resp = self._http.post(url, json=payload)
            except httpx.HTTPError as exc:
                # Connection reset, DNS, timeout — transient by nature, and the
                # exception text carries the URL (and so the token).
                last = _redact(f"{type(exc).__name__}: {exc}", self._token)
                if attempt < self._max_attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                return SendResult(False, error=last, attempts=attempt)

            outcome = self._read(resp)
            if outcome.ok or outcome.permanent or attempt >= self._max_attempts:
                return SendResult(
                    outcome.ok, outcome.message_id, outcome.error, attempt, outcome.permanent
                )
            last = outcome.error or "retryable failure"
            self._sleep(self._retry_delay(resp, attempt))
        return SendResult(False, error=last, attempts=self._max_attempts)

    def _read(self, resp: httpx.Response) -> SendResult:
        """Turn one HTTP response into an outcome, without leaking the token."""
        try:
            data = resp.json()
        except ValueError:
            # Telegram fronted by something that answered HTML (a proxy error
            # page). Body is not ours to trust or to log wholesale.
            return SendResult(
                False,
                error=f"HTTP {resp.status_code}: non-JSON response",
                permanent=False,
            )
        if isinstance(data, dict) and data.get("ok"):
            result = data.get("result") or {}
            mid = result.get("message_id") if isinstance(result, dict) else None
            return SendResult(True, message_id=mid if isinstance(mid, int) else None)

        desc = ""
        code = resp.status_code
        if isinstance(data, dict):
            desc = str(data.get("description") or "")
            code = int(data.get("error_code") or resp.status_code)
        return SendResult(
            False,
            error=_redact(f"HTTP {code}: {desc or 'unknown error'}", self._token),
            permanent=self._is_permanent(code),
        )

    @staticmethod
    def _is_permanent(code: int) -> bool:
        """True when trying again cannot help.

        400 is a malformed request or an unknown chat; 401/404 is a bad token;
        403 is the bot blocked or removed from the chat. All four are
        configuration, and a background loop that retries them forever earns a
        rate-limit ban for a message that was never going to land. 429 and 5xx
        are explicitly *not* here.
        """
        return code in (400, 401, 403, 404)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0 ** (attempt - 1), 8.0)

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        """Honour Telegram's own `retry_after` on a 429; back off otherwise."""
        try:
            data = resp.json()
            after = float(data["parameters"]["retry_after"])
        except (ValueError, KeyError, TypeError):
            return self._backoff(attempt)
        return max(0.0, min(after, MAX_RETRY_AFTER_S))
