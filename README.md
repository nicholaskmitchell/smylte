# Task Manager

A TickTick-equivalent task web app backed by the existing Radicale CalDAV server,
destined for `tasks.nicholaskmitchell.com` (spec: the build sheet). One CalDAV
client among several — Tasks.org (DAVx⁵), jtx Board, and Thunderbird share the
same collections and have equal rights. **Radicale is the source of truth; SQLite
is a disposable cache** (except the app-only sidecar — see `docs/phase0-findings.md`).

## Status

- **Phase 0 (Foundation): complete and tested.** DAV client, iCalendar
  round-trip with fidelity guarantees, SQLite cache + sidecar, sync engine
  (incremental + full resync + invalid-token fallback + orphan GC), and the
  write path with 412 merge. 24 tests green, incl. a concurrent-writer fuzz.
- Phases 1–6: not started. Recurrence (§6) is gated pending real-device captures.

## Layout

```
backend/
  tasksd/
    dav/        hand-rolled CalDAV client (httpx + lxml)
    ical/       icalendar read/extract + invariant-#2 edit path + canonicalizer
    db/         SQLite (WAL, FTS5) cache + sidecar (raw sqlite3, schema.sql)
    sync/       sync engine + write path (create/edit/delete, 412 merge)
    config.py
  tests/        fidelity golden files + sync + concurrency (pytest)
  dev/          empirical probes (fidelity comparison, normalization, DAV smoke)
scratch/        disposable Radicale 3.7.4 in Docker on :5233 (NEVER production)
docs/           phase0-findings.md (incl. spec-vs-reality notes), recurrence (gated)
```

## Develop

```bash
# 1. bring up the scratch Radicale (isolated; never touches ~/radicale)
cd scratch && docker compose up -d --build

# 2. run the suite (integration tests target :5233 and skip if it's down)
cd ../backend && .venv/bin/python -m pytest

# handy probes
.venv/bin/python -m dev.ical_fidelity          # icalendar vs vobject scorecard
.venv/bin/python -m dev.radicale_normalization # what Radicale does to a PUT
.venv/bin/python -m dev.smoke_dav              # end-to-end DAV client walkthrough
```

The app itself (FastAPI/uvicorn on `127.0.0.1:8080`, behind the existing
Cloudflare Tunnel + Access) is not built yet — Phase 0 lands before any pixel.
See the build sheet and `docs/phase0-findings.md`.
