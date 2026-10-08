# Smylte

A self-hosted tasks and calendar app on top of a [Radicale](https://radicale.org)
CalDAV server. Smylte is one CalDAV client among several: Tasks.org (via
DAVx⁵), jtx Board, Thunderbird and Apple's clients can share the same
collections with it.

Radicale is the source of truth. The app's SQLite database is mostly a cache,
except for an app-only **sidecar**: manual order, pins, parking, the day plan,
habits, displays and day notes. These have no CalDAV equivalent, so a resync
can't rebuild them and backups must include them (see `docs/DEPLOY.md`).

The backend (`smylted`) is FastAPI and owns the CalDAV, sync and write path.
The frontend is a React + Vite single-page app that the backend serves.

The reasoning behind most of the design is in [`docs/DESIGN.md`](docs/DESIGN.md).

## Features

- **Tasks.** Lists, groups, subtasks, due dates, priority, tags and notes.
  List, 3-Day and Week views, quick add, and drag to reschedule or reorder.
  You can **park** a task to set it aside without completing it. Parking, the
  manual order and a task's original due date stay in Smylte and don't sync to
  other clients. Ticking a task's last subtask can complete the task itself
  (Settings → Tasks).
- **Calendar.** A month grid across several calendars, with archive (hide
  without deleting), drag to move or resize, and recurring events (edit one
  occurrence, this and following, or the whole series). Task lists can be shown
  on the grid. Task recurrence isn't supported yet.
- **Scheduling.** Booking links with weekly availability, buffers, minimum
  notice and a horizon. The public page at `/book/{token}` writes the booking to
  your calendar. Events marked Free don't block slots.
- **Home.** A dashboard of modules (today, overdue, upcoming, mini calendar,
  bookings, quick add, weekly count) that you can arrange on desktop.
- **Today.** A day plan that is fixed when you first open the day, holding
  tasks, notes and habits. Overdue work is offered rather than added. Past a
  configurable number of days, it asks for a new date or for you to park it.
  There's a planning step (day length, what goes on it, estimates), a shutdown
  step (what carries over, a note), and a read-only review of past days.
- **Focus.** A pomodoro view of today's plan at `/focus` that records time
  worked per row. The desktop client can show it in a floating window.
- **Notifications.** Optional, through Telegram: a daily digest, event
  reminders, bookings, sync failures and reminders you set on a task or event.
  More rules are available in Settings, off by default.
- **Email suggestions.** Optional. Reads chosen folders through Proton Mail
  Bridge and suggests tasks, task updates and events. Nothing is added until you
  approve it. Bulk mail is filtered in code before anything reaches the model.
  Secrets are write-only and kept out of the database.
- **Displays.** Read-only screens: the month, habits and today, or now and
  next. They work in a browser or on e-ink panels driven by a microcontroller,
  which fetch a packed 1-bit framebuffer from `/api/public/display/<token>.bin`.
  The display URL works as a password.
- **Appearance.** Three built-in designs (Smylte, Classic, Workspace), two
  layouts (Sidebar, Classic), and an editor for colours, radius, type and
  density. Custom themes can be saved, exported and imported.
- **Claude connector.** An optional remote MCP server at `/mcp`
  (`SMYLTE_MCP_ENABLED=true`) with about forty tools covering tasks, calendars,
  bookings and the day plan. It uses OAuth 2.1 with read-only or full access,
  and it can't open, back-date or write your notes about a day.
- **Desktop client.** Windows and Linux windows that load the app from local
  disk and update themselves. See [`desktop/README.md`](desktop/README.md).
- **Panel firmware.** A MicroPython example for a Pico 2 W and a Waveshare 7.5"
  e-paper panel. See [`firmware/README.md`](firmware/README.md).

Preferences (theme, layout, dashboard, views, hidden calendars and lists, clock,
language) are saved to your account. The app supports English and German, and a
12- or 24-hour clock.

## Architecture

```
backend/
  smylted/
    app.py        FastAPI app: /api routes, auth, SSE, serves the built SPA
    service.py    orchestration over the DAV client, cache and sync
    dav/          CalDAV client (httpx + lxml)
    ical/         iCalendar read, edit, canonicalise, recurrence expansion
    db/           SQLite (WAL, FTS5) cache and app-only sidecar (schema.sql)
    sync/         sync engine and write path with 412 merge
    mcp/          MCP server: OAuth 2.1 (oauth.py), transport (server.py),
                  tools (tools.py, api.py)
    notify/       Telegram sender, trigger rules, delivery sweep
    mail/         email suggestions: IMAP, parsing, sender auth, LLM call,
                  pipeline, review, secret store
    display/      display frames (frame.py) and the rasterizer (render.py)
    due.py, scheduling.py, auth.py, access.py, config.py, csp.py, limits.py
  tests/          pytest
  dev/            probes and build scripts
frontend/
  src/
    components/   views, settings sections, modals
    i18n/         string catalogues (en.ts, de.ts)
    api.ts        typed API client and SSE subscription
    App.tsx       shell: frame, settings, theme, live refresh
    styles/       design tokens, app.css, layout.css, display.css
firmware/         MicroPython example for a Pico 2 W + Waveshare 7.5"
desktop/          Windows (WinForms, WebView2) and Linux (GTK 4, WebKitGTK) clients
scratch/          disposable Radicale for development on :5233
deploy/           systemd unit, Caddy snippet, cloudflared, setup and autopull scripts
docs/             DEPLOY.md, DESIGN.md, findings
```

## Develop

```bash
# 1. scratch Radicale (isolated from any real server)
cd scratch && docker compose up -d --build      # http://127.0.0.1:5233

# 2. backend on 127.0.0.1:8080 (dev defaults point at the scratch Radicale)
cd ../backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SMYLTE_AUTH_ENABLED=false .venv/bin/python -m smylted

# 3. frontend; Vite proxies /api to :8080
cd ../frontend && npm install && npm run dev     # http://127.0.0.1:5173
```

`npm run build` writes `frontend/dist/`, which the backend serves when
`SMYLTE_STATIC` points at it. Configuration is in `backend/smylted/config.py` and
`deploy/smylte.env.example`.

```bash
cd backend && .venv/bin/python -m pytest        # integration tests need the scratch Radicale
cd frontend && npm test                          # vitest unit tests
cd frontend && npm run test:browser              # Playwright: Chromium and WebKit
```

## Deploy

Run Radicale and the app behind a reverse proxy that sends `/dav` to Radicale
and everything else to the app on `127.0.0.1:8080`. The app signs in to Radicale
over localhost. The public gate is the app's own username and password. A
Cloudflare tunnel or Cloudflare Access can sit in front. The full guide,
including backups, is in [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Disclosure

Smylte was built with the assistance of AI coding tools, mainly Anthropic's
Claude via Claude Code. The design decisions, the review, and what ships are
mine. Commits made with AI assistance carry a `Co-Authored-By` trailer.

## License

Copyright © 2026 Nicholas K. Mitchell.

Smylte is licensed under the **GNU Affero General Public License, version 3
only** (`AGPL-3.0-only`). See [`LICENSE`](LICENSE). If you run a modified copy
that other people use over a network, you must offer them its source. Settings →
About links to the source; in a fork, change `SOURCE_URL` in
`frontend/src/components/SettingsMenu.tsx` to point at your repository.

`firmware/` is MIT (`firmware/LICENSE`). The bundled typefaces (Newsreader,
Hanken Grotesk, JetBrains Mono, Fraunces, Inter) are under the SIL Open Font
License 1.1, with the licence text in `frontend/public/fonts/` and
`backend/smylted/display/fonts/`.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.
