"""The mail pipeline end to end, against a real sidecar database and fakes for
the mailbox, the model and Jev. No network: the service's Radicale is a
closed port, and staging a suggestion never needs it."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from smylted.db import store
from smylted.mail import message, pipeline, redact, review, settings
from smylted.mail.imap import FolderInfo, MailConnectError
from smylted.mail.jev import JevError
from smylted.mail.llm import EXTRACT_TOOL_NAME, LlmError, Match
from smylted.mail.pipeline import Ingestor
from smylted.mail.settings import MAIL_SETTINGS_KEY, MAIL_STATUS_KEY
from tests.mail_fakes import (
    TEST_TYPESAFE_KEY,
    FakeJev,
    FakeLlm,
    FakeMailSource,
    FakeSdk,
    SpyHost,
    at,
    extraction,
    extraction_response,
    jev_match,
    make_llm_client,
    make_service,
    make_store,
    response,
    set_config,
    source_factory,
    tool_use,
    verdict,
)

CORPUS = Path(__file__).parent / "corpus" / "mail"
NOW = at(2026, 10, 6, 8)
INBOX = FolderInfo(name="INBOX", raw="INBOX", flags=frozenset(), delimiter="/")
BASE_CONFIG = {
    "enabled": True,
    "self_addresses": ["me@proton.me"],
    "always_parse": ["portal.school.example"],
    "folders": ["INBOX", "Labels/School"],
}


def eml(name: str) -> bytes:
    return (CORPUS / f"{name}.eml").read_bytes()


def reply(n: int, body: str, *, root: str = "req-1@club.example") -> bytes:
    """A later message in the coach's thread."""
    return (
        f"Message-ID: <reply-{n}@club.example>\r\n"
        f"Date: Tue, 06 Oct 2026 0{n}:00:00 +0200\r\n"
        "From: Coach Miller <coach@club.example>\r\n"
        "To: me@proton.me\r\n"
        "Subject: Re: Snacks for Saturday\r\n"
        f"In-Reply-To: <{root}>\r\n"
        f"References: <{root}>\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    ).encode()


def plain(mid: str, subject: str, body: str, sender: str = "office@school.example") -> bytes:
    return (
        f"Message-ID: <{mid}>\r\n"
        "Date: Mon, 05 Oct 2026 10:00:00 +0200\r\n"
        f"From: {sender}\r\n"
        "To: me@proton.me\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    ).encode()


@pytest.fixture(autouse=True)
def _forget_secrets():
    redact.forget_all_for_tests()
    yield
    redact.forget_all_for_tests()


@pytest.fixture
def svc(tmp_path):
    s = make_service(tmp_path)
    set_config(s, **BASE_CONFIG)
    yield s
    s.close()


@pytest.fixture
def secrets(tmp_path):
    return make_store(tmp_path)


@pytest.fixture
def jev_secrets(tmp_path):
    # A TypeSafe key is the owner's opt-in to Jev; without one the model decides.
    return make_store(tmp_path, typesafe_key=TEST_TYPESAFE_KEY)


def ingestor(svc, secrets, llm=None, *, jev=None, source=None, host=None) -> Ingestor:
    return Ingestor(host or svc, secrets, llm=llm if llm is not None else FakeLlm(),
                    jev=jev or FakeJev(),
                    source_factory=source_factory(source) if source is not None else None,
                    clock=lambda: NOW)


def pending(svc) -> list:
    return svc.mail(store.mail_list_suggestions, status="pending")


def ledger(svc, key: str):
    return svc.mail(store.mail_ledger_get, key)


def inbox_source(messages: dict[int, bytes], *, dates=None, uidvalidity: int = 1,
                 **extra_folders) -> FakeMailSource:
    folders = {"INBOX": {"flags": [], "uidvalidity": uidvalidity, "messages": messages,
                         "dates": dates or {u: at(2026, 10, 5) for u in messages}}}
    folders.update(extra_folders)
    return FakeMailSource(folders)


# ── the required scenarios ──

def test_allowlisted_noreply_with_dmarc_pass_is_parsed(svc, secrets):
    llm = FakeLlm(extract=extraction("Sign the field trip permission slip", due=date(2026, 10, 9)))
    out = ingestor(svc, secrets, llm).process_message(
        INBOX, eml("pipe_school_noreply_dmarc_pass"), uid=1)
    assert out.outcome == "staged"
    [s] = pending(svc)
    assert s["kind"] == "task" and s["due"] == "2026-10-09"
    row = ledger(svc, "mid:trip-pass-1@portal.school.example")
    assert row["outcome"] == "staged" and row["suggestion_id"] == s["id"]
    assert "dmarc=pass" in row["detail"]
    assert len(llm.extract_calls) == 1


def test_same_sender_with_dmarc_fail_is_filtered_as_bulk(svc, secrets):
    llm = FakeLlm(extract=extraction("Sign the slip"))
    out = ingestor(svc, secrets, llm).process_message(
        INBOX, eml("pipe_school_noreply_dmarc_fail"), uid=1)
    assert (out.stage, out.outcome) == ("bulk", "skipped")
    assert pending(svc) == []
    row = ledger(svc, "mid:trip-fail-1@portal.school.example")
    assert row["stage"] == "bulk"
    assert "List-Unsubscribe" in row["detail"] and "dmarc=fail" in row["detail"]
    assert llm.extract_calls == []


def test_newsletter_with_list_unsubscribe_is_skipped(svc, secrets):
    llm = FakeLlm(extract=extraction("Order before Sunday"))
    out = ingestor(svc, secrets, llm).process_message(INBOX, eml("pipe_newsletter"), uid=1)
    assert (out.stage, out.outcome, out.detail) == ("bulk", "skipped", "List-Unsubscribe")
    assert pending(svc) == [] and llm.extract_calls == []


def test_my_sent_mail_is_skipped(svc, secrets):
    llm = FakeLlm(extract=extraction("Send the reading log"))
    out = ingestor(svc, secrets, llm).process_message(INBOX, eml("pipe_sent_by_me"), uid=1)
    assert (out.stage, out.outcome) == ("self", "skipped")
    assert ledger(svc, "mid:sent-1@proton.me")["stage"] == "self"
    assert llm.extract_calls == []


def test_note_to_self_is_captured(svc, secrets):
    llm = FakeLlm(extract=extraction("Buy stamps for the school forms"))
    out = ingestor(svc, secrets, llm).process_message(INBOX, eml("pipe_note_to_self"), uid=1)
    assert out.outcome == "staged"
    assert [s["title"] for s in pending(svc)] == ["Buy stamps for the school forms"]


def test_one_message_in_three_folders_yields_one_suggestion(svc, secrets):
    raw = eml("pipe_request")
    source = inbox_source(
        {1: raw},
        **{"Labels/School": {"flags": [], "uidvalidity": 7, "messages": {3: raw},
                             "dates": {3: at(2026, 10, 5)}},
           "All Mail": {"flags": ["\\All"], "uidvalidity": 9, "messages": {40: raw},
                        "dates": {40: at(2026, 10, 5)}}})
    set_config(svc, folders=["INBOX", "Labels/School", "All Mail"])
    llm = FakeLlm(extract=extraction("Bring the team snack list", due=date(2026, 10, 9)))
    report = ingestor(svc, secrets, llm, source=source).run_once()
    assert report.ok, report.error
    assert len(pending(svc)) == 1
    assert len(llm.extract_calls) == 1
    assert "All Mail" not in source.selected_names()
    assert source.selected_names() == ["INBOX", "Labels/School"]
    assert report.counts == {"staged": 1, "duplicate": 1}
    assert source.closed


def test_reply_quoting_the_request_attaches_to_the_thread(svc, secrets):
    llm = FakeLlm(extract=[extraction("Bring the team snack list", due=date(2026, 10, 9)),
                           extraction("Bring cups", notes="Also cups.")])
    ing = ingestor(svc, secrets, llm)
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    second = ing.process_message(INBOX, eml("pipe_reply_quoting"), uid=2)
    assert first.outcome == "staged"
    assert (second.stage, second.outcome) == ("dedup", "attached")
    assert second.suggestion_id == first.suggestion_id
    [s] = pending(svc)
    updates = review.suggestion_dto(s)["updates"]
    assert len(updates) == 1 and updates[0]["notes"] == "Also cups."
    assert s["due"] == "2026-10-09"
    assert "Bring the team snack list" not in llm.extract_calls[1].body
    assert "Also please bring cups." in llm.extract_calls[1].body


def test_rescan_after_uidvalidity_change_creates_no_duplicates(svc, secrets):
    raw = eml("pipe_request")
    source = inbox_source({5: raw})
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    ing = ingestor(svc, secrets, llm, source=source)
    assert ing.run_once().ok
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 5

    source.folders["INBOX"].update(uidvalidity=2, messages={12: raw}, dates={12: at(2026, 10, 5)})
    report = ing.run_once()
    assert report.ok, report.error
    assert report.folders["INBOX"]["rescanned"] is True
    assert len(pending(svc)) == 1
    assert len(llm.extract_calls) == 1
    cur = svc.mail(store.mail_get_cursor, "INBOX")
    assert (cur["uidvalidity"], cur["last_uid"]) == (2, 12)
    searches = [arg for name, arg in source.calls if name == "search_uids"]
    assert searches[-1]["after_uid"] is None and searches[-1]["since"] is not None


def test_rejected_suggestion_does_not_come_back(svc, secrets):
    source = inbox_source({1: eml("pipe_request")})
    llm = FakeLlm(extract=extraction("Bring the team snack list", due=date(2026, 10, 9)))
    ing = ingestor(svc, secrets, llm, source=source)
    assert ing.run_once().ok
    [s] = pending(svc)
    review.reject(svc, s["id"])

    # (a) a rescan from scratch finds the message again: nothing new
    svc.mail(lambda conn: conn.execute("DELETE FROM mail_cursors"))
    assert ing.run_once().ok
    assert pending(svc) == [] and len(llm.extract_calls) == 1
    # ... and even with its ledger row gone, the rejection holds
    svc.mail(lambda conn: conn.execute("DELETE FROM mail_ledger WHERE key='mid:req-1@club.example'"))
    out = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    assert (out.stage, out.outcome) == ("ledger", "suppressed")

    # (b) a later reply restating the same thing is suppressed
    out = ing.process_message(INBOX, reply(1, "Reminder: the snack list by Friday."), uid=2)
    assert (out.stage, out.outcome) == ("dedup", "suppressed")
    assert pending(svc) == []

    # (c) a later reply asking for something else is a new suggestion
    llm.extract_script = extraction("Book the minibus", due=date(2026, 10, 10))
    llm.match_script = Match("new", None)
    out = ing.process_message(INBOX, reply(2, "Could you also book the minibus?"), uid=3)
    assert out.outcome == "staged"
    assert [p["title"] for p in pending(svc)] == ["Book the minibus"]
    [(_, candidates)] = llm.match_calls
    assert [c.label for c in candidates] == ["R1"]


def test_ics_attachment_becomes_an_event_without_the_llm(svc, secrets):
    llm = FakeLlm(extract=extraction("should not be asked"))
    ing = ingestor(svc, secrets, llm)
    out = ing.process_message(INBOX, eml("pipe_invite"), uid=1)
    assert (out.stage, out.outcome) == ("fastpath", "staged")
    [s] = pending(svc)
    assert s["kind"] == "event" and s["title"] == "Parent evening"
    assert s["event_start"] == "2026-10-14T18:00:00+02:00"
    assert s["event_end"] == "2026-10-14T19:30:00+02:00"
    assert s["location"] == "Main hall" and s["ics_uid"] == "parent-evening-2026@school.example"
    assert s["event_all_day"] == 0
    assert llm.extract_calls == [] and llm.match_calls == []
    # The same invite re-sent in a new message does not stage a second copy.
    again = eml("pipe_invite").replace(b"<invite-1@school.example>", b"<invite-2@school.example>")
    out = ing.process_message(INBOX, again, uid=2)
    assert (out.stage, out.outcome) == ("fastpath", "duplicate")
    assert len(pending(svc)) == 1


def test_prompt_injection_produces_at_most_a_normal_suggestion(svc, secrets):
    injected = tool_use("smylte_create_task", {"summary": "pwned", "count": 50})
    valid = tool_use(EXTRACT_TOOL_NAME, {
        "is_actionable": True, "kind": "task", "title": "Bring a cake to the bake sale",
        "notes": "A stranger asked.", "due": "2026-10-09", "event_start": None,
        "event_end": None, "location": "", "confidence": 0.7})
    client, sdk = make_llm_client([response(injected, valid)])
    spy = SpyHost(svc)
    out = ingestor(svc, secrets, client, host=spy).process_message(
        INBOX, eml("pipe_injection"), uid=1)
    assert out.outcome == "staged"

    [request] = sdk.calls
    assert [t["name"] for t in request["tools"]] == [EXTRACT_TOOL_NAME]
    content = request["messages"][0]["content"]
    start, end = content.index("<<<EMAIL n0nce>>>"), content.index("<<<END EMAIL n0nce>>>")
    assert start < content.index("Ignore previous instructions") < end
    suggestions = svc.mail(store.mail_list_suggestions)
    assert len(suggestions) <= 1 and all(s["kind"] == "task" for s in suggestions)
    assert "create_task" not in spy.called and "edit_task" not in spy.called


def test_prompt_injection_with_only_a_foreign_tool_call_is_an_error(svc, secrets):
    client, sdk = make_llm_client([response(tool_use("smylte_create_task", {"summary": "x"}))])
    spy = SpyHost(svc)
    out = ingestor(svc, secrets, client, host=spy).process_message(
        INBOX, eml("pipe_injection"), uid=1)
    assert (out.stage, out.outcome) == ("extract", "error")
    assert svc.mail(store.mail_list_suggestions) == []
    assert ledger(svc, "mid:inj-1@stranger.example")["outcome"] == "error"
    assert "create_task" not in spy.called


def test_missing_message_id_falls_back_to_hash(svc, secrets):
    llm = FakeLlm(extract=extraction("Call Sam about the car pool"))
    ing = ingestor(svc, secrets, llm)
    out = ing.process_message(INBOX, eml("pipe_no_message_id"), uid=1)
    assert out.outcome == "staged"
    [row] = svc.mail(store.mail_ledger_recent)
    assert row["key"].startswith("hash:")
    again = ing.process_message(INBOX, eml("pipe_no_message_id"), uid=9)
    assert (again.stage, again.outcome) == ("ledger", "duplicate")
    assert len(pending(svc)) == 1 and len(llm.extract_calls) == 1


# ── the run around the messages ──

def test_model_and_workspace_are_read_on_every_call(svc, secrets):
    ing = Ingestor(svc, secrets, jev=FakeJev(), clock=lambda: NOW)
    sdk = FakeSdk([extraction_response("Bring the snack list"), extraction_response("Buy stamps")])

    def factory(key, workspace):
        sdk.factory_calls.append((workspace,))
        return sdk
    ing.llm.client_factory = factory

    set_config(svc, model="claude-model-a")
    ing.process_message(INBOX, eml("pipe_request"), uid=1)
    set_config(svc, model="claude-model-b", anthropic_workspace_id="wrkspc_test01")
    ing.process_message(INBOX, eml("pipe_note_to_self"), uid=2)
    assert [c["model"] for c in sdk.calls] == ["claude-model-a", "claude-model-b"]
    assert sdk.factory_calls == [(None,), ("wrkspc_test01",)]


def test_fake_llm_sees_the_model_per_call(svc, secrets):
    llm = FakeLlm(extract=[extraction("Bring the snack list"), extraction("Buy stamps")])
    ing = ingestor(svc, secrets, llm)
    llm.model_provider = lambda: ing.config().model
    set_config(svc, model="claude-model-a")
    ing.process_message(INBOX, eml("pipe_request"), uid=1)
    set_config(svc, model="claude-model-b")
    ing.process_message(INBOX, eml("pipe_note_to_self"), uid=2)
    assert llm.models == ["claude-model-a", "claude-model-b"]


def test_transient_llm_error_releases_the_claim_for_the_next_run(svc, secrets):
    source = inbox_source({1: eml("pipe_request")})
    llm = FakeLlm(extract=[LlmError("rate limited (429)", kind="transient"),
                           extraction("Bring the team snack list")])
    ing = ingestor(svc, secrets, llm, source=source)
    report = ing.run_once()
    assert not report.ok and report.error == "rate limited (429)"
    assert report.counts == {"retry": 1}
    assert ledger(svc, "mid:req-1@club.example") is None
    assert svc.mail(store.mail_get_cursor, "INBOX") is None
    assert svc.mail(store.get_meta_json, MAIL_STATUS_KEY)["last_error"] == "rate limited (429)"

    report = ing.run_once()
    assert report.ok, report.error
    assert len(pending(svc)) == 1
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 1
    status = svc.mail(store.get_meta_json, MAIL_STATUS_KEY)
    assert status["last_error"] is None and status["last_ok_at"]


def test_config_llm_error_aborts_the_run_and_keeps_the_cursor(svc, secrets):
    source = inbox_source({1: eml("pipe_request"), 2: eml("pipe_no_message_id"),
                           3: eml("pipe_note_to_self")})
    llm = FakeLlm(extract=[extraction("Bring the team snack list"),
                           LlmError("Anthropic rejected the API key (401).", kind="config"),
                           extraction("never reached")])
    report = ingestor(svc, secrets, llm, source=source).run_once()
    assert not report.ok and "rejected the API key" in report.error
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 1
    assert len(llm.extract_calls) == 2
    keys = [r["key"] for r in svc.mail(store.mail_ledger_recent)]
    assert keys == ["mid:req-1@club.example"]          # 2 released, 3 never claimed
    assert "rejected the API key" in svc.mail(store.get_meta_json, MAIL_STATUS_KEY)["last_error"]


def test_oversize_message_is_skipped(svc, secrets, monkeypatch):
    monkeypatch.setattr(pipeline, "MAX_MESSAGE_BYTES", 100)
    source = inbox_source({1: eml("pipe_request")})
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    report = ingestor(svc, secrets, llm, source=source).run_once()
    assert report.ok and report.counts == {"skipped": 1}
    row = ledger(svc, "oversize:INBOX:1:1")
    assert (row["stage"], row["outcome"], row["detail"]) == ("fetch", "skipped", "larger than 8 MB")
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 1
    assert llm.extract_calls == []


def test_first_run_only_fetches_messages_since_backfill(svc, secrets):
    source = inbox_source({1: eml("pipe_no_message_id"), 2: eml("pipe_request")},
                          dates={1: at(2026, 9, 1), 2: at(2026, 10, 5)})
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    report = ingestor(svc, secrets, llm, source=source).run_once()
    assert report.ok
    assert [arg for name, arg in source.calls if name == "fetch"] == [[2]]
    assert len(llm.extract_calls) == 1
    # Nothing new next time: the cursor search starts after UID 2.
    ingestor(svc, secrets, llm, source=source).run_once()
    assert [arg for name, arg in source.calls if name == "search_uids"][-1]["after_uid"] == 2


def test_runs_are_skipped_when_switched_off(svc, secrets):
    source = inbox_source({1: eml("pipe_request")})
    set_config(svc, enabled=False)
    report = ingestor(svc, secrets, source=source).run_once()
    assert report.skipped_reason == "disabled" and source.calls == []
    off = Ingestor(svc, secrets, llm=FakeLlm(), jev=FakeJev(), deployment_enabled=False,
                   source_factory=source_factory(source))
    set_config(svc, enabled=True)
    assert off.run_once().skipped_reason == "deployment"
    assert off.poll_interval_s() == 300.0
    assert svc.mail(store.get_meta_json, MAIL_STATUS_KEY) == {}


def test_missing_anthropic_key_fails_the_run_before_connecting(svc, tmp_path):
    source = inbox_source({1: eml("pipe_request")})
    no_key = make_store(tmp_path, api_key=None)
    report = ingestor(svc, no_key, source=source).run_once()
    assert not report.ok and report.error == "no Anthropic API key is set"
    assert source.calls == []


def test_pending_suggestion_duplicate_keeps_its_due_date(svc, secrets):
    llm = FakeLlm(extract=[extraction("Bring the team snack list", due=date(2026, 10, 9)),
                           extraction("Team snack list", due=date(2026, 10, 20), notes="Again.")],
                  match=Match("duplicate", "S1"))
    ing = ingestor(svc, secrets, llm)
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    out = ing.process_message(INBOX, eml("pipe_no_message_id"), uid=2)
    assert (out.stage, out.outcome, out.suggestion_id) == ("dedup", "attached", first.suggestion_id)
    [s] = pending(svc)
    assert s["due"] == "2026-10-09"
    [u] = review.suggestion_dto(s)["updates"]
    assert u["notes"] == "" and u["due"] == "2026-10-20"


def test_test_imap_reports_folders_and_authentication_results(svc, secrets):
    source = inbox_source(
        {1: eml("pipe_request"), 2: eml("pipe_school_noreply_dmarc_pass")},
        **{"Sent": {"flags": ["\\Sent"], "uidvalidity": 3, "messages": {}},
           "Labels/School": {"flags": [], "uidvalidity": 4, "messages": {}}})
    set_config(svc, imap_username="me@proton.me")
    result = ingestor(svc, secrets, source=source).test_imap()
    assert result["ok"] and result["detail"] == "Logged in as me@proton.me; 3 folders."
    folders = {f["name"]: f for f in result["folders"]}
    assert folders["Sent"] == {"name": "Sent", "special": ["\\Sent"], "excluded": True,
                               "selected": False}
    assert folders["Labels/School"]["selected"] and folders["INBOX"]["selected"]
    assert result["auth_results"] == {"checked": True, "present": True,
                                      "authserv_ids": ["mailin008.protonmail.ch"],
                                      "trusted": True, "sampled": 2}
    assert ("fetch_header_fields", 2) in source.calls and source.closed


def test_status_combines_the_stored_status_with_live_counts(svc, secrets):
    source = inbox_source({1: eml("pipe_request")})
    ing = ingestor(svc, secrets, FakeLlm(extract=extraction("Bring the team snack list")),
                   source=source)
    ing.run_once()
    st = ing.status()
    assert st["enabled"] is True and st["deployment_enabled"] is True and st["running"] is False
    assert st["pending_count"] == 1 and st["counts"] == {"staged": 1}
    assert [c["folder"] for c in st["cursors"]] == ["INBOX"]
    assert st["last_error"] is None and st["last_counts"] == {"staged": 1}
    assert st["last_folders"]["Labels/School"] == {"missing": True}


# ── task or event (addendum Z) ──

def test_model_event_with_a_start_becomes_an_event(svc, secrets):
    llm = FakeLlm(extract=extraction("Parent evening", kind="event",
                                     event_start=datetime(2026, 10, 14, 18, 0),
                                     location="Main hall"))
    out = ingestor(svc, secrets, llm).process_message(INBOX, eml("pipe_request"), uid=1)
    [s] = pending(svc)
    assert (s["kind"], s["event_start"], s["event_all_day"]) == ("event", "2026-10-14T18:00:00", 0)
    assert s["location"] == "Main hall" and s["due"] is None and s["ics_uid"] is None
    assert "the model chose event" in out.detail


def test_rules_override_the_model(svc, secrets):
    set_config(svc, kind_decider="rules", kind_rules=['subject:"parent evening" -> event'])
    llm = FakeLlm(extract=extraction("Go to the parent evening", kind="task",
                                     event_start=date(2026, 10, 14)))
    out = ingestor(svc, secrets, llm).process_message(
        INBOX, plain("pe-1@school.example", "Parent evening next week", "See you there."), uid=1)
    [s] = pending(svc)
    assert s["kind"] == "event" and s["event_all_day"] == 1 and s["event_start"] == "2026-10-14"
    assert 'rule: subject:"parent evening" -> event' in out.detail


def test_rules_with_no_match_make_a_task(svc, secrets):
    set_config(svc, kind_decider="rules", kind_rules=['subject:"parent evening" -> event'])
    llm = FakeLlm(extract=extraction("Concert", kind="event",
                                     event_start=datetime(2026, 10, 14, 18, 0)))
    out = ingestor(svc, secrets, llm).process_message(INBOX, eml("pipe_request"), uid=1)
    assert [s["kind"] for s in pending(svc)] == ["task"]
    assert "no rule matched" in out.detail


def test_event_without_a_start_is_kept_as_a_task(svc, secrets):
    llm = FakeLlm(extract=extraction("Parent evening", kind="event"))
    out = ingestor(svc, secrets, llm).process_message(INBOX, eml("pipe_request"), uid=1)
    assert [s["kind"] for s in pending(svc)] == ["task"]
    assert "no start time, kept as a task" in ledger(svc, "mid:req-1@club.example")["detail"]
    assert out.detail.endswith("no start time, kept as a task")


# ── TypeSafe Jev (addendum ZJ) ──

def test_jev_choosing_event_overrides_the_model(svc, jev_secrets):
    set_config(svc, kind_decider="jev")
    jev = FakeJev(verdict("event", confidence=0.9))
    llm = FakeLlm(extract=extraction("Match on Saturday", kind="task",
                                     event_start=datetime(2026, 10, 10, 10, 0),
                                     due=date(2026, 10, 9)))
    out = ingestor(svc, jev_secrets, llm, jev=jev).process_message(
        INBOX, eml("pipe_request"), uid=1)
    assert [s["kind"] for s in pending(svc)] == ["event"]
    assert "Jev chose event (0.90, jev-1.13.0)" in out.detail
    # The email alone, as dev/mail_eval.py measured it: nothing the model extracted.
    [call] = jev.calls
    assert call.keys() == {"sender", "subject", "sent", "body"}
    assert call["sender"] == "Coach Miller <coach@club.example>"
    assert (call["subject"], call["sent"]) == ("Snacks for Saturday", "2026-10-05")
    assert call["body"] == llm.extract_calls[0].body


def test_jev_disagreeing_with_itself_keeps_the_models_kind(svc, jev_secrets):
    set_config(svc, kind_decider="jev")
    jev = FakeJev(verdict("event", agreed=False))
    llm = FakeLlm(extract=extraction("Match on Saturday", kind="task",
                                     event_start=datetime(2026, 10, 10, 10, 0)))
    out = ingestor(svc, jev_secrets, llm, jev=jev).process_message(
        INBOX, eml("pipe_request"), uid=1)
    assert [s["kind"] for s in pending(svc)] == ["task"]
    assert "Jev unsure (0.00); kept the model's task" in out.detail


def test_jev_failing_keeps_the_models_kind(svc, jev_secrets):
    set_config(svc, kind_decider="jev")
    jev = FakeJev(JevError("TypeSafe is unavailable (529)", kind="transient"))
    llm = FakeLlm(extract=extraction("Match on Saturday", kind="event",
                                     event_start=datetime(2026, 10, 10, 10, 0)))
    out = ingestor(svc, jev_secrets, llm, jev=jev).process_message(
        INBOX, eml("pipe_request"), uid=1)
    assert out.outcome == "staged"
    assert [s["kind"] for s in pending(svc)] == ["event"]
    detail = ledger(svc, "mid:req-1@club.example")["detail"]
    assert "Jev unavailable (TypeSafe is unavailable (529)); kept the model's event" in detail


def test_jev_without_a_key_leaves_the_kind_to_the_model(svc, secrets):
    set_config(svc, kind_decider="jev")
    jev = FakeJev(verdict("event", confidence=0.9))
    llm = FakeLlm(extract=extraction("Match on Saturday", kind="task",
                                     event_start=datetime(2026, 10, 10, 10, 0)))
    out = ingestor(svc, secrets, llm, jev=jev).process_message(INBOX, eml("pipe_request"), uid=1)
    assert [s["kind"] for s in pending(svc)] == ["task"]
    assert out.detail == "the model chose task"           # silently: no Jev note
    assert jev.calls == []


def test_jev_below_the_measured_confidence_keeps_the_models_kind(svc, jev_secrets):
    set_config(svc, kind_decider="jev")
    jev = FakeJev(verdict("event", confidence=0.65))
    llm = FakeLlm(extract=extraction("Match on Saturday", kind="task",
                                     event_start=datetime(2026, 10, 10, 10, 0)))
    out = ingestor(svc, jev_secrets, llm, jev=jev).process_message(
        INBOX, eml("pipe_request"), uid=1)
    assert [s["kind"] for s in pending(svc)] == ["task"]
    assert "Jev unsure (0.65); kept the model's task" in out.detail


# ── Jev for the duplicate check (addendum ZD) ──

def _dedup_pair(svc, secrets, jev, *, second_due=date(2026, 10, 9), match=None):
    """Stage a pending suggestion, then process a second message that finds it as S1."""
    set_config(svc, kind_decider="model")
    llm = FakeLlm(extract=[extraction("Bring the team snack list", due=date(2026, 10, 9)),
                           extraction("Team snack list", due=second_due, notes="Again.")],
                  match=match if match is not None else Match("new", None))
    ing = ingestor(svc, secrets, llm, jev=jev)
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    out = ing.process_message(INBOX, eml("pipe_no_message_id"), uid=2)
    return first, out, llm


def test_jev_dedup_target_that_changes_something_is_an_update(svc, jev_secrets):
    jev = FakeJev(match=jev_match("S1", 0.93, changed=0.8))
    first, out, llm = _dedup_pair(svc, jev_secrets, jev)
    assert (out.stage, out.outcome, out.suggestion_id) == ("dedup", "attached", first.suggestion_id)
    assert out.detail.startswith("update to a pending suggestion")
    assert "Jev p=0.93 (jev-1.13.0)" in out.detail
    assert llm.match_calls == []
    [(item, candidates)] = jev.match_calls
    assert item == {"label": "new", "title": "Team snack list", "notes": "Again.",
                    "due": "2026-10-09"}
    assert [(x["label"], x["title"], x["due"]) for x in candidates] == [
        ("S1", "Bring the team snack list", "2026-10-09")]
    [u] = review.suggestion_dto(pending(svc)[0])["updates"]
    assert u["notes"] == "Again."


def test_jev_dedup_target_that_changes_nothing_is_a_duplicate(svc, jev_secrets):
    jev = FakeJev(match=jev_match("S1", 0.93, changed=0.2))
    first, out, llm = _dedup_pair(svc, jev_secrets, jev)
    assert (out.stage, out.outcome, out.suggestion_id) == ("dedup", "attached", first.suggestion_id)
    assert out.detail.startswith("same as a pending suggestion")
    assert llm.match_calls == []


def test_jev_dedup_moved_deadline_is_an_update_whatever_jev_says(svc, jev_secrets):
    jev = FakeJev(match=jev_match("S1", 0.93, changed=0.1))
    _, out, llm = _dedup_pair(svc, jev_secrets, jev, second_due=date(2026, 10, 20))
    assert out.detail.startswith("update to a pending suggestion")
    [s] = pending(svc)
    assert s["due"] == "2026-10-20"
    assert llm.match_calls == []


def test_jev_dedup_no_same_candidate_is_new(svc, jev_secrets):
    jev = FakeJev(match=jev_match(None, 0.1))
    _, out, llm = _dedup_pair(svc, jev_secrets, jev)
    assert (out.stage, out.outcome) == ("stage", "staged")
    assert "Jev p=0.10 (jev-1.13.0)" in out.detail
    assert len(pending(svc)) == 2 and llm.match_calls == []


def test_jev_dedup_unsure_asks_claude(svc, jev_secrets):
    jev = FakeJev(match=jev_match(None, 0.4, unsure=True))
    first, out, llm = _dedup_pair(svc, jev_secrets, jev, match=Match("duplicate", "S1"))
    assert (out.outcome, out.suggestion_id) == ("attached", first.suggestion_id)
    assert "Jev unsure (p=0.40); asked Claude" in out.detail
    assert len(llm.match_calls) == 1 and len(jev.match_calls) == 1


def test_jev_dedup_failing_asks_claude(svc, jev_secrets):
    jev = FakeJev(match=JevError("TypeSafe is unavailable (529)", kind="transient"))
    first, out, llm = _dedup_pair(svc, jev_secrets, jev, match=Match("duplicate", "S1"))
    assert (out.outcome, out.suggestion_id) == ("attached", first.suggestion_id)
    assert "Jev unavailable (TypeSafe is unavailable (529)); asked Claude" in out.detail
    assert len(llm.match_calls) == 1


def test_jev_dedup_without_a_key_asks_claude_and_not_jev(svc, secrets):
    jev = FakeJev(match=jev_match("S1", 0.93, changed=0.8))
    first, out, llm = _dedup_pair(svc, secrets, jev, match=Match("duplicate", "S1"))
    assert (out.outcome, out.suggestion_id) == ("attached", first.suggestion_id)
    assert "Jev" not in out.detail
    assert len(llm.match_calls) == 1
    assert jev.match_calls == [] and jev.calls == []


def test_dedup_decider_model_asks_claude_even_with_a_key(svc, jev_secrets):
    set_config(svc, dedup_decider="model", kind_decider="model")
    jev = FakeJev(match=jev_match("S1", 0.93, changed=0.8))
    llm = FakeLlm(extract=[extraction("Bring the team snack list"), extraction("Team snack list")],
                  match=Match("duplicate", "S1"))
    ing = ingestor(svc, jev_secrets, llm, jev=jev)
    ing.process_message(INBOX, eml("pipe_request"), uid=1)
    out = ing.process_message(INBOX, eml("pipe_no_message_id"), uid=2)
    assert out.outcome == "attached"
    assert len(llm.match_calls) == 1 and jev.match_calls == []


def test_jev_dedup_rejected_candidate_is_suppressed(svc, jev_secrets):
    set_config(svc, kind_decider="model")
    llm = FakeLlm(extract=[extraction("Bring the team snack list", due=date(2026, 10, 9)),
                           extraction("Book the minibus", due=date(2026, 10, 10))])
    jev = FakeJev(match=jev_match("R1", 0.9, changed=0.1))
    ing = ingestor(svc, jev_secrets, llm, jev=jev)
    ing.process_message(INBOX, eml("pipe_request"), uid=1)
    [s] = pending(svc)
    review.reject(svc, s["id"])
    out = ing.process_message(INBOX, reply(1, "Could you also book the minibus?"), uid=2)
    assert (out.stage, out.outcome) == ("dedup", "suppressed")
    assert "Jev p=0.90" in out.detail
    [(_, candidates)] = jev.match_calls
    assert [x["label"] for x in candidates] == ["R1"]
    assert llm.match_calls == []


def test_jev_dedup_compares_deadlines_by_day_not_by_string(svc, jev_secrets):
    """An open task's due may be timed; the email's is a date. Same day ≠ moved."""
    from types import SimpleNamespace
    from smylted.mail.llm import Candidate
    jev = FakeJev(match=jev_match("T1", 0.93, changed=0.1))
    ing = ingestor(svc, jev_secrets, FakeLlm(), jev=jev)
    c = SimpleNamespace(key="mid:x@club.example", extra=[])
    ex = extraction("Team snack list", due=date(2026, 10, 9))
    same_day = [Candidate(label="T1", title="Bring the team snack list", notes="",
                          due="2026-10-09T17:00:00+02:00")]
    assert ing._jev_match(c, ex, same_day) == Match("duplicate", "T1")
    other_day = [Candidate(label="T1", title="Bring the team snack list", notes="",
                           due="2026-10-12T17:00:00+02:00")]
    assert ing._jev_match(c, ex, other_day) == Match("update", "T1")


# ── an interrupted run loses nothing (review fix A1) ──

def _claim_unsettled(svc, raw: bytes, *, uid: int = 1, age: timedelta = timedelta(minutes=5)):
    """The claim a run left behind when it died mid-message, `age` before NOW."""
    m = message.parse_message(raw)
    key = message.ledger_key(m)
    assert svc.mail(store.mail_claim, key, message_id=m.message_id,
                    thread_id=message.thread_id(m), folder="INBOX", uid=uid)
    svc.mail(lambda conn: conn.execute("UPDATE mail_ledger SET claimed_at=? WHERE key=?",
                                       (pipeline._iso(NOW - age), key)))
    return key


def test_a_claim_left_by_an_interrupted_run_is_read_by_the_next(svc, secrets):
    raw = eml("pipe_request")
    svc.mail(store.mail_set_cursor, "INBOX", uidvalidity=1, last_uid=0,
             last_scan_at=pipeline._iso(NOW - timedelta(minutes=10)))
    key = _claim_unsettled(svc, raw)
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    report = ingestor(svc, secrets, llm, source=inbox_source({1: raw})).run_once()
    assert report.ok, report.error
    assert report.counts == {"staged": 1}
    assert ledger(svc, key)["outcome"] == "staged"
    assert len(pending(svc)) == 1
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 1


def test_a_claim_held_by_an_unfinished_run_is_retried_not_a_duplicate(svc, secrets):
    raw = eml("pipe_request")
    _claim_unsettled(svc, raw)
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    out = ingestor(svc, secrets, llm).process_message(INBOX, raw, uid=1)
    assert (out.stage, out.outcome, out.transient) == ("ledger", "retry", True)
    assert out.detail == "an unfinished run holds this message"
    assert llm.extract_calls == []


def test_an_approval_stuck_for_ten_minutes_is_pending_again(svc, secrets):
    for sid, age in (("old", timedelta(minutes=11)), ("young", timedelta(minutes=5))):
        svc.mail(store.mail_insert_suggestion, sid, {
            "kind": "task", "title": "Pay", "sender": "office@school.example",
            "message_key": f"mid:{sid}@x", "thread_id": f"mid:{sid}@x"})
        assert svc.mail(store.mail_transition_suggestion, sid, "pending", "approving")
        svc.mail(lambda conn, sid=sid, age=age: conn.execute(
            "UPDATE mail_suggestions SET updated_at=? WHERE id=?",
            (pipeline._iso(NOW - age), sid)))
    assert ingestor(svc, secrets, source=inbox_source({})).run_once().ok
    assert svc.mail(store.mail_get_suggestion, "old")["status"] == "pending"
    assert svc.mail(store.mail_get_suggestion, "young")["status"] == "approving"


def test_request_stop_finishes_the_message_in_hand_and_saves_the_cursor(svc, secrets):
    source = inbox_source({1: eml("pipe_request"), 2: eml("pipe_no_message_id"),
                           3: eml("pipe_note_to_self")})
    holder = {}

    def extract(email):
        holder["ing"].request_stop()            # shutdown arrives mid-message
        return extraction("Bring the team snack list")

    llm = FakeLlm(extract=extract)
    ing = holder["ing"] = ingestor(svc, secrets, llm, source=source)
    report = ing.run_once()
    assert report.skipped_reason == "stopping" and report.counts == {"staged": 1}
    assert len(llm.extract_calls) == 1
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 1
    assert source.selected_names() == ["INBOX"]       # no further folder either
    again = ing.run_once()
    assert again.skipped_reason == "stopping" and len(llm.extract_calls) == 1
    assert ing.wait_idle(0.1) is True


def test_wait_idle_waits_for_a_running_scan(svc, secrets):
    ing = ingestor(svc, secrets)
    ing._run_lock.acquire()
    try:
        assert ing.wait_idle(0.05) is False
    finally:
        ing._run_lock.release()
    assert ing.wait_idle(0.05) is True


def test_the_service_refuses_mail_work_once_closed(tmp_path):
    s = make_service(tmp_path)
    s.close()
    with pytest.raises(RuntimeError, match="the service is closed"):
        s.mail(store.mail_get_cursor, "INBOX")


def test_a_message_that_cannot_be_parsed_is_settled_and_the_folder_goes_on(
        svc, secrets, monkeypatch):
    bad = plain("bad-1@school.example", "Broken", "BOOM")
    good = eml("pipe_request")
    real = message.parse_message

    def parse(raw):
        if b"BOOM" in raw:
            raise RecursionError("maximum recursion depth exceeded")
        return real(raw)

    monkeypatch.setattr(message, "parse_message", parse)
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    ing = ingestor(svc, secrets, llm, source=inbox_source({1: bad, 2: good}))
    report = ing.run_once()
    assert report.ok, report.error
    assert report.counts == {"error": 1, "staged": 1}
    row = ledger(svc, "hash:" + hashlib.sha256(bad).hexdigest())
    assert (row["stage"], row["outcome"]) == ("error", "error")
    assert "RecursionError" in row["detail"] and row["settled_at"]
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 2
    again = ing.process_message(INBOX, bad, uid=1)
    assert (again.stage, again.outcome) == ("ledger", "duplicate")


# ── the password is bound to its server (review fix A2) ──

def test_a_password_saved_for_other_server_settings_is_never_sent(svc, secrets):
    source = inbox_source({1: eml("pipe_request")})
    # Changed behind the binding's back, as a settings edit without a new password is.
    svc.mail(store.merge_meta_json, MAIL_SETTINGS_KEY, {"imap_host": "imap.attacker.example"})
    ing = ingestor(svc, secrets, source=source)
    report = ing.run_once()
    assert not report.ok and report.error == settings.PASSWORD_BINDING_MESSAGE
    with pytest.raises(MailConnectError) as e:
        ing.test_imap()
    assert e.value.kind == "config" and str(e.value) == settings.PASSWORD_BINDING_MESSAGE
    assert source.calls == []                          # the factory was never called


# ── merge races and rejections (review fixes A3, A4) ──

def test_a_suggestion_rejected_while_a_match_is_in_flight_is_left_alone(svc, secrets):
    holder = {}

    def match(item, candidates):
        holder["sid"] = pending(svc)[0]["id"]
        review.reject(svc, holder["sid"])             # the owner, while the model thinks
        return Match("update", "S1")

    llm = FakeLlm(extract=[extraction("Bring the team snack list", due=date(2026, 10, 9)),
                           extraction("Bring the team snack list", due=date(2026, 10, 12))],
                  match=match)
    ing = ingestor(svc, secrets, llm)
    ing.process_message(INBOX, eml("pipe_request"), uid=1)
    out = ing.process_message(INBOX, eml("pipe_no_message_id"), uid=2)
    assert (out.stage, out.outcome) == ("stage", "staged")
    rejected = svc.mail(store.mail_get_suggestion, holder["sid"])
    assert rejected["status"] == "rejected"
    assert rejected["updates"] == "[]" and rejected["due"] == "2026-10-09"
    [new] = pending(svc)
    assert new["id"] == out.suggestion_id and new["due"] == "2026-10-12"
    assert svc.mail(store.mail_get_thread, new["thread_id"])["suggestion_id"] == new["id"]


def test_merged_updates_carry_their_thread_and_sender_name(svc, secrets):
    llm = FakeLlm(extract=[extraction("Bring the team snack list"),
                           extraction("Bring cups", notes="Also cups.")])
    ing = ingestor(svc, secrets, llm)
    ing.process_message(INBOX, eml("pipe_request"), uid=1)
    ing.process_message(INBOX, eml("pipe_reply_quoting"), uid=2)
    [s] = pending(svc)
    [u] = pipeline._load_updates(s["updates"])
    assert u["thread_id"] == "mid:req-1@club.example" and u["sender_name"] == "Coach Miller"
    assert review.suggestion_dto(s)["updates"][0]["sender_name"] == "Coach Miller"


class _TaskHost:
    """The service, with the thread's task present and open."""

    def __init__(self, svc):
        self._svc = svc

    def __getattr__(self, name):
        return getattr(self._svc, name)

    def get_task(self, href, uid):
        return {"uid": uid, "list": "l", "summary": "Bring the team snack list", "notes": "",
                "completed": False, "cancelled": False, "due": None}


def test_a_dismissed_update_to_the_threads_task_stays_dismissed(svc, secrets):
    svc.mail(store.mail_upsert_thread, "mid:req-1@club.example", task_list="/c/l/",
             task_uid="t1")
    first = eml("pipe_reply_quoting")
    again = first.replace(b"<req-2@club.example>", b"<req-3@club.example>")
    llm = FakeLlm(extract=extraction("Bring cups"))
    ing = ingestor(svc, secrets, llm, host=_TaskHost(svc))
    out = ing.process_message(INBOX, first, uid=1)
    assert (out.stage, out.outcome) == ("dedup", "staged")
    review.reject(svc, out.suggestion_id)
    out = ing.process_message(INBOX, again, uid=2)
    assert (out.stage, out.outcome) == ("dedup", "suppressed")
    assert out.detail.startswith("same as a dismissed suggestion")
    assert pending(svc) == []


# ── invitations (review fix A5) ──

def _invite(n: int, *, start=b"20261014T180000", end=b"20261014T193000") -> bytes:
    return (eml("pipe_invite").replace(b"<invite-1@school.example>",
                                       f"<invite-{n}@school.example>".encode())
            .replace(b"20261014T180000", start).replace(b"20261014T193000", end))


def test_a_rescheduled_invitation_updates_the_pending_suggestion(svc, secrets):
    ing = ingestor(svc, secrets)
    first = ing.process_message(INBOX, _invite(1), uid=1)
    out = ing.process_message(INBOX, _invite(2, start=b"20261016T170000",
                                             end=b"20261016T183000"), uid=2)
    assert (out.stage, out.outcome, out.detail) == ("fastpath", "attached",
                                                     "updated the pending invitation")
    assert out.suggestion_id == first.suggestion_id
    [s] = pending(svc)
    assert s["event_start"] == "2026-10-16T17:00:00+02:00"
    assert s["event_end"] == "2026-10-16T18:30:00+02:00"
    [u] = pipeline._load_updates(s["updates"])
    assert u["notes"] == "Changed: 2026-10-16T17:00:00+02:00 at Main hall"
    assert u["thread_id"] == "mid:invite-2@school.example" and u["sender_name"] == "Ms Smith"
    # The same version again changes nothing.
    out = ing.process_message(INBOX, _invite(3, start=b"20261016T170000",
                                             end=b"20261016T183000"), uid=3)
    assert (out.outcome, out.detail) == ("duplicate", "event already suggested")


def test_a_dismissed_invitation_sent_again_is_not_staged(svc, secrets):
    ing = ingestor(svc, secrets)
    first = ing.process_message(INBOX, _invite(1), uid=1)
    review.reject(svc, first.suggestion_id)
    out = ing.process_message(INBOX, _invite(2, start=b"20261016T170000",
                                             end=b"20261016T183000"), uid=2)
    assert (out.stage, out.outcome) == ("fastpath", "suppressed")
    assert pending(svc) == []


def test_a_changed_invitation_after_approval_is_not_applied(svc, secrets):
    ing = ingestor(svc, secrets)
    first = ing.process_message(INBOX, _invite(1), uid=1)
    svc.mail(store.mail_transition_suggestion, first.suggestion_id, "pending", "approving")
    out = ing.process_message(INBOX, _invite(2, start=b"20261016T170000"), uid=2)
    assert (out.outcome, out.detail) == (
        "duplicate", "already added; changes to an added event are not applied")
    assert svc.mail(store.mail_get_suggestion, first.suggestion_id)["event_start"] == (
        "2026-10-14T18:00:00+02:00")


# ── date windows (review fix A6) ──

def test_an_old_message_at_a_higher_uid_is_not_read_after_the_window(svc, secrets):
    source = inbox_source({1: eml("pipe_request"), 2: eml("pipe_no_message_id")},
                          dates={1: at(2026, 10, 4), 2: at(2026, 8, 1)})
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    ing = ingestor(svc, secrets, llm, source=source)
    assert ing.run_once().ok
    cur = svc.mail(store.mail_get_cursor, "INBOX")
    assert (cur["last_uid"], cur["window_since"]) == (2, None)
    assert ing.run_once().ok
    assert len(llm.extract_calls) == 1


def test_a_truncated_window_continues_by_date_next_run(svc, secrets, monkeypatch):
    monkeypatch.setattr(pipeline, "MAX_PER_FOLDER_PER_RUN", 2)
    msgs = {u: plain(f"w{u}@school.example", f"Note {u}", f"Item {u}") for u in (1, 2, 3, 4)}
    source = inbox_source(msgs, dates={1: at(2026, 10, 4), 2: at(2026, 10, 4),
                                       3: at(2026, 8, 1), 4: at(2026, 10, 5)})
    llm = FakeLlm(extract=extraction(actionable=False))
    ing = ingestor(svc, secrets, llm, source=source)
    assert ing.run_once().ok
    cur = svc.mail(store.mail_get_cursor, "INBOX")
    since = (NOW - timedelta(days=ing.config().backfill_days)).date().isoformat()
    assert (cur["last_uid"], cur["window_since"]) == (2, since)
    assert ing.run_once().ok
    searches = [arg for name, arg in source.calls if name == "search_uids"]
    assert searches[-1] == {"after_uid": None, "since": date.fromisoformat(since)}
    assert [arg for name, arg in source.calls if name == "fetch"][-1] == [4]
    assert len(llm.extract_calls) == 3                    # 1, 2 and 4; never the old 3
    cur = svc.mail(store.mail_get_cursor, "INBOX")
    assert (cur["last_uid"], cur["window_since"]) == (4, None)


class _ExpungingSource(FakeMailSource):
    """Search finds UIDs that are gone by the time they are fetched."""

    def search_uids(self, *, after_uid=None, since=None):
        super().search_uids(after_uid=after_uid, since=since)
        return [3, 4]


def test_a_window_whose_messages_were_expunged_ends_at_uidnext(svc, secrets):
    source = _ExpungingSource({"INBOX": {"flags": [], "uidvalidity": 1, "messages": {},
                                         "uidnext": 10}})
    report = ingestor(svc, secrets, source=source).run_once()
    assert report.ok, report.error
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 9


# ── reconnecting (review fix A7) ──

class _DroppingSource(FakeMailSource):
    """Loses the connection when `fail_folder` is selected, `failures` times."""

    def __init__(self, folders, *, fail_folder: str, failures: int = 1):
        super().__init__(folders)
        self.fail_folder, self.failures = fail_folder, failures

    def select(self, folder):
        if folder.name == self.fail_folder and self.failures:
            self.failures -= 1
            self.calls.append(("select", folder.name))
            raise MailConnectError("the connection was closed", kind="network")
        return super().select(folder)


def _two_folders(**kw) -> _DroppingSource:
    return _DroppingSource(
        {"INBOX": {"flags": [], "uidvalidity": 1, "messages": {1: eml("pipe_request")},
                   "dates": {1: at(2026, 10, 5)}},
         "Labels/School": {"flags": [], "uidvalidity": 2,
                           "messages": {5: eml("pipe_note_to_self")},
                           "dates": {5: at(2026, 10, 5)}}},
        fail_folder="Labels/School", **kw)


def test_a_dropped_connection_is_reopened_once_and_the_folder_retried(svc, secrets):
    source = _two_folders()
    llm = FakeLlm(extract=[extraction("Bring the team snack list"), extraction("Buy stamps")])
    report = ingestor(svc, secrets, llm, source=source).run_once()
    assert report.ok, report.error
    assert report.reconnects == 1 and report.counts == {"staged": 2}
    assert [n for n, _ in source.calls].count("connect") == 2
    assert source.selected_names() == ["INBOX", "Labels/School", "Labels/School"]
    assert svc.mail(store.mail_get_cursor, "Labels/School")["last_uid"] == 5


def test_a_second_drop_ends_the_run(svc, secrets):
    source = _two_folders(failures=2)
    llm = FakeLlm(extract=extraction("Bring the team snack list"))
    report = ingestor(svc, secrets, llm, source=source).run_once()
    assert not report.ok and report.error == "the connection was closed"
    assert report.reconnects == 1
    assert svc.mail(store.mail_get_cursor, "INBOX")["last_uid"] == 1


# ── the connection test samples recent mail (review fix A8) ──

def test_test_imap_samples_the_ten_newest_inbox_messages(svc, secrets):
    msgs = {u: eml("pipe_request") for u in range(1, 13)}
    msgs[3] = eml("pipe_school_noreply_dmarc_pass")       # only an older one has headers
    source = inbox_source(msgs)
    result = ingestor(svc, secrets, source=source).test_imap()
    assert result["auth_results"] == {"checked": True, "present": True,
                                      "authserv_ids": ["mailin008.protonmail.ch"],
                                      "trusted": True, "sampled": 10}
    fetched = sorted(arg for name, arg in source.calls if name == "fetch_header_fields")
    assert fetched == list(range(3, 13))


# ── quote stripping is bounded (review fix A9) ──

def test_quote_stripping_reads_a_bounded_prefix_and_the_subject(svc, secrets, monkeypatch):
    seen = []
    real = message.strip_quotes

    def strip(text, **kw):
        seen.append((len(text), kw))
        return real(text, **kw)

    monkeypatch.setattr(message, "strip_quotes", strip)
    raw = plain("big-1@school.example", "Fwd: the form", "Sign the form.\n" + "x" * 300_000)
    ingestor(svc, secrets, FakeLlm(extract=extraction("Sign the form"))).process_message(
        INBOX, raw, uid=1)
    [(n, kw)] = seen
    assert n == pipeline.MAX_STRIP_CHARS == 200_000
    assert kw == {"subject": "Fwd: the form"}
