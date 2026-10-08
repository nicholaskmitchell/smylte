# Design notes

Why Smylte works the way it does. The README says what it does; this file is
for anyone changing it.

## Data

**CalDAV is the source of truth.** Radicale holds every task and event. SQLite
caches them, and a resync can rebuild the cache from scratch. The exception is
the **sidecar**: app-only state that has nowhere to live on the wire, such as
manual order, pins, parking, the original due date, the day plan, habits,
displays and day notes. Backups must include it (`docs/DEPLOY.md`,
`docs/phase0-findings.md`).

**State that other clients can't represent goes in the sidecar, not in an `X-`
property.** Tasks.org, jtx Board and Thunderbird share the same collections and
would show an invented status or property as nothing at all. Parking, per-item
reminders and the original due date follow this rule. The cost is stated in the
UI: a parked task still appears in those clients.

**One sort order** (`order.ts`): manual position, then due date (undated last),
priority, title and uid. Including the uid makes it a total order, so the
array's own order never shows through, and an optimistically added task appears
where it belongs instead of jumping when the server answers. Manual order is
global rather than per list, because the task pane always shows lists merged.

**Subtasks reorder only among their siblings.** Dragging one out from under its
parent would be re-parenting, not ordering. Subtasks are usually a sequence, and
without a manual order undated, unprioritised steps would fall into title order.

## Tasks

**Parking** is the neutral fourth state beside needs-action, done and
cancelled. Cancelled reads as a verdict, so in practice nothing ever left a list.
A parked task leaves the lists, the day's automatic rows, the open counts and
the digest, and comes back unchanged. It is never reported as done. Nothing
clears it automatically: a completion can arrive from a phone through sync, and
a flag that cleared on Smylte's own writes but not on synced ones would leave
two identical tasks disagreeing.

**Ticking the last subtask completes the parent.** A parent with nothing left
in it is a row nobody can act on. "Nothing left" means every step is done or
won't-do. A parked step keeps the parent open, because it is coming back. The
rule walks upward, so finishing a checklist can close the task above it. It runs
only when a write from Smylte settles a step. Renames and note edits don't
trigger it, and neither does another client ticking the last box, since a sync
engine that wrote back would turn every incoming change into an outgoing one. A
failed close never rolls back the tick that caused it. It is the one preference
that writes to the server on the user's behalf, so it is a setting (on by
default) rather than a fixed rule.

## Calendar

Archive hides a calendar in Smylte only. The task-list overlay on the grid is an
allowlist, unlike the calendar toggles, because tasks are an addition to a view
that never had them. Event recurrence is implemented
(`docs/recurrence-findings.md`). Task (VTODO) recurrence stays disabled until it
can be checked against captures from real devices.

## Scheduling

Busy/Free is iCalendar's `TRANSP`, which Apple Calendar, Google Calendar and
Thunderbird already write. A Free event is left out of the busy set behind the
booking page, out of the redacted busy blocks shown on it, and out of
`smylte_find_free_time`. A missing or unrecognised value counts as Busy, which
is RFC 5545's default. A page that publishes availability to strangers should
only ever be wrong by over-blocking.

## Today

**A snapshot, not a query.** Every other task view recomputes on every paint,
so the list shifts under you all day. The first time a day is opened, the
backend freezes what is due that day and what was left unfinished on the last
planned day. After that the day is arranged by hand.

**Late work is offered, not placed.** A deadline set for today is a commitment.
A deadline already missed is a decision not yet made, and putting it back on the
day every morning makes that decision by default. Overdue tasks appear in the
strip below the day with what is due tomorrow and what has gone untouched for
three weeks. Moving one onto the day is a deliberate act.

**After a few days, it asks.** The threshold is three days by default, and 0
turns it off. Past it, a task gets two answers: a new date, or park it. Adding it
to today is deliberately not offered, because it leaves the deadline in place and
the task is late again tomorrow. Nothing is hidden. The task stays on its list,
stays marked overdue, and the Home Overdue module still lists it with a count of
how many are waiting on a decision.

**A new date doesn't erase the old one.** DUE holds one value, so rescheduling
used to lose the fact that a task was ever late. The deadline a task is moved
off is remembered and shown as "was due …". It is stamped once and never
rewritten, so a task moved four times still names its first promised date. It
is recorded only when the old date had already passed, because moving future
work is planning, not slipping. The task editor is where it can be cleared.

**Rows and the add box.** A filled square is a task (a real VTODO that syncs),
a hollow one is a note (this day only, in Smylte only), and `↻` is a habit. The
add box parses a line ("invoice friday", "gym at 7") and shows what Enter will
create and where, with a one-press switch between task and note.

**Habits** are rules that add a row to the day on chosen weekdays. Each
occurrence is an ordinary day-plan row. No VTODO or RRULE is written, so nothing
reaches the shared collections. The weekly count is over occurrences that exist,
so days the app wasn't opened don't count against you, and it is never coloured
as a failure.

**Planning** has three steps: how long the day is, what goes on it, and how
long each thing takes. Length can be given as "until 6pm" or "5h", with a
default per weekday in Settings. An account that has never stated a length gets
no load figures at all, because inventing an eight-hour day is the one thing
this must not do. Overcommitting is never blocked. The button reads *Start it
anyway* beside *Trim something*, so the warning is part of the decision rather
than read after it. How far over the day was at commit time is recorded and
shown once in the review, as a fact rather than a score.

**Shutdown** mirrors planning: what happened, what carries over, and a note.
Each unfinished row can go to tomorrow, to a named day, or off the plan.
Leaving it alone lets the automatic carry handle it. Moved work is recorded as
moved, not abandoned. Nothing scores the day: no percentage, streak or colour.

**Review** splits a day by where each row came from (chosen, carried over,
derived, habits), what was moved or dropped, and what was finished without being
planned. A past day is read-only, because a log you can fill in afterwards is a
scorecard. Only today can be opened. Reading a past day never creates one.

**Finished this week** is one number: tasks completed, counted by the
`COMPLETED` stamp, so a task ticked in Tasks.org counts too and earlier weeks
are covered. Notes and habits are excluded, since folding habits in would let
the figure rise on a day nothing was finished. There's no target and no colour.
Home shows the last few weeks so the number has context.

## Focus

- **The server keeps anchors, not counters.** It stores when the current phase
  began and how much was banked before it. Every transition settles first,
  crediting the elapsed time to the row, clamped to what the phase had left.
  That is why two windows agree to the second, a refresh loses nothing, and a
  laptop closed mid-interval credits only the rest of that interval.
- **The server names the row.** Ticking the current row anywhere (Today, a
  phone, Thunderbird) moves the cursor, and the focus view follows.
- **A clock that ran out while nobody was watching waits.** "Roll straight on"
  applies only to a live screen. A session found past its end asks.
- **It never opens a day.** Like displays and the connector, it points you to
  Today instead.
- **It records one number:** worked time per row, shown beside the estimate and
  never as a ratio, streak or colour. The connector exposes it as
  `worked_minutes` beside `planned_minutes`.
- A row either stops at its estimate or runs until done. The default is until
  done, so the app never moves you off something you didn't ask to leave.

## Notifications

`backend/smylted/notify/rules.py` holds the whole policy, including the test a
new rule has to pass: a notification must tell you something you can't recover
by opening the app later. Four rules meet that and are on by default: the daily
digest (which replaces opening the app), a warning before an event (which a
morning digest can't cover), a new booking (the only thing that arrives from
outside), and sync failure (the one state where the screen looks normal but the
data is frozen).

- Bookings and sync failures always arrive silent. Nothing can be done about
  either at 3am. That is fixed in code, which is why there are no quiet hours.
  Everything that buzzes is timed by an hour you set or an event in your
  calendar.
- Past eight buzzing messages in a day, the rest are sent silently rather than
  dropped. A sweep that would send three or more messages sends one.
- Per-item reminders are stored app-side rather than as `VALARM`. Tasks.org,
  Thunderbird and Apple Calendar would each fire their own alarm from a VALARM,
  so one reminder would arrive three times.
- Eight more rules exist, off by default, each documented with why. Before
  every task is due, overdue counts, "today isn't planned" and the others
  restate something already on screen.
- The bot token is write-only, so the settings the page loads never carry a
  working bot. **Send a test message** exists because every way of getting a
  token or chat id wrong fails silently.

## Email suggestions

Most of the work is deciding what not to read, and that is code, not a model.
Messages already seen (by Message-ID, or a hash) are skipped first. Sent,
Drafts, All Mail, Spam and Trash are never opened. Your own mail is skipped
unless it is a note to yourself. Bulk-shaped mail (`List-Unsubscribe`,
`Precedence: bulk`, auto-replies, no-reply senders) is skipped unless the sender
is on the always-read list **and** Proton's DMARC verdict confirms them. An
allowlist that anyone can satisfy by typing an address into From isn't one.
Calendar invitations become events without a model call.

What's left goes to Claude with quoted replies removed, in one call whose only
tool records an answer. The model never has a tool that touches Smylte, and the
email is passed as data between markers it can't forge. A reply in a thread that
already has a task becomes an update to it.

Two narrow decisions can go to TypeSafe's Jev: task or event, and whether a new
item duplicates an existing task. Claude decides when Jev is unsure,
unreachable or unconfigured. This split was measured (`backend/dev/mail_eval/`):
on the same labelled mail, Claude alone merged a genuinely new request into an
existing task 4 times in 98, which hides a task, and Jev with Claude as fallback
did not once. Task-or-event can also be decided by a small validated rule
language, checked on save.

Secrets are write-only and live in the OS keyring, or encrypted under a key file
outside the repository on a headless server, never in `smylte.db`. The Bridge
password is bound to the server it was entered for. Changing the host, port,
encryption, certificate or username clears it, so a changed setting can't send
it elsewhere.

## Displays

**No input, by design.** A display has no session, no controls and nothing
focusable. Its URL reaches one read-only call.

**Three modes.** *The month* is drawn like a paper wall calendar: six fixed
weeks, Sunday first. *Habits + today* gets shorter as the day goes, and its
count is taken before done habits are hidden. *Now + next* shows the first
unfinished row of today's plan, the one after it, and a count of the rest. It
advances when something is ticked off anywhere, on the panel's next poll. There
is deliberately no plain task-list mode: a screen with no scroll would show the
first eight of forty while implying that was all of them. Two rows and "+6" is
the whole day.

**A display never opens a day.** An unopened day shows a labelled preview of
what opening it would derive, and writes nothing.

**It uses the app's own design**, not the account's theme or the Classic
preset, since a choice made for a laptop shouldn't carry to a screen read across
a room. Newsreader for the month and names, uppercase JetBrains Mono for labels
and clocks, Hanken Grotesk for text. The server-side renderer uses static
instances of the same woff2 files.

**E-ink is designed for one bit, not a dark theme inverted.**
- No grey: an intermediate value becomes a shimmering dither, so hierarchy is
  carried by size, weight and rules. Days outside the month are a size smaller,
  not fainter.
- No colour: a calendar is identified by the shape of its mark (filled, hollow,
  left bar, dotted). Past four calendars, chips get a letter.
- Newsreader is pinned to optical size 12 on e-ink. At its default of 18 the
  hairlines break up when thresholded ("10" read as "I0" on a 4.2" panel). Mono
  labels sit one weight heavier than in the app, because they are read from
  across a room.
- The grid is always six weeks, so the layout never changes height and forces a
  full-panel flash.

**Small panels are told, not smeared.** The month needs about 360×260. Below
that the panel says it is too small and names a mode that fits, and Settings
warns as soon as the size is typed. Above it, the grid is sized by column width,
which is what portrait panels need. *Now + next* has no floor, and its type is
fitted to the panel, because its content is always two items.

**Three ways to drive one.** A browser opens `/display/<token>`. A
microcontroller fetches `.bin`, the packed 1-bit framebuffer (8 pixels a byte,
MSB leftmost, 1 = white, i.e. `framebuf.MONO_HLSB`), and reads it straight into
the driver's buffer. That format exists because PNG needs zlib and five
unfilters and BMP is stored bottom-up with padded rows. Boards with a decoder can
use `.png` or `.bmp`, and there's JSON for anyone drawing it themselves. `.png`
and `.bmp` are 1-bit only while the display is set to e-ink. Switch it to colour
and the same URL serves 24-bit BGR (1,152,054 bytes instead of 48,000). `.bin`
is 1-bit by construction and rejects a palette parameter.

**Refresh and caching.** E-ink is limited to one refresh every three minutes,
because panel makers say faster refreshes damage the screen permanently. Colour
screens can refresh every minute. Every response answers 304 to a matching
`If-None-Match`, so a panel polling every five minutes doesn't flash 288 times a
day to redraw a month that changed twice. Content is built once
(`display/frame.py`) and rasterized per format, with every string already
formatted in the account's language and clock.

**The URL is the credential.** Unlike a booking link, it shows the calendar
itself. It is 32 bytes, reaches one read-only call, and *New URL* re-keys a
display in place, keeping its configuration so there's no reason to leave a
leaked token in use. Settings → Developer previews every mode at real panel
sizes without creating tokens.

## Appearance

Three designs ship. **Smylte** is the default: warm off-white, one orange accent,
Newsreader for reading, Hanken Grotesk for interface, JetBrains Mono for labels
and figures, with a radius scale, soft shadows and eased motion. The app's sizes
were set for Inter, and Hanken sets smaller and lighter, so sans text is
x-height-normalised (`font-size-adjust`, `--sans-adjust`) rather than resized.
Serif and mono reset it to `none`, and only Hanken gets it. **Classic** is the
earlier design, kept exactly: Fraunces, Inter, sharp corners, uppercase mono
controls, hard shadows, no entrance motion. Its palette is the default's, and
what it restores beyond tokens lives in `styles/classic.css` as the old value of
each lever `app.css` reads. **Workspace** is neutral greys, a blue accent and one
system sans.

Layout is a separate choice. **Sidebar** keeps views, the open view's collections
and Settings in one column. Tasks and Calendar lend their lists through a portal
(`shell.tsx`), so the collections stay the view's own code. **Classic** is the
original tab strip. Everything the Sidebar layout draws is in `styles/layout.css`
scoped to `data-layout="sidebar"`, and `design-tokens.test.ts` fails if a rule
there could match in Classic.

**No shipped design is ever edited.** Customisation is a sparse override layer
of inline custom properties on `<html>`, so resetting is dropping the overrides.
Presets live in `tokens.css` under `:root[data-preset=…]`, which keeps them
uneditable and lets a palette fix reach everyone on deploy. Editing a preset
forks a theme seeded with its values. A theme carries tokens only, so a fork of
Classic keeps its type, corners and capitals but takes the current controls,
shadows and motion. Overrides are validated against a token allowlist on both
sides, because a pre-paint script writes them into the CSSOM and a `url()` beacon
or a property break-out must never survive storage. `appearance.test.ts` checks
the defaults and presets against `tokens.css`.

## Claude connector

- **Read-only about whether a day exists.** A connector can see today, add to
  it, estimate, move rows, tick notes and review a day. It can't open one.
  Asking about an unopened day returns a labelled preview and writes nothing. A
  past day can't be planned.
- **It reports your declarations about a day** (capacity, start, shutdown,
  note) so a model can see you're already over before proposing more. It can't
  write them. For the same reason it has no tool for creating habit rules, and
  it can't set an estimate on a past day.
- **It is its own OAuth 2.1 authorization server**, since there's one account
  and no identity provider. Connecting needs the app password on a consent
  screen, where you choose read-only or full access. Tokens are opaque, stored
  as hashes, and bound to this server. Refresh tokens rotate, and presenting a
  used one revokes the whole grant. Changing the app password or session secret
  revokes grants too.
- **Off unless enabled**, because it adds public OAuth endpoints. With it on,
  the app refuses to start without a public URL, app auth and a persistent
  session secret.

## Across the app

Writes are optimistic: paint immediately, reconcile with the server's response,
roll back on failure. Live updates arrive over Server-Sent Events.

`time.ts` is the only place a clock is formatted, so the 12/24-hour setting has
one place to land. Native date and time pickers are drawn by the browser and
follow the element's `lang` in Chrome, Edge and the Windows client. Firefox and
WebKit (including the Linux client) follow the OS instead. The public booking
page always uses the visitor's locale.

## Desktop client

**A host, not a rewrite.** Each client hosts the engine its OS already has
(WebView2 on Windows, WebKitGTK on Linux), so rendering is the browser's. The
gain is that the shell, CSS, JS and fonts load from disk, and installing is one
self-updating file. API calls still go to the server.

**The page talks to the host over HTTP**, not a webview bridge. That kept the
Linux port small: about 1,100 lines (local server, updater, session, settings)
are shared and covered by one test suite that runs on either OS. Those shared
files stay in `desktop/Smylte.Desktop/` because `desktop-release.yml` hashes
that directory to decide whether to republish the exe, and
`backend/tests/test_csp.py` reads `LocalServer.cs` by path. Linux window classes
hold their `Gtk.Window` rather than subclassing it, because GirCore has marked
those constructors obsolete.

**Updates.** The web build is one asset shared by both clients and checked on
every launch. Binaries are compared by content hash rather than version number,
because a forgotten version bump would ship a client nobody is told about. CI
republishes a binary only when its sources changed, since a self-contained
bundle is never byte-identical and would otherwise look new on every push. The
two clients have different keys: the Linux client links the shared sources, so
its key hashes both directories. One shared key would tell every Windows user to
download 69 MB when a GTK file moved. The swap renames the running file aside
(Windows can't overwrite a running image) and waits for the old process to exit
(on Linux the single-instance D-Bus name would otherwise just raise the old
window).

**The icon.** Icons are generated by `backend/dev/build_app_icon.py` from
`frontend/public/favicon.svg`; CI checks them byte by byte. The Windows icon is
not the favicon. Windows composites the file literally, and a cream plate fails
on both taskbar themes (1.05:1 on light, 13.98:1 on dark). A `.ico` has one image
per size and no light/dark variant, and burnt orange is the only brand colour
above 3:1 on both, so the compiled icon is a rounded accent plate. Following the
theme is possible only at runtime. On Windows 11 the grouped taskbar button
takes its icon from a Start menu shortcut, never from the window, so that
shortcut is an opt-in toggle. GTK sets icons by name, so Linux gets more for
free, and its toggle writes the applications-menu entry instead. The entry's
basename, `StartupWMClass` and program name must all match or GNOME shows a
generic icon. Small sizes are drawn from stroke-offset masters rather than
downscaled, and the generator refuses to write a size that misses its legibility
floors.

**The title bar.** On Windows 11 the caption is painted the app's `--bg` with
`DwmSetWindowAttribute`; Windows 10 offers only light or dark. X11 and Wayland
have no way to colour a server-side frame, so the Linux client draws its own
`GtkHeaderBar`. That drops the window manager's decoration theme entirely, which
is why *System title bar* exists. On Linux it takes effect after a restart,
because `gtk_window_set_titlebar` on a visible window does nothing and
unrealizing it would destroy the WebKit surface. The header bar's stylesheet
rules carry a class so they can't reach the default header bar GTK builds on
GNOME Wayland.

**Wayland is the default.** Staying on top, reopening in place and staying out
of the task list are EWMH features that Wayland lacks. The client used to force
X11 to keep them, but XWayland has one scale factor for every monitor and
stretches bitmaps under fractional scaling, which blurred the main window for
every GNOME Wayland user. `"Backend": "x11"` trades back. Existing installs with
`x11` saved were migrated to `auto` once (`SettingsVersion`). An explicit backend
the session can't provide falls back to `auto`, because GDK would otherwise fail
to open the display and exit silently.

**The password.** Windows uses DPAPI. Linux uses AES-GCM under a key derived
from a 0600 key file, `/etc/machine-id` and the user name, so a copied
`settings.json` is useless without the key file from the same machine. The
login keyring would be stronger against disk imaging but can't be tested in CI
(no session bus), and an untested path shouldn't carry the main credential.

**The floating window** is the same `/focus` page at a small size in the same
session. On WebKitGTK, which has no app-region dragging, the host moves the
window from a gesture, so a press that starts on a button and travels moves the
window. Every key the page reads about it is optional, because the web build can
be newer than the client.

**The proxy must not buffer.** `/api/events` is an SSE stream carrying every
live update, so `LocalServer.cs` sends chunked and flushes after every read. A
buffering proxy doesn't error. It leaves the stream silently connected.

## Panel firmware

`firmware/` is about sixty lines because the server does the hard part: `.bin`
is the buffer the driver already holds. It doesn't vendor Waveshare's driver,
since a stale copy of third-party code would be worse than none. A backend test
parses `main.py` and checks its constants against the live endpoint, because CI
jobs are scoped per directory and a new top-level directory would otherwise
have no checks. Raw sockets are used instead of `urequests`, which would buffer a
second copy of the 48,000-byte frame on a board with 520 KB of RAM.

The directory is MIT while the rest is AGPL. The AGPL's distinguishing clause
(§13) applies to software people reach over a network, and a panel only makes
outbound requests. The example is meant to be copied and ported. Waveshare's
driver is GPL-3.0, so what runs on the board is a GPL-3.0 combined work either
way. MIT lets the fetch-to-buffer part be reused somewhere that driver isn't.
The server side (`backend/smylted/display/`) stays AGPL.

## Licence

**Affero, not plain GPL.** GPL copyleft triggers on distribution, and a hosted
app distributes nothing. Without §13, someone could run a modified copy as a
service and owe nobody the changes. Settings → About is how a running copy
offers its source.

**Version 3 only, not "or later".** "Or later" is a standing grant to relicense
under terms nobody here has read. The cost is that adopting a future version is
a deliberate relicence, and `AGPL-4.0-only` code can't be merged. That is
intended. `vobject` (Apache-2.0) and `recurring-ical-events`
(LGPL-3.0-or-later) are both compatible with v3, and their own "or later" is what
makes pinning safe on this side.
