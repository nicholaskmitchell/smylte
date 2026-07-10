"""Manual integration smoke test for the DAV client, against SCRATCH Radicale.

Run: backend/.venv/bin/python -m dev.smoke_dav   (cwd = backend/)

Exercises the whole Phase-0 write/read/sync path and, along the way, empirically
answers three questions the spec makes me verify against this exact server:
  1. Does Radicale return 412 on an If-Match etag mismatch, even though the log
     says 'strict preconditions check: False'? (invariant #5)
  2. What status/body does a pruned/invalid sync token produce? (invariant #6)
  3. Does PUT return an ETag header, or must we HEAD for it?
"""
from __future__ import annotations

import sys

from tasksd.dav import DavClient, InvalidSyncToken, PreconditionFailed

VTODO = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//tasksd//smoke//EN\r\n"
    "BEGIN:VTODO\r\n"
    "UID:{uid}\r\n"
    "SUMMARY:{summary}\r\n"
    "X-FOREIGN-PROP:keep-me\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR\r\n"
)


def main() -> int:
    c = DavClient("http://127.0.0.1:5233", "testuser", "testpass")
    print("OPTIONS methods:", sorted(c.options()))

    col = c.create_task_collection("Smoke Inbox", components=("VTODO",))
    print("created task collection:", col.href, "is_task_list=", col.is_task_list)

    href = f"{col.href}task-1.ics"
    etag1 = c.put(href, VTODO.format(uid="task-1", summary="first").encode(), if_none_match="*")
    print("PUT #1 etag:", repr(etag1), "(empty means Radicale omitted ETag on PUT)")

    got = c.get(href)
    print("GET etag:", repr(got.etag), "body has X-FOREIGN-PROP:",
          b"X-FOREIGN-PROP" in (got.data or b""))

    # Q3: is the GET etag stable/usable for If-Match?
    etag = got.etag or etag1

    # Q1: stale If-Match must 412.
    try:
        c.put(href, VTODO.format(uid="task-1", summary="stale").encode(),
              if_match='"definitely-not-the-etag"')
        print("Q1 RESULT: no 412 on stale If-Match  <-- unexpected; note for conflict handling")
    except PreconditionFailed as e:
        print("Q1 RESULT: stale If-Match -> 412 as expected:", e.status)

    # Correct If-Match should succeed.
    etag2 = c.put(href, VTODO.format(uid="task-1", summary="second").encode(), if_match=etag)
    print("PUT #2 (correct If-Match) new etag:", repr(etag2))

    # sync: initial (full) then incremental.
    s0 = c.sync_collection(col.href)
    print("initial sync token:", s0.token[:40], "... changed:", len(s0.changed),
          "removed:", len(s0.removed))
    items = c.multiget(col.href, [i.href for i in s0.changed])
    print("multiget bodies:", len(items), "first body keeps X-FOREIGN-PROP:",
          any(b"X-FOREIGN-PROP" in (i.data or b"") for i in items))

    href2 = f"{col.href}task-2.ics"
    c.put(href2, VTODO.format(uid="task-2", summary="second task").encode(), if_none_match="*")
    s1 = c.sync_collection(col.href, s0.token)
    print("incremental sync: changed:", [i.href.rsplit('/', 1)[-1] for i in s1.changed],
          "removed:", s1.removed)

    c.delete(href2)
    s2 = c.sync_collection(col.href, s1.token)
    print("after delete, incremental removed:", [h.rsplit('/', 1)[-1] for h in s2.removed])

    # Q2: invalid sync token.
    try:
        c.sync_collection(col.href, "http://radicale.org/ns/sync/DEFINITELY-INVALID-TOKEN")
        print("Q2 RESULT: bogus token did NOT raise  <-- note; may return full set instead")
    except InvalidSyncToken as e:
        print(f"Q2 RESULT: bogus token -> InvalidSyncToken (status={e.status})")

    # cleanup this smoke collection
    c.delete_collection(col.href)
    print("cleaned up smoke collection")
    return 0


if __name__ == "__main__":
    sys.exit(main())
