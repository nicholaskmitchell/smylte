"""TypeSafe's Jev, asked two narrow questions about an email the model has read.

Jev (https://docs.typesafe.ai) is a decision model: it takes a `state` and
typed questions and, for a Choice question, returns the chosen option, a
probability per option and a calibrated confidence; for a Noul (yes/no)
question, the probability of yes. It never writes text, which is why it is
trusted with decisions and nothing else: its answer is confined to a closed
set, so the worst an email that talks to it can do is flip task and event, or
"new" and "same", on a suggestion the owner still has to approve.

The two questions, and the thresholds, are the ones measured against labelled
mail in `dev/mail_eval/README.md` (the harness is `dev/mail_eval.py`; change
one and the other together, or the numbers no longer describe this code):

- **Task or event** (`decide_kind`). Jev's answer stands only at confidence
  `MIN_CONFIDENCE` (0.7) or more; below it the extraction model decides. That
  split beat either alone (65 of 66 against 62–63).
- **Is this the same piece of work as one already there?** (`match`). One
  Noul per candidate; for the best one, a second request asks whether `new`
  changes anything about `existing`. Whether the deadline moved is compared in
  code, not by Jev. In the `UNSURE` band the pipeline asks Claude instead.
  Measured: never merged new work into an existing task, where Claude alone
  did 4 times in 98. Asking "does `new_item` add details not in
  `candidates.C1`?" inside the candidate list was tried and rejected: Jev
  fired on plain rewordings.

What is known about Jev shapes how it is asked:

- **It can lean toward the first option**, so a Choice is asked twice in one
  request, with the options in both orders, and the two answers are combined.
  When they disagree the kind verdict's confidence is 0 and the pipeline keeps
  the extraction model's choice; asking once would hide that disagreement
  behind a confident-looking number.
- **It is weaker at date arithmetic**, so it is shown the dates the extraction
  already resolved and never asked to compare them; dates stay with the
  extraction model and our code.
- **It does not treat the state as hostile**, which the closed answer sets
  above make tolerable.

Plain synchronous `httpx`, the house pattern for outbound HTTP (see
`smylted/notify/telegram.py`), not the `typesafe-sdk` package: the API is one
POST, and another SDK is supply-chain surface for no gain. 429, 529 and other
5xx answers and network errors are retried with a short backoff here, because
the pipeline runs unattended; a failure after that is a `JevError` the pipeline
turns into "let the model decide", never a stopped run.

The key is read through a provider on every call, so a key saved in Settings
applies to the next email. It is registered with `redact` before it is used,
and every error message leaving this module passes through `redact`. Nothing
here logs the key, the email, or a response body.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from .redact import redact, redact_exc, register_secret

log = logging.getLogger("smylted.mail")

API_ORIGIN = "https://api.typesafe.ai"
DEFAULT_JEV_MODEL = "jev-latest"
MIN_CONFIDENCE = 0.7          # measured, see dev/mail_eval/README.md
KIND_CRITERIA = {
    "event": "Something that happens at a particular time the owner should attend or keep free: a meeting, appointment, parent evening, match, call.",
    "task": "Work the owner has to do, with or without a deadline: reply, pay, sign, submit, bring, book, review, decide.",
}
KIND_INSTRUCTIONS = "Should the request in `email` go on the owner's calendar as an event, or on their to-do list as a task?"

# The duplicate check, exactly as dev/mail_eval.py::run_dedup asks it.
SAME_T = 0.5                  # a candidate is "the same work" at p >= this
UNSURE = (0.35, 0.65)         # best match in this band: Claude decides instead
CHANGED_T = 0.5               # "new changes something" at p >= this
CHANGED_INSTRUCTIONS = "`new` and `existing` describe the same piece of work. Does `new` change anything about it?"
CHANGED_CRITERIA = {
    "same": "Nothing changes: `new` only rewords `existing`, or repeats details `existing` already has.",
    "changed": "Something changes or is added: a different or newly stated deadline, amount, place, time, quantity, recipient, or an extra requirement.",
}
MAX_CANDIDATES = 15

KINDS = ("task", "event")
DETAIL_MAX = 300
MAX_RETRY_AFTER_S = 10.0

_RETRYABLE = frozenset({429, 529})
_NOT_UNDERSTOOD = "TypeSafe returned an answer this code does not understand"
_BAD_KEY_CHARS = "the TypeSafe key contains a character that cannot go in a header; paste it again"


class JevError(Exception):
    """A failed Jev call, sorted like `llm.LlmError`.

    `kind` is "config" (the owner must fix the key or the model), "transient"
    (TypeSafe is busy or unreachable) or "permanent" (this request will not
    work as sent). The message is redacted on the way in, so `str(err)` is safe
    to log, store in the ledger or return over HTTP.
    """

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(redact(message))
        self.kind = kind


@dataclass(frozen=True)
class KindVerdict:
    kind: str                     # "task" | "event"
    confidence: float             # min of the two answers' confidences, 0 when they disagree
    probabilities: dict[str, float]   # averaged over both orders
    model: str                    # the versioned model that answered, e.g. "jev-1.13.0"
    agreed: bool                  # both orders chose the same option


@dataclass(frozen=True)
class JevMatch:
    target: str | None            # the best candidate's label when p >= SAME_T, else None
    p: float                      # that candidate's p(same)
    unsure: bool                  # UNSURE[0] <= p < UNSURE[1]
    changed: float | None         # averaged p("changed") for the target (None when not asked)
    model: str                    # the versioned model that answered


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _answer(answers: Mapping, qid: str) -> tuple[str, float, dict[str, float]]:
    """One Choice answer as `(choice, confidence, probabilities)`; JevError otherwise."""
    a = answers.get(qid)
    if not isinstance(a, Mapping) or a.get("type") != "choice" or a.get("choice") not in KINDS:
        raise JevError(_NOT_UNDERSTOOD, kind="permanent")
    confidence = _number(a.get("confidence"))
    probs = a.get("probabilities")
    if confidence is None or not isinstance(probs, Mapping):
        raise JevError(_NOT_UNDERSTOOD, kind="permanent")
    out: dict[str, float] = {}
    for option in KINDS:
        p = _number(probs.get(option))
        if p is None:
            raise JevError(_NOT_UNDERSTOOD, kind="permanent")
        out[option] = p
    return a["choice"], min(1.0, max(0.0, confidence)), out


def _verdict(data: object, *, requested_model: str) -> KindVerdict:
    """The two answers to the kind question, combined into one verdict.

    Probabilities are averaged over both orders and the kind is their argmax
    (a tie is a task, the cheaper mistake). The confidence is the lower of the
    two only when both orders chose the same option; otherwise it is 0.
    """
    if not isinstance(data, Mapping) or not isinstance(data.get("answers"), Mapping):
        raise JevError(_NOT_UNDERSTOOD, kind="permanent")
    choice_a, conf_a, probs_a = _answer(data["answers"], "kind_a")
    choice_b, conf_b, probs_b = _answer(data["answers"], "kind_b")
    probabilities = {k: (probs_a[k] + probs_b[k]) / 2 for k in KINDS}
    kind = "event" if probabilities["event"] > probabilities["task"] else "task"
    agreed = choice_a == choice_b
    return KindVerdict(
        kind=kind,
        confidence=min(conf_a, conf_b) if agreed else 0.0,
        probabilities=probabilities,
        model=_answered_model(data, requested_model),
        agreed=agreed,
    )


def _answered_model(data: Mapping, requested_model: str) -> str:
    model = data.get("model")
    return model[:100] if isinstance(model, str) and model else requested_model


def _probability(value: object) -> float:
    p = _number(value)
    if p is None or not 0.0 <= p <= 1.0:
        raise JevError(_NOT_UNDERSTOOD, kind="permanent")
    return p


def _answers(data: object) -> Mapping:
    if not isinstance(data, Mapping) or not isinstance(data.get("answers"), Mapping):
        raise JevError(_NOT_UNDERSTOOD, kind="permanent")
    return data["answers"]


def _same(answers: Mapping, qid: str) -> float:
    """p(yes) of one Noul answer; JevError otherwise."""
    a = answers.get(qid)
    if not isinstance(a, Mapping):
        raise JevError(_NOT_UNDERSTOOD, kind="permanent")
    return _probability(a.get("noul"))


def _changed(answers: Mapping, qid: str) -> float:
    """p("changed") of one Choice answer to the changed question; JevError otherwise."""
    a = answers.get(qid)
    if (not isinstance(a, Mapping) or a.get("type") != "choice"
            or not isinstance(a.get("probabilities"), Mapping)):
        raise JevError(_NOT_UNDERSTOOD, kind="permanent")
    return _probability(a["probabilities"].get("changed"))


def _item(x: Mapping) -> dict:
    """What Jev is shown of an item: its title, notes and due date, nothing else."""
    return {"title": x["title"], "notes": x["notes"], "due": x["due"]}


def _detail(response: httpx.Response) -> str:
    """The `detail` of an error answer as text, at most DETAIL_MAX characters."""
    try:
        body = response.json()
    except ValueError:
        return redact(response.text[:DETAIL_MAX])
    detail = body.get("detail", body) if isinstance(body, Mapping) else body
    return redact(str(detail)[:DETAIL_MAX])


def _retry_after(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    if not math.isfinite(seconds):
        return None
    return min(MAX_RETRY_AFTER_S, max(0.0, seconds))


class JevClient:
    """The pipeline's handle on Jev. One `httpx.Client` per instance."""

    def __init__(self, *, api_key_provider: Callable[[], str | None],
                 model_provider: Callable[[], str] = lambda: DEFAULT_JEV_MODEL,
                 timeout: float = 20.0, origin: str = API_ORIGIN, max_attempts: int = 3,
                 sleep=time.sleep, transport: httpx.BaseTransport | None = None) -> None:
        self._api_key_provider = api_key_provider
        self._model_provider = model_provider
        self._origin = origin.rstrip("/")
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep
        # The key goes on each request, not on the client, so a key changed in
        # Settings is used by the next call without rebuilding the pool.
        self._http = httpx.Client(timeout=timeout, follow_redirects=False, transport=transport,
                                  headers={"User-Agent": "smylted-mail/0.1"})

    def _key(self) -> str:
        key = (self._api_key_provider() or "").strip()
        if not key:
            raise JevError("no TypeSafe API key is set", kind="config")
        register_secret(key)
        if not (key.isascii() and key.isprintable()):
            raise JevError(_BAD_KEY_CHARS, kind="config")
        return key

    def _request(self, method: str, path: str, *, body: dict | None = None,
                 model: str | None = None) -> Any:
        """One API call with the retries described in the module docstring."""
        headers = {"Authorization": f"Bearer {self._key()}"}
        url = self._origin + path
        failure = ""
        for attempt in range(1, self._max_attempts + 1):
            response: httpx.Response | None = None
            try:
                response = self._http.request(method, url, json=body, headers=headers)
            except (httpx.InvalidURL, UnicodeEncodeError):
                raise JevError(_BAD_KEY_CHARS, kind="config") from None
            except httpx.HTTPError as exc:
                failure = f"could not reach TypeSafe ({redact_exc(exc)})"
            else:
                status = response.status_code
                if status == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise JevError(_NOT_UNDERSTOOD, kind="permanent") from None
                if status in (401, 403):
                    raise JevError("TypeSafe rejected the API key", kind="config")
                if status == 404:
                    if model is not None:
                        raise JevError(f"TypeSafe does not know the model {model!r}", kind="config")
                    raise JevError(f"TypeSafe does not know {path} (404)", kind="config")
                if status == 422:
                    raise JevError(f"TypeSafe refused the request: {_detail(response)}",
                                   kind="permanent")
                if status not in _RETRYABLE and status < 500:
                    raise JevError(f"TypeSafe refused the request ({status})", kind="permanent")
                failure = (f"TypeSafe is rate limiting requests ({status})" if status == 429
                           else f"TypeSafe is unavailable ({status})")
            if attempt == self._max_attempts:
                break
            delay = _retry_after(response)
            if delay is None:
                delay = float(min(2 ** (attempt - 1), 8))
            log.info("mail: %s; retrying in %.0fs (attempt %d of %d)",
                     redact(failure), delay, attempt, self._max_attempts)
            self._sleep(delay)
        raise JevError(failure, kind="transient")

    def decide_kind(self, *, subject: str, sender: str, body: str, title: str,
                    start: str | None, due: str | None) -> KindVerdict:
        """Ask Jev whether this email is a task or an event (both option orders, one call)."""
        model = self._model_provider()
        request = {
            "model": model,
            "state": {"email": {"from": sender, "subject": subject, "body": body},
                      "extracted": {"title": title, "start": start, "due": due}},
            "questions": {
                "kind_a": {"type": "choice", "instructions": KIND_INSTRUCTIONS,
                           "criteria": {"event": KIND_CRITERIA["event"],
                                        "task": KIND_CRITERIA["task"]}},
                "kind_b": {"type": "choice", "instructions": KIND_INSTRUCTIONS,
                           "criteria": {"task": KIND_CRITERIA["task"],
                                        "event": KIND_CRITERIA["event"]}},
            },
        }
        data = self._request("POST", "/v1/systemone", body=request, model=model)
        return _verdict(data, requested_model=model)

    def match(self, item: Mapping, candidates: Sequence[Mapping]) -> JevMatch:
        """Is `item` the same piece of work as one of `candidates`, and if so, does it change it?

        `item` and each candidate are `{"label", "title", "notes", "due"}` (due
        ISO or None; the item's label is not sent). One request asks a Noul per
        candidate; a second, only when the best candidate clears `SAME_T` and is
        not in the `UNSURE` band, asks the changed question in both option
        orders. Mirrors `dev/mail_eval.py::run_dedup`.
        """
        if not candidates or len(candidates) > MAX_CANDIDATES:
            raise ValueError(f"match needs 1 to {MAX_CANDIDATES} candidates")
        model = self._model_provider()
        labels = [x["label"] for x in candidates]
        request = {
            "model": model,
            "state": {"new_item": _item(item),
                      "candidates": {x["label"]: _item(x) for x in candidates}},
            "questions": {f"same_{label}": {
                "type": "noul",
                "instructions": f"Is `new_item` the same piece of work as `candidates.{label}` (the same action on the same thing for the same period)?"}
                for label in labels},
        }
        data = self._request("POST", "/v1/systemone", body=request, model=model)
        answers = _answers(data)
        same = {label: _same(answers, f"same_{label}") for label in labels}
        best, p = max(same.items(), key=lambda kv: kv[1])
        unsure = UNSURE[0] <= p < UNSURE[1]
        target = best if p >= SAME_T else None
        changed = None
        if target is not None and not unsure:
            # Asked directly, `existing` against `new`: inside the candidate
            # list the same question fired on rewordings (see the README).
            existing = next(x for x in candidates if x["label"] == best)
            reverse = dict(reversed(list(CHANGED_CRITERIA.items())))
            second = self._request("POST", "/v1/systemone", body={
                "model": model,
                "state": {"existing": _item(existing), "new": _item(item)},
                "questions": {
                    "changed_a": {"type": "choice", "instructions": CHANGED_INSTRUCTIONS,
                                  "criteria": CHANGED_CRITERIA},
                    "changed_b": {"type": "choice", "instructions": CHANGED_INSTRUCTIONS,
                                  "criteria": reverse},
                },
            }, model=model)
            b = _answers(second)
            changed = (_changed(b, "changed_a") + _changed(b, "changed_b")) / 2
        return JevMatch(target=target, p=p, unsure=unsure, changed=changed,
                        model=_answered_model(data, model))

    def test_key(self) -> str:
        """Check the key with one cheap call; a sentence naming the models on success."""
        data = self._request("GET", "/v1/models")
        models = data.get("models") if isinstance(data, Mapping) else None
        if not isinstance(models, list):
            raise JevError(_NOT_UNDERSTOOD, kind="permanent")
        names = [m["name"] for m in models
                 if isinstance(m, Mapping) and isinstance(m.get("name"), str) and m["name"]]
        return redact(f"The TypeSafe key works; models: {', '.join(names) or 'none'}.")

    def close(self) -> None:
        self._http.close()
