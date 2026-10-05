"""TypeSafe's Jev — request shapes, verdict and match math, status handling, no key leaks.

No network: every request goes to an `httpx.MockTransport`, and the retry
sleep is a recorder that does not wait.
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from smylted.mail import jev, redact
from smylted.mail.jev import JevClient, JevError, JevMatch, KindVerdict

KEY = "ts-live-TESTKEYTESTKEYTESTKEY"


@pytest.fixture(autouse=True)
def _registry():
    # Not pre-registered: the client must register the key itself.
    redact.forget_all_for_tests()
    yield
    redact.forget_all_for_tests()


def _answer(choice, confidence, task, event):
    return {"type": "choice", "choice": choice, "confidence": confidence,
            "probabilities": {"task": task, "event": event}}


def _ok(a, b, model="jev-1.13.0"):
    return httpx.Response(200, json={"model": model, "answers": {"kind_a": a, "kind_b": b},
                                     "usage": {"input_tokens": 511, "output_tokens": 31}})


AGREE_EVENT = _ok(_answer("event", 0.92, 0.04, 0.96), _answer("event", 0.88, 0.1, 0.9))


def _client(responses, *, key=KEY, model="jev-latest", max_attempts=3):
    """A client answering from `responses` (Responses, or callables of the request)."""
    queue = list(responses)
    seen: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        out = queue.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out(request) if callable(out) else out

    c = JevClient(api_key_provider=key if callable(key) else (lambda: key),
                  model_provider=model if callable(model) else (lambda: model),
                  max_attempts=max_attempts, sleep=sleeps.append,
                  transport=httpx.MockTransport(handler))
    return c, seen, sleeps


def _decide(client, **over):
    fields = dict(subject="Parent evening", sender="office@school.example",
                  body="Parent evening on Thursday at 18:00 in the hall.",
                  title="Parent evening", start="2026-10-08T18:00", due=None)
    fields.update(over)
    return client.decide_kind(**fields)


def test_request_shape():
    models = iter(["jev-latest", "jev-preview"])
    client, seen, _ = _client([AGREE_EVENT, AGREE_EVENT], model=lambda: next(models))
    _decide(client)
    _decide(client, start=None, due="2026-10-09")
    first, second = seen
    assert first.method == "POST"
    assert str(first.url) == "https://api.typesafe.ai/v1/systemone"
    assert first.headers["Authorization"] == f"Bearer {KEY}"
    assert first.headers["User-Agent"] == "smylted-mail/0.1"
    body = json.loads(first.content)
    assert body["model"] == "jev-latest"
    assert json.loads(second.content)["model"] == "jev-preview"      # read on every call
    assert body["state"] == {
        "email": {"from": "office@school.example", "subject": "Parent evening",
                  "body": "Parent evening on Thursday at 18:00 in the hall."},
        "extracted": {"title": "Parent evening", "start": "2026-10-08T18:00", "due": None}}
    assert json.loads(second.content)["state"]["extracted"] == {
        "title": "Parent evening", "start": None, "due": "2026-10-09"}
    qa, qb = body["questions"]["kind_a"], body["questions"]["kind_b"]
    for q in (qa, qb):
        assert q["type"] == "choice" and q["instructions"] == jev.KIND_INSTRUCTIONS
        assert q["criteria"] == jev.KIND_CRITERIA
    # Both orders in one request.
    assert list(qa["criteria"]) == ["event", "task"]
    assert list(qb["criteria"]) == ["task", "event"]


def test_key_read_on_every_call():
    keys = iter(["ts-first-key-123456", "ts-second-key-654321"])
    client, seen, _ = _client([AGREE_EVENT, AGREE_EVENT], key=lambda: next(keys))
    _decide(client)
    _decide(client)
    assert [r.headers["Authorization"] for r in seen] == [
        "Bearer ts-first-key-123456", "Bearer ts-second-key-654321"]


def test_verdict_when_both_orders_agree():
    client, _, _ = _client([AGREE_EVENT])
    v = _decide(client)
    assert v == KindVerdict(kind="event", confidence=0.88,
                            probabilities={"task": pytest.approx(0.07), "event": pytest.approx(0.93)},
                            model="jev-1.13.0", agreed=True)


def test_verdict_when_the_orders_disagree():
    client, _, _ = _client([_ok(_answer("event", 0.7, 0.2, 0.8), _answer("task", 0.6, 0.7, 0.3))])
    v = _decide(client)
    assert v.agreed is False
    assert v.confidence == 0.0
    assert v.kind == "event"                    # argmax of the averaged probabilities
    assert v.probabilities == {"task": pytest.approx(0.45), "event": pytest.approx(0.55)}


def test_verdict_tie_is_a_task():
    client, _, _ = _client([_ok(_answer("event", 0.5, 0.4, 0.6), _answer("task", 0.5, 0.6, 0.4))])
    v = _decide(client)
    assert v.kind == "task" and v.agreed is False and v.confidence == 0.0


def test_verdict_model_falls_back_to_the_requested_one():
    resp = httpx.Response(200, json={"answers": {
        "kind_a": _answer("task", 0.9, 0.9, 0.1), "kind_b": _answer("task", 0.8, 0.8, 0.2)}})
    client, _, _ = _client([resp], model="jev-preview")
    assert _decide(client).model == "jev-preview"


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_is_config(status):
    client, _, sleeps = _client([httpx.Response(status, json={"detail": {
        "error_type": "authentication_error", "message": "Cannot authenticate with the server."}})])
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "config"
    assert str(info.value) == "TypeSafe rejected the API key"
    assert sleeps == []


def test_unknown_model_is_config():
    client, _, _ = _client([httpx.Response(404, json={"detail": "not found"})], model="jev-nope")
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "config"
    assert "'jev-nope'" in str(info.value)


def test_validation_error_is_permanent_with_detail():
    client, _, sleeps = _client([httpx.Response(422, json={"detail": [
        {"loc": ["body", "questions"], "msg": "field required"}]})])
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "permanent"
    assert str(info.value).startswith("TypeSafe refused the request: ")
    assert "field required" in str(info.value)
    assert sleeps == []


def test_long_detail_is_cut():
    client, _, _ = _client([httpx.Response(422, json={"detail": "x" * 1000})])
    with pytest.raises(JevError) as info:
        _decide(client)
    assert len(str(info.value)) == len("TypeSafe refused the request: ") + jev.DETAIL_MAX


def test_rate_limit_is_retried_once_and_succeeds():
    client, seen, sleeps = _client([httpx.Response(429), AGREE_EVENT])
    assert _decide(client).kind == "event"
    assert len(seen) == 2
    assert sleeps == [1.0]


def test_retry_after_is_honoured_and_capped():
    client, _, sleeps = _client([httpx.Response(429, headers={"Retry-After": "3"}),
                                 httpx.Response(503, headers={"Retry-After": "120"}),
                                 AGREE_EVENT])
    _decide(client)
    assert sleeps == [3.0, 10.0]


def test_overloaded_three_times_is_transient():
    client, seen, sleeps = _client([httpx.Response(529)] * 3)
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "transient"
    assert "(529)" in str(info.value)
    assert len(seen) == 3
    assert sleeps == [1.0, 2.0]                 # no sleep after the last attempt


def test_network_error_is_retried_then_transient():
    client, seen, _ = _client([httpx.ConnectError("refused")] * 3)
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "transient"
    assert "could not reach TypeSafe" in str(info.value)
    assert len(seen) == 3


def test_other_client_errors_are_permanent_and_not_retried():
    client, seen, _ = _client([httpx.Response(400)])
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "permanent"
    assert len(seen) == 1


@pytest.mark.parametrize("answers", [
    {},
    {"kind_a": _answer("event", 0.9, 0.1, 0.9)},
    {"kind_a": _answer("maybe", 0.9, 0.1, 0.9), "kind_b": _answer("event", 0.9, 0.1, 0.9)},
    {"kind_a": {**_answer("event", 0.9, 0.1, 0.9), "type": "number"},
     "kind_b": _answer("event", 0.9, 0.1, 0.9)},
    {"kind_a": _answer("event", "high", 0.1, 0.9), "kind_b": _answer("event", 0.9, 0.1, 0.9)},
    {"kind_a": _answer("event", 0.9, 0.1, None), "kind_b": _answer("event", 0.9, 0.1, 0.9)},
    {"kind_a": {**_answer("event", 0.9, 0.1, 0.9), "probabilities": [0.1, 0.9]},
     "kind_b": _answer("event", 0.9, 0.1, 0.9)},
])
def test_malformed_answer_is_permanent(answers):
    client, _, _ = _client([httpx.Response(200, json={"model": "jev-1", "answers": answers})])
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "permanent"
    assert str(info.value) == "TypeSafe returned an answer this code does not understand"


def test_non_json_answer_is_permanent():
    client, _, _ = _client([httpx.Response(200, text="<html>")])
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "permanent"


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_key_is_config(key):
    client, seen, _ = _client([AGREE_EVENT], key=lambda: key)
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "config"
    assert str(info.value) == "no TypeSafe API key is set"
    assert seen == []


def test_key_with_a_bad_character_is_config():
    client, seen, _ = _client([AGREE_EVENT], key="ts-key-é-123456")
    with pytest.raises(JevError) as info:
        _decide(client)
    assert info.value.kind == "config"
    assert "cannot go in a header" in str(info.value)
    assert seen == []


def test_the_key_never_appears_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)

    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": f"bad header {request.headers['Authorization']}"})

    def echo_text(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=request.headers["Authorization"])

    client, _, _ = _client([echo, echo_text, httpx.ConnectError(f"refused {KEY}"),
                            httpx.ConnectError(f"refused {KEY}")])
    errors = []
    for _ in range(2):
        with pytest.raises(JevError) as info:
            _decide(client)
        errors.append(str(info.value))
    assert "bad header Bearer <redacted>" in errors[0]
    for text in errors:
        assert KEY not in text and "TESTKEY" not in text
    for record in caplog.records:
        assert KEY not in logging.Formatter().format(record)


def test_test_key_lists_the_models():
    client, seen, _ = _client([httpx.Response(200, json={"models": [
        {"name": "jev-latest", "description": "d", "release_date": "2026-09-01"},
        {"name": "jev-preview", "description": "d", "release_date": "2026-09-20"}]})])
    assert client.test_key() == "The TypeSafe key works; models: jev-latest, jev-preview."
    (req,) = seen
    assert req.method == "GET" and str(req.url) == "https://api.typesafe.ai/v1/models"
    assert req.headers["Authorization"] == f"Bearer {KEY}"


def test_test_key_errors():
    client, _, _ = _client([httpx.Response(401)])
    with pytest.raises(JevError) as info:
        client.test_key()
    assert info.value.kind == "config"
    client, _, _ = _client([httpx.Response(200, json={"models": "jev-latest"})])
    with pytest.raises(JevError) as info:
        client.test_key()
    assert info.value.kind == "permanent"


def test_close():
    client, _, _ = _client([])
    client.close()


# ── the duplicate check (addendum ZD) ──

ITEM = {"label": "new", "title": "Return the signed field-trip form",
        "notes": "Sign and send back.", "due": "2026-10-09"}
CANDS = [
    {"label": "T1", "title": "Book dentist appointment", "notes": "", "due": None},
    {"label": "S1", "title": "Sign permission slip for zoo trip", "notes": "Return to teacher",
     "due": "2026-10-09"},
]


def _same(model="jev-1.13.0", **p):
    return httpx.Response(200, json={"model": model, "answers": {
        f"same_{label}": {"type": "noul", "noul": v} for label, v in p.items()}})


def _changed(a, b):
    def answer(p_changed):
        return {"type": "choice", "choice": "changed" if p_changed >= 0.5 else "same",
                "confidence": 0.9, "probabilities": {"same": 1 - p_changed, "changed": p_changed}}
    return httpx.Response(200, json={"model": "jev-1.13.0",
                                     "answers": {"changed_a": answer(a), "changed_b": answer(b)}})


def test_match_request_shapes():
    client, seen, _ = _client([_same(T1=0.02, S1=0.93), _changed(0.8, 0.6)])
    m = client.match(ITEM, CANDS)
    assert m == JevMatch(target="S1", p=0.93, unsure=False, changed=pytest.approx(0.7),
                         model="jev-1.13.0")
    first, second = seen
    for r in seen:
        assert str(r.url) == "https://api.typesafe.ai/v1/systemone"
        assert r.headers["Authorization"] == f"Bearer {KEY}"
    one = json.loads(first.content)
    assert one["model"] == "jev-latest"
    assert one["state"] == {
        "new_item": {"title": "Return the signed field-trip form", "notes": "Sign and send back.",
                     "due": "2026-10-09"},
        "candidates": {
            "T1": {"title": "Book dentist appointment", "notes": "", "due": None},
            "S1": {"title": "Sign permission slip for zoo trip", "notes": "Return to teacher",
                   "due": "2026-10-09"}}}
    assert one["questions"] == {
        f"same_{label}": {
            "type": "noul",
            "instructions": f"Is `new_item` the same piece of work as `candidates.{label}` "
                            "(the same action on the same thing for the same period)?"}
        for label in ("T1", "S1")}
    two = json.loads(second.content)
    assert two["model"] == "jev-latest"
    assert two["state"] == {"existing": one["state"]["candidates"]["S1"],
                            "new": one["state"]["new_item"]}
    qa, qb = two["questions"]["changed_a"], two["questions"]["changed_b"]
    for q in (qa, qb):
        assert q["type"] == "choice" and q["instructions"] == jev.CHANGED_INSTRUCTIONS
        assert q["criteria"] == jev.CHANGED_CRITERIA
    assert list(qa["criteria"]) == ["same", "changed"]
    assert list(qb["criteria"]) == ["changed", "same"]


def test_match_below_the_threshold_is_new_without_a_second_request():
    client, seen, _ = _client([_same(T1=0.02, S1=0.2)])
    m = client.match(ITEM, CANDS)
    assert (m.target, m.p, m.unsure, m.changed) == (None, 0.2, False, None)
    assert len(seen) == 1


@pytest.mark.parametrize("p,target", [(0.35, None), (0.49, None), (0.5, "S1"), (0.64, "S1")])
def test_match_unsure_band_asks_nothing_more(p, target):
    client, seen, _ = _client([_same(T1=0.1, S1=p)])
    m = client.match(ITEM, CANDS)
    assert m.unsure is True and m.target == target and m.changed is None
    assert len(seen) == 1


def test_match_at_the_top_of_the_band_is_sure():
    client, seen, _ = _client([_same(T1=0.65, S1=0.1), _changed(0.1, 0.3)])
    m = client.match(ITEM, CANDS)
    assert (m.target, m.unsure, m.changed) == ("T1", False, pytest.approx(0.2))
    assert len(seen) == 2


def test_match_tie_takes_the_first_candidate():
    client, _, _ = _client([_same(T1=0.9, S1=0.9), _changed(0.1, 0.1)])
    assert client.match(ITEM, CANDS).target == "T1"


@pytest.mark.parametrize("answers", [
    {},
    {"same_T1": {"type": "noul", "noul": 0.1}},
    {"same_T1": {"type": "noul", "noul": 0.1}, "same_S1": {"type": "noul", "noul": "high"}},
    {"same_T1": {"type": "noul", "noul": 0.1}, "same_S1": {"type": "noul", "noul": 1.5}},
    {"same_T1": {"type": "noul", "noul": 0.1}, "same_S1": {"type": "noul", "noul": True}},
    {"same_T1": {"type": "noul", "noul": 0.1}, "same_S1": 0.9},
])
def test_match_malformed_same_answer_is_permanent(answers):
    client, _, _ = _client([httpx.Response(200, json={"model": "jev-1", "answers": answers})])
    with pytest.raises(JevError) as info:
        client.match(ITEM, CANDS)
    assert info.value.kind == "permanent"
    assert str(info.value) == "TypeSafe returned an answer this code does not understand"


@pytest.mark.parametrize("answers", [
    {},
    {"changed_a": {"type": "choice", "probabilities": {"same": 0.2, "changed": 0.8}}},
    {"changed_a": {"type": "choice", "probabilities": {"same": 0.2, "changed": 0.8}},
     "changed_b": {"type": "choice", "probabilities": {"same": 0.2}}},
    {"changed_a": {"type": "choice", "probabilities": {"same": 0.2, "changed": 0.8}},
     "changed_b": {"type": "noul", "probabilities": {"same": 0.2, "changed": 0.8}}},
    {"changed_a": {"type": "choice", "probabilities": {"same": 0.2, "changed": 0.8}},
     "changed_b": {"type": "choice", "probabilities": {"same": 0.2, "changed": -0.1}}},
])
def test_match_malformed_changed_answer_is_permanent(answers):
    client, _, _ = _client([_same(T1=0.1, S1=0.9),
                            httpx.Response(200, json={"model": "jev-1", "answers": answers})])
    with pytest.raises(JevError) as info:
        client.match(ITEM, CANDS)
    assert info.value.kind == "permanent"


def test_match_needs_one_to_fifteen_candidates():
    client, seen, _ = _client([])
    with pytest.raises(ValueError):
        client.match(ITEM, [])
    many = [{"label": f"T{i}", "title": "x", "notes": "", "due": None} for i in range(16)]
    with pytest.raises(ValueError):
        client.match(ITEM, many)
    assert seen == []


def test_match_errors_are_jev_errors():
    client, _, _ = _client([httpx.Response(401)])
    with pytest.raises(JevError) as info:
        client.match(ITEM, CANDS)
    assert info.value.kind == "config"
