"""Keep the two mail secrets out of every log line, error and traceback.

A security control, not tidiness — the same position `notify/telegram.py` takes
about its bot token, applied more broadly because there are more ways out here.
An Anthropic key or a Bridge password can leave the process in:

- an exception message (`imaplib` echoes what the server said back; an
  `httpx2` error can carry a URL; our own "could not log in as …" sentences),
- a traceback, which repeats that message and is written by whoever catches it
  — uvicorn, asyncio, a background loop — not by the code that knew it was
  holding a secret,
- a log record's arguments, formatted long after the call site returned.

So redaction happens at the one place every record passes through: the
`logging` record factory. `install_log_redaction()` wraps it once per process,
and from then on any record from ANY logger — ours, uvicorn's, the SDK's —
whose message, exception text or stack carries a registered secret is
rewritten before a handler sees it. A record that carries no secret is left
exactly as it was created (its `exc_info` intact), so this costs the rest of
the app nothing but a substring check.

The registry holds every secret value the process has seen: values read from
the store or the environment, and values just written. It never shrinks. A key
the owner replaced is still a key worth keeping out of the journal.

Values shorter than `MIN_LEN` are not registered: replacing every "abc" in
every log line would mangle the log without protecting anything a three-letter
password could protect.
"""
from __future__ import annotations

import logging
import re
import threading
import traceback

REDACTED = "<redacted>"
MIN_LEN = 6

_lock = threading.Lock()
_secrets: tuple[str, ...] = ()          # longest first, so a secret that
                                        # contains another is replaced whole

# Shapes worth redacting even when the value was never registered — a key
# pasted into the wrong field, or one arriving in an SDK error before the store
# has been read.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Anthropic API keys and admin keys.
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-" + REDACTED),
    # An IMAP LOGIN command echoed back: `<tag> LOGIN <user> <password>`, the
    # password quoted or bare. Case-sensitive and tag-anchored on purpose, so
    # an ordinary sentence that says "login" is left alone.
    (re.compile(r'(\b[A-Za-z0-9]{1,16} LOGIN (?:"(?:[^"\\]|\\.)*"|\S+) )'
                r'("(?:[^"\\]|\\.)*"|\S+)'),
     r"\1" + REDACTED),
    # SASL PLAIN carries user and password, base64'd, on one line.
    (re.compile(r"(\bAUTHENTICATE PLAIN )\S+"), r"\1" + REDACTED),
)


def register_secret(value: str | None) -> None:
    """Remember `value` so it is redacted from now on. Idempotent."""
    global _secrets
    v = (value or "").strip()
    if len(v) < MIN_LEN:
        return
    with _lock:
        if v in _secrets:
            return
        _secrets = tuple(sorted({*_secrets, v}, key=len, reverse=True))


def forget_all_for_tests() -> None:
    """Empty the registry. Tests only — production never forgets a secret."""
    global _secrets
    with _lock:
        _secrets = ()


def redact(text: object) -> str:
    """`str(text)` with every registered secret and known secret shape removed."""
    out = text if isinstance(text, str) else str(text)
    for secret in _secrets:              # a snapshot: the tuple is replaced, never mutated
        if secret in out:
            out = out.replace(secret, REDACTED)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_exc(exc: BaseException) -> str:
    """`ExcType: message`, redacted — the form error sentences quote."""
    return redact(f"{type(exc).__name__}: {exc}")


def _scrub(record: logging.LogRecord) -> logging.LogRecord:
    """Rewrite `record` in place if, and only if, it carries a secret."""
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001 — a bad format string is the caller's bug, not ours to raise
        message = str(record.msg)
    clean = redact(message)
    if clean != message:
        record.msg = clean
        record.args = ()
    if record.exc_info and record.exc_info[0] is not None:
        text = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
        clean_exc = redact(text)
        if clean_exc != text:
            # The formatted, redacted traceback replaces the live one: a handler
            # that re-formats `exc_info` would print the secret again.
            record.exc_text = clean_exc
            record.exc_info = None
    elif record.exc_text:
        record.exc_text = redact(record.exc_text)
    if record.stack_info:
        record.stack_info = redact(record.stack_info)
    return record


class RedactingFilter(logging.Filter):
    """The same scrub as a filter, for a handler installed outside this process's
    record factory (a test harness, a custom logging config)."""

    def filter(self, record: logging.LogRecord) -> bool:
        _scrub(record)
        return True


_installed = False


def install_log_redaction() -> None:
    """Wrap the logging record factory so every record is scrubbed. Idempotent."""
    global _installed
    with _lock:
        if _installed:
            return
        previous = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            return _scrub(previous(*args, **kwargs))

        logging.setLogRecordFactory(factory)
        _installed = True
