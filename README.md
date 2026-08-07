# Smylte

A self-hosted **tasks + calendar** web app (TickTick-style) backed by the
existing Radicale CalDAV server, live at `radicale.nicholaskmitchell.com`
(raw CalDAV for devices lives under `/dav`; clients that take only a hostname —
Apple's — find it via RFC 6764 discovery at the root). It is one CalDAV client among
several — Tasks.org (DAVx⁵), jtx Board, and Thunderbird share the same
collections and have equal rights. **Radicale is the source of truth; SQLite
is a disposable cache** (except the app-only sidecar — pins and app-only
metadata that have nowhere to live on the wire; see `docs/phase0-findings.md`).

The stack is a FastAPI backend (`tasksd`) that owns the CalDAV/sync/write path
and serves a React + Vite single-page app.

## Features

**Tasks.** Lists (create, rename, recolor, reorder, delete) and tasks with
subtasks, due dates (all-day or timed), priority, tags, and notes. List /
3-Day / Week layouts, quick-add, and drag-to-reschedule across day columns.
Every list is merged into one pane, dotted by list color; the sidebar works
just like the calendar's — each list is a row you click anywhere to show or hide
it individually, no separate "all" toggle — plus collapsible **groups** to
organize lists without widening the sidebar. Full-text search and tags.

**Calendar.** Month grid across multiple calendars, each with a
visibility toggle and non-destructive **archive** (hide without deleting;
restore from Settings). Events support all-day and timed spans, drag to move
or resize, and a mobile day-agenda. **VEVENT recurrence is implemented** —
author repeats and edit/delete a single occurrence, this-and-following, or the
whole series (`docs/recurrence-findings.md`). **Task (VTODO) recurrence stays
gated** pending real-device captures.

**Scheduling.** Calendly-style booking links: weekly availability, buffers,
minimum notice, and a horizon, with a public booking page at `/book/{token}`
that writes a real event onto the target calendar.

**Home.** The landing tab: a 12-column canvas of modules — Today, Overdue,
Upcoming, mini calendar, recently completed, booking links, upcoming bookings,
quick add — that you drag, resize and add/remove in **Arrange** mode. The layout
is account-synced. Arranging is desktop-only for now; phones render the same
modules stacked in the saved order. The mini calendar dots each day in its
calendars' colors, and a day opens a read-only list of its events.

**Tabs.** Settings → Tabs reorders the top strip and picks which tab the app
opens on — a fixed one, or wherever you left off. Both follow the account.

**Appearance.** Settings → Appearance opens a live editor over the design
system: every color token (with a picker and a raw OKLCH/hex field), corner
radius, text scale, gutter and row density, and the serif / sans / mono
families. Save named themes, export and import them as JSON, reset a single
token, one mode, or everything. A theme carries separate light and dark maps.

**The shipped design is never edited.** Customization is a sparse override
layer written as inline custom properties on `<html>`, so `styles/tokens.css`
stays the product's design and "Reset to Smylte" is simply dropping the
overrides. Editing while the default is active forks a new theme rather than
modifying it. Overrides are validated against a token allowlist on both sides
of the wire — the blob is re-read by a pre-paint script that writes straight
into the CSSOM, so a `url()` beacon or a property break-out must never survive
storage. `appearance.test.ts` asserts the defaults still match `tokens.css`.

**Across the app.** Optimistic writes (paint immediately, reconcile with the
server DTO, roll back on failure), live updates over Server-Sent Events, and
account-synced UI preferences (theme, appearance, dashboard layout, task view,
sidebar state, hidden/archived calendars, hidden lists, task groups). The
public gate is the app's own username/password (scrypt-hashed, cookie session);
Cloudflare Access is an optional second layer.

## Architecture

```
backend/
  tasksd/
    app.py      FastAPI app: /api routes, auth, SSE, serves the built SPA
    service.py  orchestration over the DAV client + cache + sync
    dav/        hand-rolled CalDAV client (httpx + lxml)
    ical/       icalendar read/extract + invariant-preserving edit path
                + canonicalizer + recurrence expansion
    db/         SQLite (WAL, FTS5) cache + app-only sidecar (schema.sql)
    sync/       sync engine (incremental / full resync / invalid-token
                fallback / orphan GC) + write path with 412 merge
    scheduling.py, auth.py, access.py, config.py
  tests/        api + security + sync + concurrency + fidelity + scheduling (pytest)
  dev/          empirical probes (fidelity comparison, normalization, smokes)
frontend/
  src/
    components/ TasksView, CalendarView, SchedulingView, HomeView, BookingPage,
                Sidebar, Login, AppearancePanel, ArchivedCalendarsModal
    api.ts      typed, same-origin API client (+ SSE subscribe)
    App.tsx     shell: tabs, settings, theme, live-refresh
    appearance.ts  token allowlist + validation, apply/reset, theme import/export
    dashboard.ts   Home grid math (pack/move/resize) — pure, unit-tested
    styles/     design tokens + app.css
scratch/        disposable Radicale 3.7.4 in Docker on :5233 (NEVER production)
deploy/         systemd unit, Caddy path-split snippet, cloudflared, setup.sh
docs/           DEPLOY.md, phase0-findings.md, recurrence-findings.md
```

## Develop

```bash
# 1. bring up the scratch Radicale (isolated; never touches production)
cd scratch && docker compose up -d --build      # http://127.0.0.1:5233

# 2. backend — deps in a venv, then run the API on 127.0.0.1:8080
cd ../backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
#    dev defaults already point at the scratch Radicale; auth can be disabled
#    for local work (see backend/tasksd/config.py and deploy/tasks.env.example)
TASKS_AUTH_ENABLED=false .venv/bin/python -m tasksd

# 3. frontend — Vite dev server proxies /api to the backend on :8080
cd ../frontend && npm install && npm run dev     # http://127.0.0.1:5173
```

For a production-shaped run, `npm run build` emits `frontend/dist/`, which the
backend serves statically (`TASKS_STATIC`) so the whole app is one origin.

```bash
# tests — integration tests target the scratch Radicale on :5233 and skip if
# it is down. Task-recurrence tests stay gated pending real-device captures.
cd backend && .venv/bin/python -m pytest        # incl. a concurrent-writer fuzz
cd frontend && npm test                          # vitest: unit + rendering (jsdom)

# handy probes
.venv/bin/python -m dev.ical_fidelity           # icalendar vs vobject scorecard
.venv/bin/python -m dev.radicale_normalization  # what Radicale does to a PUT
.venv/bin/python -m dev.smoke_dav               # end-to-end DAV client walkthrough
```

## Deployment

Live at `https://radicale.nicholaskmitchell.com` behind a Cloudflare tunnel and
a Caddy path split: `/dav*` → Radicale (device CalDAV sync), everything else →
the app on `127.0.0.1:8080`. The app authenticates to Radicale as you over
localhost; Radicale is never exposed except through `/dav`. Auto-deploys from
`main` via `~/tasks-autopull.sh` (cron, every minute). Full runbook, systemd
unit, and Caddy/cloudflared config in `docs/DEPLOY.md` and `deploy/`.

## Disclosure

Smylte was built with the assistance of AI coding tools — primarily
Anthropic's Claude, via Claude Code. The design decisions, the review, and
what ultimately ships are mine. Commits made with AI assistance carry a
`Co-Authored-By` trailer, so the record lives in `git log`, not just here.
