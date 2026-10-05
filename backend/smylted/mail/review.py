"""The owner's side of the pipeline: list suggestions, approve one, reject one.

Nothing the mail pipeline proposes reaches the owner's lists until they press
Approve here; this module is the only place a suggestion becomes a CalDAV
write. The alternative — the pipeline writing tasks itself and the owner
deleting the wrong ones — would put whatever a stranger's email talked the
model into straight onto the owner's phone.

**Approval is a compare-and-swap.** A suggestion moves pending → approving
before anything is written and approving → approved after; two clicks (two
tabs, a double tap) race on the status column and only one creates the task.
A failed write moves it back to pending so the owner can try again. The
approved item's `client_id` is the suggestion id, so the UID it gets is
derived from the suggestion rather than minted fresh. What is written is read
from the row AFTER the swap: a message merged in between the owner opening
the card and pressing Approve (a moved deadline, a note) is part of it, and
one merged later finds the row no longer pending and becomes its own
suggestion.

**Provenance.** Every task or event written from mail ends its notes with a
line naming the sender, the subject and the date, so a task met weeks later
in another client still says where it came from. The notes of messages merged
into the suggestion come before it, one line each.

**Times.** An event the model read from prose has a naive start ("18:00 in
the email's own words"); it is placed in the owner's home time zone when one
is set, and left floating otherwise — the same rule the rest of Smylte uses
for times typed without a zone. An invite's times carry their own offset.

**Rejection is remembered per message.** Rejecting writes a row for the
suggestion's own message and for every message merged into it — each under
its own thread, since a merged message may come from another conversation —
so neither a rescan of the folder nor a later reply restating the same
request brings it back. The swap and those rows are one transaction, so a
message merged at the same moment is either rejected with the rest or staged
on its own. Rejecting never touches a task.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

import icalendar

from ..db import store
from ..ical.edit import UNSET, EventEdit, TaskEdit
from .redact import redact, redact_exc
from .settings import MailConfig

log = logging.getLogger("smylted.mail")

UNSET_DUE = object()
MAX_TITLE = 300


class ReviewError(Exception):
    """A refusal the route turns into an HTTP status (404, 409, 422, 502).
    The message is redacted and safe to show."""

    def __init__(self, message: str, *, status: int):
        super().__init__(redact(message))
        self.status = status


def _slug(href: str | None) -> str | None:
    return href.rstrip("/").rsplit("/", 1)[-1] if href else None


def _updates(row) -> list[dict]:
    try:
        data = json.loads(row["updates"] or "[]")
    except (TypeError, ValueError):
        return []
    return [u for u in data if isinstance(u, dict)] if isinstance(data, list) else []


def suggestion_dto(row, *, target_title: str | None = None) -> dict:
    kind = row["kind"]
    approved_item = (row["status"] == "approved" and kind in ("task", "event")
                     and row["target_uid"])
    return {
        "id": row["id"],
        "kind": kind,
        "status": row["status"],
        "title": row["title"],
        "notes": row["notes"] or "",
        "due": row["due"],
        "confidence": row["confidence"],
        "event": {
            "start": row["event_start"],
            "end": row["event_end"],
            "all_day": bool(row["event_all_day"]),
            "location": row["location"],
            "rrule": row["event_rrule"],
        } if kind == "event" else None,
        "target": {
            "list": _slug(row["target_list"]),
            "uid": row["target_uid"],
            "title": target_title,
        } if kind == "update" else None,
        "source": {
            "sender": row["sender"],
            "sender_name": row["sender_name"],
            "subject": row["subject"],
            "sent_at": row["sent_at"],
            "message_id": row["message_id"],
            "thread_id": row["thread_id"],
            "folder": row["folder"],
        },
        "updates": [{k: u.get(k) for k in ("sender", "sender_name", "subject", "sent_at",
                                              "notes", "due")}
                    for u in _updates(row)],
        "created_at": row["created_at"],
        "decided_at": row["decided_at"],
        "result": {"list": _slug(row["target_list"]), "uid": row["target_uid"]}
        if approved_item else None,
    }


def _target_title(host, row) -> str | None:
    if row["kind"] != "update" or not row["target_list"] or not row["target_uid"]:
        return None
    try:
        task = host.get_task(row["target_list"], row["target_uid"])
    except Exception:  # noqa: BLE001 — a missing title must not break the list
        return None
    return task["summary"] if task else None


def _dto(host, row) -> dict:
    return suggestion_dto(row, target_title=_target_title(host, row))


def list_suggestions(host, *, status: str | None, limit: int) -> list[dict]:
    rows = host.mail(store.mail_list_suggestions, status=status, limit=limit)
    return [_dto(host, r) for r in rows]


def _provenance(row) -> str:
    name, sender = row["sender_name"], row["sender"]
    line = f"From {name} <{sender}>" if name else f"From {sender}"
    if row["subject"]:
        line += f' · "{row["subject"]}"'
    if row["sent_at"]:
        line += f" · {row['sent_at'][:10]}"
    return line + " (via email)"


def _join(*parts: str) -> str:
    return "\n\n".join(p for p in (s.strip() for s in parts if s) if p)


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _first_id(collections: list[dict]) -> str | None:
    return collections[0]["id"] if collections else None


def _update_block(row, notes: str) -> str:
    """The lines appended to the task an update suggestion targets."""
    def line(who: str | None, sent_at: str | None, text: str | None) -> str:
        head = f"— Update from {who or 'unknown sender'}"
        if sent_at:
            head += f", {sent_at[:10]}"
        text = (text or "").strip()
        return f"{head}: {text}" if text else head

    lines = [line(row["sender_name"] or row["sender"], row["sent_at"], notes)]
    lines += [line(u.get("sender_name") or u.get("sender"), u.get("sent_at"), u.get("notes"))
              for u in _updates(row)]
    return "\n".join(lines)


def _merged_notes(row) -> str:
    """One line per merged message that added notes, for a new task or event."""
    lines = []
    for u in _updates(row):
        text = (u.get("notes") or "").strip()
        if not text:
            continue
        head = f"— {u.get('sender_name') or u.get('sender') or 'unknown sender'}"
        if u.get("sent_at"):
            head += f", {u['sent_at'][:10]}"
        lines.append(f"{head}: {text}")
    return "\n".join(lines)


def _moment(value: str | None, all_day: bool, tz) -> date | datetime | None:
    if not value:
        return None
    if all_day:
        return date.fromisoformat(value[:10])
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None and tz is not None:
        dt = dt.replace(tzinfo=tz)
    return dt


def approve(host, suggestion_id: str, *, config: MailConfig, title: str | None = None,
            notes: str | None = None, due=UNSET_DUE, list_id: str | None = None,
            calendar_id: str | None = None) -> dict:
    """Write the suggestion to CalDAV as a task, an update or an event.

    Overrides (`title`, `notes`, `due`, the list or calendar) are what the
    owner edited on the card; `due=None` clears the date, leaving it at
    `UNSET_DUE` keeps the suggested one.
    """
    row = host.mail(store.mail_get_suggestion, suggestion_id)
    if row is None:
        raise ReviewError("no such suggestion", status=404)
    if row["status"] != "pending":
        raise ReviewError(f"this suggestion is already {row['status']}", status=409)
    if not host.mail(store.mail_transition_suggestion, suggestion_id, "pending", "approving"):
        raise ReviewError("this suggestion was just handled elsewhere", status=409)
    # Re-read: a message merged since the first read (a moved due, a note)
    # belongs in what is written. Nothing can merge into it from here on.
    row = host.mail(store.mail_get_suggestion, suggestion_id)

    kind = row["kind"]
    new_title = (title or "").strip()
    if not new_title or len(new_title) > MAX_TITLE:
        new_title = row["title"]
    body = notes or row["notes"] or ""
    chosen_due = row["due"] if due is UNSET_DUE else due
    try:
        if kind == "task":
            lid = list_id or config.task_list or _first_id(host.list_lists())
            href = host.resolve_list(lid, component="VTODO") if lid else None
            if href is None:
                raise ReviewError("choose a list for this task", status=422)
            d = _as_date(chosen_due)
            edit = TaskEdit(description=_join(body, _merged_notes(row), _provenance(row)),
                            due=d if d is not None else UNSET)
            created = host.create_task(href, new_title, edit=edit, client_id=row["id"])
            result = (href, created["uid"])
        elif kind == "update":
            task = host.get_task(row["target_list"], row["target_uid"])
            if task is None:
                raise ReviewError("the task this updates no longer exists", status=409)
            d = _as_date(chosen_due)
            # A stuck 'approving' is put back to pending after 10 minutes, and
            # the edit may have landed before the process died. Creating a task
            # or an event is idempotent by client_id; appending notes is not,
            # so a line already in the notes is not appended a second time.
            # Checked per line, not per block: a reply merged in between the
            # reset and this approve adds a line, and the block as a whole
            # would then miss and append the first line again.
            block = _update_block(row, body)
            current = task["notes"] or ""
            existing = {ln.strip() for ln in current.splitlines() if ln.strip()}
            new = [ln for ln in block.splitlines() if ln.strip() and ln.strip() not in existing]
            if not new:
                description = UNSET
            else:
                description = (current.rstrip() + "\n\n" + "\n".join(new)).lstrip()
            edit = TaskEdit(description=description,
                            due=d if d is not None else UNSET)
            created = host.edit_task(row["target_list"], row["target_uid"], edit)
            result = None
        elif kind == "event":
            cid = calendar_id or config.event_calendar or _first_id(host.list_calendars())
            href = host.resolve_list(cid, component="VEVENT") if cid else None
            if href is None:
                raise ReviewError("choose a calendar for this event", status=422)
            home_tz = getattr(host, "_home_tz", None)
            tz = home_tz() if callable(home_tz) else None
            all_day = bool(row["event_all_day"])
            dtstart = _moment(row["event_start"], all_day, tz)
            if dtstart is None:
                raise ReviewError("this event has no start time", status=422)
            dtend = _moment(row["event_end"], all_day, tz)
            edit = EventEdit(
                location=row["location"] or UNSET,
                description=_join(body, _merged_notes(row), _provenance(row)),
                rrule=icalendar.vRecur.from_ical(row["event_rrule"]) if row["event_rrule"] else UNSET,
            )
            created = host.create_event(href, new_title, dtstart=dtstart, dtend=dtend, edit=edit,
                                        client_id=row["id"])
            result = (href, created["uid"])
        else:
            raise ReviewError(f"cannot approve a suggestion of kind {kind!r}", status=422)
    except ReviewError:
        host.mail(store.mail_transition_suggestion, suggestion_id, "approving", "pending")
        raise
    except Exception as exc:  # noqa: BLE001 — CalDAV, validation, anything: back to pending
        host.mail(store.mail_transition_suggestion, suggestion_id, "approving", "pending")
        reason = redact_exc(exc)
        log.warning("mail: approving suggestion %s failed: %s", suggestion_id, reason)
        raise ReviewError(f"could not save it: {reason}", status=502) from None

    d = _as_date(chosen_due)
    fields: dict[str, Any] = {"title": new_title, "notes": body,
                              "due": d.isoformat() if d is not None else None}
    if result is not None:
        fields["target_list"], fields["target_uid"] = result
    tid = row["thread_id"]

    def finish(conn):
        with store.tx(conn):
            store.mail_transition_suggestion(conn, suggestion_id, "approving", "approved", **fields)
            th = store.mail_get_thread(conn, tid)
            # Only unhook the thread from THIS suggestion: a newer pending one
            # it now feeds stays attached.
            unhook = {"suggestion_id": None} if th and th["suggestion_id"] == suggestion_id else {}
            if kind == "task":
                store.mail_upsert_thread(conn, tid, task_list=result[0], task_uid=result[1],
                                         **unhook)
            elif kind == "update":
                # The thread now feeds that task: a later reply is an update to
                # it without asking the dedup question again.
                store.mail_upsert_thread(conn, tid, task_list=row["target_list"],
                                         task_uid=row["target_uid"], **unhook)
            elif unhook:
                store.mail_upsert_thread(conn, tid, **unhook)
            return store.mail_get_suggestion(conn, suggestion_id)
    final = host.mail(finish)
    host.publish_mail_changed()
    return {"suggestion": _dto(host, final), "created": created}


def reject(host, suggestion_id: str) -> dict:
    """Dismiss a suggestion and remember the messages it came from."""
    row = host.mail(store.mail_get_suggestion, suggestion_id)
    if row is None:
        raise ReviewError("no such suggestion", status=404)

    def write(conn):
        with store.tx(conn):
            if not store.mail_transition_suggestion(conn, suggestion_id, "pending", "rejected"):
                return None
            # Read in this transaction: every message merged before the swap
            # is rejected with it, and none can merge after.
            cur = store.mail_get_suggestion(conn, suggestion_id)
            tid = cur["thread_id"]
            keys = [(cur["message_key"], cur["message_id"], tid)]
            keys += [(u.get("message_key"), u.get("message_id"), u.get("thread_id") or tid)
                     for u in _updates(cur) if u.get("message_key")]
            for key, mid, thread in keys:
                store.mail_add_rejection(conn, suggestion_id=suggestion_id, message_key=key,
                                         message_id=mid, thread_id=thread, title=cur["title"],
                                         due=cur["due"])
            th = store.mail_get_thread(conn, tid)
            if th is not None and th["suggestion_id"] == suggestion_id:
                store.mail_upsert_thread(conn, tid, suggestion_id=None)
            return store.mail_get_suggestion(conn, suggestion_id)
    final = host.mail(write)
    if final is None:
        current = host.mail(store.mail_get_suggestion, suggestion_id)
        status = current["status"] if current is not None else row["status"]
        raise ReviewError(f"this suggestion is already {status}", status=409)
    host.publish_mail_changed()
    return {"suggestion": _dto(host, final)}
