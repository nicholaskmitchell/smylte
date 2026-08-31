"""The per-item reminder over MCP — schema, validation, and the wire-write split.

Stub service, no Radicale: what is interesting here is not that the service
writes a sidecar row (test_notify_rules covers what the value then does) but
that a reminder-only edit never reaches the wire, and that a bad lead is a
sentence the model can act on rather than a 500.
"""
from __future__ import annotations

import pytest

from tasksd.mcp.api import McpApi
from tasksd.mcp.tools import ToolError, build_tools


class StubSvc:
    def __init__(self):
        self.sidecar_writes = []
        self.event_sidecar_writes = []
        self.edits = []
        self.tasks = {"t1": {"uid": "t1", "summary": "Renew passport"}}
        self.events = {"e1": {"uid": "e1", "summary": "Standup"}}

    def list_lists(self):
        return [{"id": "l", "href": "/u/l/", "name": "L"}]

    def list_calendars(self):
        return [{"id": "c", "href": "/u/c/", "name": "C"}]

    def resolve_list(self, list_id, *, component=None):
        return "/u/l/" if component == "VTODO" else "/u/c/"

    def has_task(self, href, uid):
        return uid in self.tasks

    def get_task(self, href, uid):
        return self.tasks.get(uid)

    def get_event(self, href, uid):
        return self.events.get(uid)

    def create_task(self, href, summary, *, edit=None, parent_uid=None):
        self.tasks["new"] = {"uid": "new", "summary": summary}
        return self.tasks["new"]

    def edit_task(self, href, uid, edit):
        self.edits.append(("task", uid, edit))
        return self.tasks.get(uid)

    def edit_event(self, href, uid, edit, *, recurrence_id=None, scope="all"):
        self.edits.append(("event", uid, edit))
        return self.events.get(uid)

    def set_sidecar(self, href, uid, **fields):
        self.sidecar_writes.append((uid, fields))
        return {**self.tasks.get(uid, {"uid": uid}), **fields}

    def set_event_sidecar(self, href, uid, **fields):
        self.event_sidecar_writes.append((uid, fields))
        return {**self.events.get(uid, {"uid": uid}), **fields}


@pytest.fixture
def api():
    return McpApi(StubSvc())


# ── the tool schemas ─────────────────────────────────────────────────────────

def test_every_tool_that_writes_an_item_offers_the_reminder():
    tools = build_tools(McpApi(StubSvc()))
    for name in ("smylte_create_task", "smylte_update_task",
                 "smylte_create_event", "smylte_update_event"):
        props = tools[name].schema["properties"]
        assert "notify_minutes_before" in props, name
        field = props["notify_minutes_before"]
        # -1 is the clear sentinel; a week is the cap.
        assert field["minimum"] == -1 and field["maximum"] == 10080


def test_the_schema_says_when_a_model_should_set_it():
    tools = build_tools(McpApi(StubSvc()))
    text = tools["smylte_create_task"].schema["properties"]["notify_minutes_before"]["description"]
    # The whole reason a blanket "task due soon" rule does not exist is that a
    # lead is the OWNER asking. A model that sets it unprompted recreates the
    # rule that was deliberately rejected.
    assert "owner asks" in text


# ── validation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [-2, 10081, "10", 10.5, True])
def test_an_unusable_lead_is_a_sentence_not_a_crash(api, bad):
    with pytest.raises(ToolError) as caught:
        api.update_task("l", "t1", {"notify_minutes_before": bad})
    assert "notify_minutes_before" in str(caught.value) or "minutes" in str(caught.value)


@pytest.mark.parametrize("ok", [0, 10, 10080, -1])
def test_the_whole_accepted_range_writes_the_sidecar(api, ok):
    api.update_task("l", "t1", {"notify_minutes_before": ok})
    assert api._svc.sidecar_writes == [("t1", {"notify_minutes_before": ok})]


# ── the wire-write split ─────────────────────────────────────────────────────

def test_a_reminder_only_task_edit_never_touches_the_wire(api):
    # An empty TaskEdit would PUT the resource back unchanged, move its etag and
    # make every other CalDAV client re-fetch it for nothing.
    api.update_task("l", "t1", {"notify_minutes_before": 30})
    assert api._svc.edits == []
    assert api._svc.sidecar_writes == [("t1", {"notify_minutes_before": 30})]


def test_a_reminder_only_event_edit_never_touches_the_wire(api):
    api.update_event("c", "e1", {"notify_minutes_before": 30})
    assert api._svc.edits == []
    assert api._svc.event_sidecar_writes == [("e1", {"notify_minutes_before": 30})]


def test_a_mixed_edit_does_both(api):
    api.update_task("l", "t1", {"summary": "Renewed", "notify_minutes_before": 15})
    assert len(api._svc.edits) == 1
    assert api._svc.sidecar_writes == [("t1", {"notify_minutes_before": 15})]


def test_a_reminder_only_edit_of_an_unknown_item_is_still_not_found(api):
    with pytest.raises(ToolError):
        api.update_task("l", "nope", {"notify_minutes_before": 5})
    with pytest.raises(ToolError):
        api.update_event("c", "nope", {"notify_minutes_before": 5})


def test_an_edit_with_nothing_in_it_still_says_so(api):
    with pytest.raises(ToolError) as caught:
        api.update_event("c", "e1", {})
    assert "Nothing to change" in str(caught.value)


# ── create ───────────────────────────────────────────────────────────────────

def test_a_created_task_gets_its_reminder_after_the_uid_exists(api):
    # The sidecar row is keyed on a uid that does not exist until the create
    # lands, so the write has to follow it.
    api.create_task("l", summary="Renew passport", notify_minutes_before=20)
    assert api._svc.sidecar_writes == [("new", {"notify_minutes_before": 20})]


def test_a_create_without_a_reminder_writes_no_sidecar_row(api):
    api.create_task("l", summary="Ordinary task")
    assert api._svc.sidecar_writes == []
