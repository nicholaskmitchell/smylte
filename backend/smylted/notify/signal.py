"""The signal-bot sender — notifications through the owner's own Signal bot.

Why a local bot rather than a messaging service's public API. The account that
sends is the owner's own signal-bot, running on this machine and listening on
loopback only (127.0.0.1:8801), so a notification never needs the service to
reach the internet and the sandbox in deploy/smylte.service stays as tight as
it is. Smylte is one *source* on that bot: it holds a source token, kept in the
encrypted secret store (smylted/mail/secrets.py) or supplied by
SMYLTE_SIGNAL_TOKEN, never in smylte.db. The bot labels every message with the
source's name ("Smylte: "), so no text here carries it; it rate-limits each
source (30 an hour) and refuses the same text twice within a minute, so a sweep
stuck in a loop cannot flood the owner's phone; and Signal carries the message
end to end encrypted.

Synchronous, like the sender it replaced: the house pattern for outbound HTTP is
`dav.client`, a synchronous `httpx.Client` reached from FastAPI through
`asyncio.to_thread`. Matching it keeps one threading discipline in the process
instead of two, and keeps the retry sleeps below off the event loop (see
tests/test_loop_blocking.py).

Retries, because a notification that fails at 03:00 is seen by nobody. At most
three attempts, 1 s and then 2 s apart:

- The request never reached the bot (`ConnectError`, `ConnectTimeout`): retry.
- Any other transport failure (a read timeout, a dropped connection) is
  AMBIGUOUS — the bot may have sent the message before the answer was lost. One
  further attempt only. If that attempt is refused with 422, the bot refused a
  duplicate, which means the first one was delivered: report it sent.
- A 2xx that is not `{"ok": true}`, or a 5xx: retry.
- Any other HTTP error, and 400, 401, 403, 404, 422 and every other 4xx:
  permanent. The same request fails the same way until the configuration
  changes, and retrying it every minute only spends the bot's rate limit.

Every error string is redacted before it leaves this module (`_redact`): the
ledger and the app log both store it, and neither may hold a working token.

`silent` is first-class for the reason the whole notification policy exists: a
channel that buzzes for everything gets muted, and then it stops working at all.
Anything worth recording but not worth interrupting for goes out silent, lands
in the chat, and waits to be read.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

import httpx

from .transport import SendResult, clip

DEFAULT_URL = "http://127.0.0.1:8801"
OWNER = "owner"                      # signal-bot's name for the owner's own chat

MAX_ATTEMPTS = 3
# The wait before attempt 2, and before attempt 3.
_DELAYS = (1.0, 2.0)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
# Printable ASCII with no spaces: everything else either cannot go in an HTTP
# header (httpx raises) or is a paste that picked up something it should not.
_HEADER_SAFE = re.compile(r"[\x21-\x7e]+")
_BEARER = re.compile(r"(?i)bearer\s+\S+")
_SENTENCE_MAX = 300
_CODE_MAX = 40


def loopback_url(url: str) -> str:
    """The bot's base URL, normalised (scheme://host[:port], no trailing slash).

    ValueError, with a sentence naming the rule, unless the URL is http or
    https, its host is 127.0.0.1, ::1 or localhost (any case; ::1 written
    [::1]), and it has no user info, query, fragment, or path other than "" or
    "/". The URL is never repeated in the sentence: a URL with user info in it
    carries a password.
    """
    raw = (url or "").strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise ValueError(
            "the signal-bot URL is not a URL; give it as http://127.0.0.1:8801") from None
    if parts.scheme not in ("http", "https"):
        raise ValueError("the signal-bot URL must start with http:// or https://")
    if "@" in parts.netloc:
        raise ValueError("the signal-bot URL must not carry a user name or password")
    host = (parts.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS or (host == "::1" and "[" not in parts.netloc):
        raise ValueError(
            "the signal-bot URL must name this machine (127.0.0.1, [::1] or localhost); "
            "signal-bot listens on loopback only")
    if parts.query or parts.fragment or "?" in raw or "#" in raw:
        raise ValueError("the signal-bot URL must not have a query or a fragment")
    if parts.path not in ("", "/"):
        raise ValueError("the signal-bot URL must not have a path; give only scheme://host:port")
    netloc = f"[{host}]" if host == "::1" else host
    if port is not None:
        netloc += f":{port}"
    return f"{parts.scheme}://{netloc}"


def _redact(text: str, token: str) -> str:
    """Strip the token, and anything that looks like a bearer credential, out of
    a string bound for a log or the ledger."""
    out = text or ""
    if token:
        out = out.replace(token, "<redacted>")
    return _BEARER.sub("Bearer <redacted>", out)


class SignalSender:
    """A long-lived client for the bot's HTTP API. One per process."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        token: str = "",
        *,
        timeout: float = 10.0,
        sleep=time.sleep,          # injected so tests do not actually wait
        transport: httpx.BaseTransport | None = None,   # httpx.MockTransport in tests
    ) -> None:
        self._base = loopback_url(url)
        self._token = (token or "").strip()
        self._sleep = sleep
        self._http = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "smylted-notify/0.2"},
            follow_redirects=False,
            # A security control, not a default: with trust_env on, an
            # HTTP_PROXY or HTTPS_PROXY in the service's environment would route
            # this request — and the bearer token in its header — through that
            # proxy, off the machine the bot runs on.
            trust_env=False,
            transport=transport,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token)

    @property
    def base_url(self) -> str:
        """The bot's normalised base URL (no token in it; safe to show)."""
        return self._base

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        """Adopt a new source token, keeping the connection pool.

        Settable because the token can be pasted into Settings and must take
        effect on the next sweep rather than at the next restart. Rebuilding the
        whole sender per sweep would discard the httpx pool — and the redaction
        below reads `self._token`, so it has to be the one the last request
        actually used, not one captured at construction."""
        self._token = (value or "").strip()

    def close(self) -> None:
        self._http.close()

    # ── the one call the rest of the app makes ───────────────────────────────
    def send(self, chat_id: str, text: str, *, silent: bool = False) -> SendResult:
        """Deliver one message. Never raises: the caller is a background loop
        whose job is to record an outcome, not to crash on a bad network."""
        token = self._token
        if not token:
            return SendResult(False, error="no signal-bot token configured", permanent=True)
        if not _HEADER_SAFE.fullmatch(token):
            return SendResult(
                False,
                error="the signal-bot token contains a character that cannot go in a header; "
                      "paste it again",
                permanent=True,
            )
        body = (text or "").strip()
        if not body:
            return SendResult(False, error="refusing to send an empty message", permanent=True)
        payload = {"text": clip(body), "chat_id": chat_id, "silent": bool(silent)}
        return self._post(payload, token)

    # ── transport ────────────────────────────────────────────────────────────
    def _post(self, payload: dict[str, object], token: str) -> SendResult:
        url = f"{self._base}/v1/send"
        headers = {"Authorization": f"Bearer {token}"}
        last = "no attempt made"
        last_status: int | None = None
        budget = MAX_ATTEMPTS
        ambiguous = False
        attempt = 0
        while attempt < budget:
            attempt += 1
            if attempt > 1:
                self._sleep(_DELAYS[attempt - 2])
            try:
                resp = self._http.post(url, json=payload, headers=headers)
                status = resp.status_code
                last_status = status
                if 200 <= status < 300:
                    data = _json(resp)
                    if isinstance(data, dict) and data.get("ok") is True:
                        result = data.get("result")
                        ts = result.get("timestamp") if isinstance(result, dict) else None
                        # signal-bot's send timestamp (ms). Anything else, or a value
                        # the ledger's INTEGER column cannot hold, names no message.
                        mid = (ts if isinstance(ts, int) and not isinstance(ts, bool)
                               and 0 < ts < 2**63 else None)
                        return SendResult(True, message_id=mid, attempts=attempt, status=status)
                    last = _redact(f"HTTP {status}: unexpected response", token)
                    continue
                if status == 422 and ambiguous:
                    # The bot refuses the same text from the same source within 60 s,
                    # so a refusal right after an ambiguous failure says the earlier
                    # attempt was delivered. A 422 here could in principle be the
                    # rate limit instead; a duplicate is far likelier, and a duplicate
                    # 3 am alert is worse than a missed one (scheduler.py's docstring).
                    return SendResult(True, message_id=None, attempts=attempt, status=status)
                error = _redact(_describe(resp, token), token)
                if status >= 500:
                    last = error
                    continue
                return SendResult(False, error=error, attempts=attempt, permanent=True,
                                  status=status)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The request never reached the bot, so nothing was sent.
                last = _redact(f"{type(exc).__name__}: {exc}", token)
                continue
            except (httpx.InvalidURL, httpx.UnsupportedProtocol, httpx.LocalProtocolError) as exc:
                # Our own request is malformed; it fails the same way every time.
                # `InvalidURL` is not an `httpx.HTTPError` in httpx 0.28, so it
                # is named here or it would escape "never raises".
                return SendResult(False, error=_redact(f"{type(exc).__name__}: {exc}", token),
                                  attempts=attempt, permanent=True, status=last_status)
            except httpx.TransportError as exc:
                # AMBIGUOUS: the request may have reached the bot and the bot may
                # have sent it; only the answer was lost. One further attempt in
                # total from here, however many were left.
                last = _redact(f"{type(exc).__name__}: {exc}", token)
                if not ambiguous:
                    ambiguous = True
                    budget = min(budget, attempt + 1)
                continue
            except httpx.HTTPError as exc:
                return SendResult(False, error=_redact(f"{type(exc).__name__}: {exc}", token),
                                  attempts=attempt, permanent=True, status=last_status)
            except Exception as exc:  # noqa: BLE001
                # The last resort behind "never raises": a surprise from the
                # client or from reading the answer. Not permanent, because
                # nothing says the configuration is wrong; and no further
                # attempt, because nothing says the bot did not send it.
                return SendResult(False, error=_redact(f"{type(exc).__name__}: {exc}", token),
                                  attempts=attempt, status=last_status)
        return SendResult(False, error=last, attempts=attempt, permanent=False,
                          status=last_status)


def _json(resp: httpx.Response):
    try:
        return resp.json()
    except (ValueError, RecursionError):
        # Not JSON, or nested too deep to parse: either way, not the bot's answer.
        return None


def _describe(resp: httpx.Response, token: str) -> str:
    """The bot's own account of a failure, from its `{code, error}` body.

    The code and the sentence are each redacted BEFORE they are cut, so a token
    straddling the cut cannot leave a prefix of itself behind."""
    data = _json(resp)
    if isinstance(data, dict):
        code = _redact(str(data.get("code", "")), token)[:_CODE_MAX]
        sentence = _redact(str(data.get("error", "")), token)[:_SENTENCE_MAX]
        return f"HTTP {resp.status_code} {code}: {sentence}"
    return f"HTTP {resp.status_code}: non-JSON response"
