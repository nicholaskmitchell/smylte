"""Approving and rejecting suggestions. The CalDAV writes run against the
scratch Radicale (marked `radicale`); the refusals need no server."""
from __future__ import annotations

import dataclasses
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from smylted.db import store
from smylted.ical.edit import UNSET
from smylted.mail import redact, review
from smylted.mail.imap import FolderInfo
from smylted.mail.llm import Match
from smylted.mail.pipeline import Ingestor
from smylted.mail.review import ReviewError
from smylted.mail.settings import MailConfig
from tests.conftest import api_settings
from tests.mail_fakes import (
    FakeJev,
    FakeLlm,
    at,
    extraction,
    make_service,
    make_store,
    set_config,
)

CORPUS = Path(__file__).parent / "corpus" / "mail"
INBOX = FolderInfo(name="INBOX", raw="INBOX", flags=frozenset(), delimiter="/")
CONFIG = {"enabled": True, "self_addresses": ["me@proton.me"], "folders": ["INBOX"]}


def eml(name: str) -> bytes:
    return (CORPUS / f"{name}.eml").read_bytes()


@pytest.fixture(autouse=True)
def _forget_secrets():
    redact.forget_all_for_tests()
    yield
    redact.forget_all_for_tests()


@pytest.fixture
def svc(tmp_path):
    s = make_service(tmp_path)
    set_config(s, **CONFIG)
    yield s
    s.close()


def ingest(svc, tmp_path, *extractions, names=("pipe_request",), host=None):
    llm = FakeLlm(extract=list(extractions))
    ing = Ingestor(host or svc, make_store(tmp_path), llm=llm, jev=FakeJev(),
                   clock=lambda: at(2026, 10, 6))
    return [ing.process_message(INBOX, eml(n), uid=i) for i, n in enumerate(names, 1)]


# ── without a server ──

def test_reject_remembers_the_message_and_its_merged_updates(svc, tmp_path):
    first, second = ingest(svc, tmp_path, extraction("Bring the team snack list"),
                           extraction("Bring cups", notes="Also cups."),
                           names=("pipe_request", "pipe_reply_quoting"))
    assert second.outcome == "attached"
    sid = first.suggestion_id
    out = review.reject(svc, sid)
    assert out["suggestion"]["status"] == "rejected" and out["suggestion"]["decided_at"]
    rows = svc.mail(store.mail_rejections_for_thread, "mid:req-1@club.example")
    assert sorted(r["message_key"] for r in rows) == ["mid:req-1@club.example",
                                                      "mid:req-2@club.example"]
    assert all(r["title"] == "Bring the team snack list" for r in rows)
    assert svc.mail(store.mail_get_thread, "mid:req-1@club.example")["suggestion_id"] is None

    with pytest.raises(ReviewError) as e:
        review.reject(svc, sid)
    assert e.value.status == 409 and "already rejected" in str(e.value)


def test_unknown_suggestion_is_404(svc):
    for call in (lambda: review.approve(svc, "0" * 32, config=MailConfig()),
                 lambda: review.reject(svc, "0" * 32)):
        with pytest.raises(ReviewError) as e:
            call()
        assert e.value.status == 404


def test_approving_a_task_with_no_lists_is_422_and_stays_pending(svc, tmp_path):
    [out] = ingest(svc, tmp_path, extraction("Bring the team snack list"))
    with pytest.raises(ReviewError) as e:
        review.approve(svc, out.suggestion_id, config=MailConfig())
    assert e.value.status == 422 and "choose a list" in str(e.value)
    assert svc.mail(store.mail_get_suggestion, out.suggestion_id)["status"] == "pending"


def test_dto_shape(svc, tmp_path):
    [task, event] = ingest(svc, tmp_path, extraction("Bring the team snack list",
                                                     due=date(2026, 10, 9)),
                           names=("pipe_request", "pipe_invite"))
    dtos = {d["kind"]: d for d in review.list_suggestions(svc, status="pending", limit=10)}
    t, ev = dtos["task"], dtos["event"]
    assert t["due"] == "2026-10-09" and t["event"] is None and t["target"] is None
    assert t["source"]["sender"] == "coach@club.example"
    assert t["source"]["thread_id"] == "mid:req-1@club.example"
    assert t["updates"] == [] and t["result"] is None
    assert ev["event"] == {"start": "2026-10-14T18:00:00+02:00",
                           "end": "2026-10-14T19:30:00+02:00", "all_day": False,
                           "location": "Main hall", "rrule": None}


class EventHost:
    """Just enough of the service to approve an event, recording the write."""

    def __init__(self, svc, tz):
        self._svc, self._tz = svc, tz
        self.events: list[dict] = []

    def mail(self, fn, *args, **kwargs):
        return self._svc.mail(fn, *args, **kwargs)

    def publish_mail_changed(self):
        pass

    def list_calendars(self):
        return [{"id": "family"}]

    def resolve_list(self, list_id, *, component=None):
        return "/dav/me/family/" if list_id == "family" and component == "VEVENT" else None

    def create_event(self, href, summary, *, dtstart, dtend=None, edit=None, client_id=None):
        self.events.append({"href": href, "summary": summary, "dtstart": dtstart,
                            "dtend": dtend, "edit": edit})
        return {"uid": f"{client_id}@smylted", "summary": summary}

    def get_task(self, href, uid):
        return None

    def _home_tz(self):
        return self._tz


@pytest.mark.parametrize("tz", [ZoneInfo("Europe/Berlin"), None])
def test_model_event_times_use_the_home_zone_when_set(svc, tmp_path, tz):
    [out] = ingest(svc, tmp_path, extraction("Parent evening", kind="event",
                                             event_start=datetime(2026, 10, 14, 18, 0),
                                             location="Main hall"))
    host = EventHost(svc, tz)
    result = review.approve(host, out.suggestion_id, config=MailConfig())
    [ev] = host.events
    assert ev["dtstart"] == datetime(2026, 10, 14, 18, 0, tzinfo=tz)
    assert ev["dtend"] is None
    assert ev["edit"].location == "Main hall"
    assert ev["edit"].description.endswith("From Coach Miller <coach@club.example> · "
                                           '"Snacks for Saturday" · 2026-10-05 (via email)')
    s = result["suggestion"]
    assert s["status"] == "approved" and s["result"] == {"list": "family",
                                                         "uid": f"{out.suggestion_id}@smylted"}


def test_auto_accept_is_off_by_default(svc, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(review, "approve", lambda *a, **k: calls.append(a))
    [out] = ingest(svc, tmp_path, extraction("Bring the team snack list", confidence=0.99))
    assert out.outcome == "staged" and calls == []


def test_auto_accept_failure_leaves_the_suggestion_pending(svc, tmp_path):
    set_config(svc, auto_accept_min_confidence=0.5)
    [out] = ingest(svc, tmp_path, extraction("Bring the team snack list", confidence=0.9))
    assert out.outcome == "staged"          # approval failed: no list on an unreachable server
    assert svc.mail(store.mail_get_suggestion, out.suggestion_id)["status"] == "pending"


class TaskHost:
    """Just enough of the service to approve a task, recording the write.
    `before_swap` runs once, just before approval's pending → approving swap."""

    def __init__(self, svc, before_swap=None):
        self._svc = svc
        self.before_swap = before_swap
        self.tasks: list[dict] = []

    def mail(self, fn, *args, **kwargs):
        if fn is store.mail_transition_suggestion and args[1:3] == ("pending", "approving"):
            hook, self.before_swap = self.before_swap, None
            if hook:
                hook()
        return self._svc.mail(fn, *args, **kwargs)

    def publish_mail_changed(self):
        pass

    def list_lists(self):
        return [{"id": "family"}]

    def resolve_list(self, list_id, *, component=None):
        return "/dav/me/family/" if list_id == "family" and component == "VTODO" else None

    def create_task(self, href, summary, *, edit=None, client_id=None):
        self.tasks.append({"href": href, "summary": summary, "edit": edit})
        return {"uid": f"{client_id}@smylted", "summary": summary}

    def get_task(self, href, uid):
        return None


def _ingestor(svc, tmp_path, llm):
    return Ingestor(svc, make_store(tmp_path), llm=llm, jev=FakeJev(),
                    clock=lambda: at(2026, 10, 6))


def test_approve_writes_what_was_merged_before_its_swap(svc, tmp_path):
    llm = FakeLlm(extract=[extraction("Bring the team snack list", due=date(2026, 10, 9)),
                           extraction("Bring cups", due=date(2026, 10, 10),
                                      notes="Also please bring cups.")])
    ing = _ingestor(svc, tmp_path, llm)
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    # The reply lands between the owner's click and the swap: it moves the due.
    host = TaskHost(svc, before_swap=lambda: ing.process_message(
        INBOX, eml("pipe_reply_quoting"), uid=2))
    result = review.approve(host, first.suggestion_id, config=MailConfig())
    [task] = host.tasks
    assert task["edit"].due == date(2026, 10, 10)
    assert result["suggestion"]["due"] == "2026-10-10"


def test_an_approved_task_carries_the_merged_notes(svc, tmp_path):
    llm = FakeLlm(extract=[extraction("Bring the team snack list", notes="Coach asked."),
                           extraction("Bring cups", notes="Also please bring cups.")])
    ing = _ingestor(svc, tmp_path, llm)
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    ing.process_message(INBOX, eml("pipe_reply_quoting"), uid=2)
    host = TaskHost(svc)
    review.approve(host, first.suggestion_id, config=MailConfig())
    [task] = host.tasks
    assert task["edit"].description == (
        "Coach asked.\n\n"
        "— Coach Miller, 2026-10-05: Also please bring cups.\n\n"
        'From Coach Miller <coach@club.example> · "Snacks for Saturday" · 2026-10-05 '
        "(via email)")


def test_reject_records_merged_messages_under_their_own_thread(svc, tmp_path):
    a = eml("pipe_request")                                            # thread req-1
    b = a.replace(b"<req-1@club.example>", b"<other-1@club.example>")  # another thread
    b_reply = eml("pipe_reply_quoting").replace(
        b"<req-1@club.example>", b"<other-1@club.example>").replace(b"<req-2@", b"<other-2@")
    llm = FakeLlm(extract=extraction("Bring the team snack list"),
                  match=Match("duplicate", "S1"))
    ing = _ingestor(svc, tmp_path, llm)
    first = ing.process_message(INBOX, a, uid=1)
    assert ing.process_message(INBOX, b, uid=2).outcome == "attached"
    review.reject(svc, first.suggestion_id)
    [row] = svc.mail(store.mail_rejections_for_thread, "mid:other-1@club.example")
    assert row["message_key"] == "mid:other-1@club.example"
    # So a reply in that other thread restating it stays dismissed.
    out = ing.process_message(INBOX, b_reply, uid=3)
    assert (out.stage, out.outcome) == ("dedup", "suppressed")


class UpdateHost(TaskHost):
    """A service with one open task that dedup finds and an update can edit."""

    TASK = {"uid": "t1", "list": "family", "summary": "Bring the team snack list",
            "notes": "Coach asked.", "due": None, "completed": False, "cancelled": False}

    def __init__(self, svc):
        super().__init__(svc)
        self.edits: list[dict] = []

    def search_open_tasks_any(self, terms, *, limit):
        return [dict(self.TASK)]

    def get_task(self, href, uid):
        return dict(self.TASK) if (href, uid) == ("/dav/me/family/", "t1") else None

    def edit_task(self, href, uid, edit):
        self.edits.append({"href": href, "uid": uid, "edit": edit})
        return dict(self.TASK)


def test_approving_an_update_maps_its_thread_to_the_task(svc, tmp_path):
    llm = FakeLlm(extract=[extraction("Bring the team snack list"),
                           extraction("Bring cups", notes="Also please bring cups.")],
                  match=Match("update", "T1"))
    host = UpdateHost(svc)
    ing = Ingestor(host, make_store(tmp_path), llm=llm, jev=FakeJev(),
                   clock=lambda: at(2026, 10, 6))
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    assert (first.stage, first.outcome) == ("dedup", "staged")
    assert first.detail.startswith("update to an open task")
    review.approve(host, first.suggestion_id, config=MailConfig())
    th = svc.mail(store.mail_get_thread, "mid:req-1@club.example")
    assert (th["task_list"], th["task_uid"], th["suggestion_id"]) == ("/dav/me/family/", "t1",
                                                                      None)

    # A later reply is an update to the same task, without asking again.
    out = ing.process_message(INBOX, eml("pipe_reply_quoting"), uid=2)
    assert (out.stage, out.outcome) == ("dedup", "staged")
    assert out.detail.startswith("update to the thread's task")
    upd = svc.mail(store.mail_get_suggestion, out.suggestion_id)
    assert (upd["kind"], upd["target_list"], upd["target_uid"]) == ("update", "/dav/me/family/",
                                                                    "t1")
    assert len(llm.match_calls) == 1


def test_an_update_names_merged_senders_by_name(svc, tmp_path):
    llm = FakeLlm(extract=[extraction("Bring the team snack list", notes="Snacks."),
                           extraction("Bring cups", notes="Also please bring cups.")],
                  match=Match("update", "T1"))
    host = UpdateHost(svc)
    ing = Ingestor(host, make_store(tmp_path), llm=llm, jev=FakeJev(),
                   clock=lambda: at(2026, 10, 6))
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    assert ing.process_message(INBOX, eml("pipe_reply_quoting"), uid=2).outcome == "attached"
    review.approve(host, first.suggestion_id, config=MailConfig())
    [e] = host.edits
    assert e["edit"].description == (
        "Coach asked.\n\n"
        "— Update from Coach Miller, 2026-10-05: Snacks.\n"
        "— Update from Coach Miller, 2026-10-05: Also please bring cups.")


class NotesHost(UpdateHost):
    """An `UpdateHost` whose task keeps the notes each edit writes."""

    def __init__(self, svc):
        super().__init__(svc)
        self.task = dict(self.TASK)

    def get_task(self, href, uid):
        return dict(self.task) if (href, uid) == ("/dav/me/family/", "t1") else None

    def edit_task(self, href, uid, edit):
        super().edit_task(href, uid, edit)
        if edit.description is not UNSET:
            self.task["notes"] = edit.description
        return dict(self.task)


def test_an_update_approved_again_after_a_stuck_reset_is_appended_once(svc, tmp_path):
    llm = FakeLlm(extract=extraction("Bring the team snack list", notes="Snacks."),
                  match=Match("update", "T1"))
    host = NotesHost(svc)
    ing = Ingestor(host, make_store(tmp_path), llm=llm, jev=FakeJev(),
                   clock=lambda: at(2026, 10, 6))
    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    review.approve(host, first.suggestion_id, config=MailConfig())
    # The edit landed but the process died before recording it: the row sits in
    # 'approving' until the stuck reset puts it back, and the owner approves again.
    assert svc.mail(store.mail_transition_suggestion, first.suggestion_id, "approved", "approving")
    assert svc.mail(store.mail_reset_stuck_approving, before="2999-01-01T00:00:00.000Z") == 1
    review.approve(host, first.suggestion_id, config=MailConfig())
    block = "— Update from Coach Miller, 2026-10-05: Snacks."
    assert host.task["notes"] == "Coach asked.\n\n" + block
    assert len(host.edits) == 2
    assert svc.mail(store.mail_get_suggestion, first.suggestion_id)["status"] == "approved"


# ── against the scratch Radicale ──

@pytest.fixture
def live(_scratch_up, tmp_path):
    from smylted.service import SmylteService

    s = SmylteService(dataclasses.replace(api_settings(str(tmp_path / "live.db"))))
    set_config(s, **CONFIG)
    tag = uuid.uuid4().hex[:8]
    lst = s.create_list(f"mail-review-{tag}")
    cal = s.create_calendar(f"mail-review-cal-{tag}")
    yield s, lst, cal
    for c in (lst, cal):
        try:
            s.delete_collection(c["href"])
        except Exception:  # noqa: BLE001
            pass
    s.close()


@pytest.mark.radicale
def test_approve_task_then_update_then_event(live, tmp_path):
    svc, lst, cal = live
    llm = FakeLlm(extract=[
        extraction("Bring the team snack list", due=date(2026, 10, 9), notes="Coach asked."),
        extraction("Bring cups too", due=date(2026, 10, 10), notes="Also cups."),
    ])
    ing = Ingestor(svc, make_store(tmp_path), llm=llm, jev=FakeJev(), clock=lambda: at(2026, 10, 6))
    cfg = MailConfig(task_list=lst["id"], event_calendar=cal["id"])

    first = ing.process_message(INBOX, eml("pipe_request"), uid=1)
    result = review.approve(svc, first.suggestion_id, config=cfg)
    task = result["created"]
    assert task["summary"] == "Bring the team snack list"
    assert task["due"].startswith("2026-10-09")
    assert "Coach asked." in task["notes"]
    assert 'From Coach Miller <coach@club.example> · "Snacks for Saturday"' in task["notes"]
    assert task["notes"].endswith("(via email)")
    assert result["suggestion"]["result"] == {"list": lst["id"], "uid": task["uid"]}
    th = svc.mail(store.mail_get_thread, "mid:req-1@club.example")
    assert (th["task_list"], th["task_uid"], th["suggestion_id"]) == (lst["href"], task["uid"], None)

    with pytest.raises(ReviewError) as e:
        review.approve(svc, first.suggestion_id, config=cfg)
    assert e.value.status == 409

    second = ing.process_message(INBOX, eml("pipe_reply_quoting"), uid=2)
    assert (second.stage, second.outcome) == ("dedup", "staged")
    upd = svc.mail(store.mail_get_suggestion, second.suggestion_id)
    assert (upd["kind"], upd["target_list"], upd["target_uid"]) == ("update", lst["href"],
                                                                    task["uid"])
    [dto] = review.list_suggestions(svc, status="pending", limit=10)
    assert dto["target"] == {"list": lst["id"], "uid": task["uid"],
                             "title": "Bring the team snack list"}

    review.approve(svc, second.suggestion_id, config=cfg)
    updated = svc.get_task(lst["href"], task["uid"])
    assert "Coach asked." in updated["notes"]
    assert "— Update from Coach Miller, 2026-10-05: Also cups." in updated["notes"]
    assert updated["due"].startswith("2026-10-10")

    invite = ing.process_message(INBOX, eml("pipe_invite"), uid=3)
    out = review.approve(svc, invite.suggestion_id, config=cfg)
    ev = svc.get_event(cal["href"], out["created"]["uid"])
    assert ev["summary"] == "Parent evening"
    assert out["suggestion"]["result"] == {"list": cal["id"], "uid": ev["uid"]}


@pytest.mark.radicale
def test_auto_accept_approves_a_confident_task(live, tmp_path):
    svc, lst, _ = live
    set_config(svc, auto_accept_min_confidence=0.5, task_list=lst["id"])
    [out] = ingest(svc, tmp_path, extraction("Bring the team snack list", confidence=0.9))
    row = svc.mail(store.mail_get_suggestion, out.suggestion_id)
    assert row["status"] == "approved" and row["target_list"] == lst["href"]
    assert svc.get_task(lst["href"], row["target_uid"])["summary"] == "Bring the team snack list"
