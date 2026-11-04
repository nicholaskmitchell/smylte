# Design notes

Why Smylte works the way it does. The README says what it does; this file is
for anyone changing it.

## Data

**CalDAV is the source of truth.** Radicale holds every task and event. SQLite
caches them, and a resync can rebuild the cache from scratch. The exception is
the **sidecar**: app-only state that has nowhere to live on the wire, such as
manual order, pins, parking, the original due date, the day plan, habits,
displays, shares and day notes. Backups must include it (`docs/DEPLOY.md`,
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

**Moving a task to another list keeps it.** A list is a CalDAV collection, so
the move is a copy into the new list and a delete from the old one. It is the
same copy-then-delete that moves events between calendars, and the UID
survives, so other clients see the task change lists instead of one task ending
and another starting. Subtasks go with their parent, because a parent is only
looked for in its own list. A subtask moved on its own leaves its parent, which
stays where it is. The subtasks are moved first and the task itself last, so a
move that fails part-way can simply be retried. A retry recognises a copy an
earlier attempt left in the new list by what it says. It must match the
task, apart from the timestamps every write renews. A move never overwrites
what it finds there. Smylte names a task's file after its UID, so a different
task with the same UID can sit exactly where the move would write. That task,
or a copy someone edited since, is refused, and the task stays in both lists
for the owner to settle. A twin identical to the task can't be told apart from
the move's own copy, and the two become one. What Smylte kept for each is
merged, so a reminder set on the copy while it showed in both lists survives.
One failure is left unrecovered on purpose. If the source's delete landed but
its answer and the check after it were both lost, and a sync ran before the
retry, the task is in the new list while its Smylte data stays orphaned in the
old one, and is collected a week later. Recovering it would need proof that
the task in the new list is this one, and a shared UID isn't proof: moving one
task's data onto a different task is worse than losing a pin. Nothing about earlier attempts is recorded, so no
lost answer can leave a wrong record behind. Everything Smylte keeps beside
the task follows it: order, pin, parking, estimate, reminder, the remembered
deadline, its rows on the day plan, and the email thread it came from. In the
editor it is the List field, which used to appear only when creating a task.

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

**Late, or the deadline moved.** Both put a passed deadline on a new date, and
only the owner knows which happened. When the date field leaves a passed
deadline, the editor asks *Running late* or *Deadline moved*, defaulting to
late. A remembered date can be answered the same way afterwards. A moved
deadline reads "moved from …" without the warning colour or a day count, and
lateness is measured from the date it moved to. Because it was never a miss,
it doesn't hold the record the way a miss does: if the new deadline passes and
is moved again, that one is remembered instead. A miss is still never
rewritten. An update approved from email counts as the deadline moving when
the email itself named the new date, since someone wrote to say so. A date the
owner adds while approving is their own, and defaults to late. The triage strip and dragging
across the day columns don't ask, so they record a move as late.

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
- **It never opens a day.** Like displays, shares and the connector, it points
  you to Today instead.
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
- "At the time" (a lead of zero) can't use the usual window, which closes at
  the moment and would be a single instant. Its window opens at the moment and
  runs to the sweep that first passes it: the Notifier remembers its last
  sweep, so consecutive windows meet however long a sweep takes. The first
  sweep after a start allows two intervals, nothing goes out more than 15
  minutes late, and the message says "now".
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
already has a task becomes an update to it, unless it adds nothing (then it is
settled as a duplicate); a moved deadline is always an update.

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

**Home can clear the queue.** The Suggested module on Home approves or dismisses
a suggestion in one tap, with no edits. That is what approving an untouched row
in the Tasks pane sends: a task goes to the list the email suggested or the
default list, an event to the default calendar, and the filing memory is only
taught by a list you pick. Editing a title, a date or a list stays in the pane,
which the module links to, so it is a queue to clear and not a second editor.
It lists the first 20 and counts the rest.

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
leaked token in use. Settings → Displays → "Preview every display mode" previews every mode at real panel
sizes without creating tokens.

## Shares

**A link for a person, not an account.** A display is a screen you own; a share
is for somebody else to read. They have no login, no settings and nothing to
install. They open a URL and see the lists and calendars you picked, and, if you
turn it on, whether you are focusing. It is read-only and has no way to ask for
more.

**The URL is the credential**, with a separate id. The token is 32 random bytes
in the path, and it is the only thing that reaches the public call. Each share
also has an id, and every owner route, every live event and the Settings editor
use that, so the token never appears in an owner URL or event. *New link*
re-keys a share in place and keeps what it shows. The name you give a share is
your label for the person; it is never sent to them, so the page has no heading
of its own beyond "Shared with you".

**Empty means nothing**, which is the opposite of a display, where an empty
selection means everything. A display is a screen in your own home, so showing
all of it is a fair default. A share is read by someone else, so the only safe
failure is to show them nothing. That is why shares are their own table rather
than a display mode: a mode would inherit the display's empty-means-everything
rule and its habit of keeping a name that does not exist yet. A share keeps only
the ids of collections that exist, of the right kind, when you save, so a name
that comes to exist later cannot start sharing something you never picked. A new
share has no lists, no calendars and Focus off.

**Titles and times only.** The viewer gets, for each shared list, its open
tasks with title, due date or time and nesting (parked tasks are left out, at
most 200 per list). For each shared calendar it gets events with title, start
and end over the horizon (at most 500). It also gets the names and colours of
those lists and calendars. Every object is built field by field from a short
list of named values, and no response the app builds for you passes through.
Estimates and worked time are effort data, not titles and times, so they are
left out with notes, descriptions, locations, tags, priority, status, alarms,
habits, day notes, the reflection and any id, href or UID. Unshared, archived and
deleted collections do not exist as far as the viewer can tell, including their
names.

**Private items show as Busy.** An item that another app marked with a CLASS
other than PUBLIC (`PRIVATE`, `CONFIDENTIAL`, or anything else) is sent with its
time and no title, and the page draws "Busy". The check reads the whole resource
and is coarse on purpose: one non-public CLASS on a recurring event's master or
on any one override marks every occurrence, and the same holds for tasks and for
the rows of today's plan. The alternative is working out which component each
occurrence came from, which puts a second reading of the recurrence rules in the
one place where a mistake shows somebody your private appointment. An empty
value or an unknown one counts as private; only an explicit PUBLIC is shown.
Smylte has no column for this and does not write it. The marks come from other
apps.

**Bookings show the link's title.** A booking's event summary is "<link title> —
<visitor>", so a share sends the title of the booking link and never the
visitor's name. The ledger is asked by event UID alone, because moving a booked
event to another calendar does not update the ledger's calendar. A summary that
still starts with a link title and the dash, with no ledger row behind it, is
cut back to the title as well. If the link has been deleted, the event shows as
Busy.

**Presence, not surveillance.** With Focus on, the page shows one card: the
state (focusing, on a break, paused, interval over, or not focusing), the time
left, and what you are on and what comes next. A timer left paused for over 30
minutes, or finished and not continued for over 15, reads as not focusing,
because "focusing" shown to a stranger for hours is a false statement. The
current row (*now*) and up to two *next* rows come from your queue, but only
from rows of **shared task lists**. A habit, a note, a task from an unshared
list or a parked task contributes nothing except its place in the order. If the
cursor is on one of those, the viewer sees the state and the clock and no title.
*Now* is named only when the cursor row is itself open and shared, and the page
paints it rather than electing its own. Below the card, today's planned rows
from the shared lists are shown with ticks and a count, done ones included; the
lists themselves stay open-only. A share does not tell the viewer whether the day
was planned at all: an unplanned day and a day with nothing shared on it look the
same.

**It never opens a day.** A share reads today's plan the way a display does, as
a pure read. An unopened day shows no rows rather than a preview of what opening
it would derive, and nothing a viewer does writes to your plan. The one write is
the share's own *last opened* stamp.

**Last opened is one timestamp.** It is written at most once a minute, and no
address or browser is recorded. Settings shows "Open now" when it is under two
minutes old and refreshes the list every 30 seconds. "See what they see" shows
the same payload and writes nothing, since the stamp records the person and not
you. Re-keying a share clears it, because the old stamp belongs to a link that
no longer works.

**How live it is.** The page polls every 15 seconds while your focus session is
running, paused or between intervals, and every 30 when it is idle, including
when Focus is off. A running phase has
a fixed end time, so the viewer counts down on its own device and asks again just
after the phase ends instead of waiting for the next beat. Its own clock is not
trusted: the page measures how far off the server's clock is and corrects for it,
so a tablet that is an hour out still shows the right time left. A hidden tab
does not poll and asks at once when it comes back. Every response answers 304 to
a matching `If-None-Match`, and the tag leaves out the timestamp, so a quiet
share transfers almost nothing. There is no public SSE stream. It would be an
open connection per stranger on a route with no session, and polling bounds the
cost with a per-address limiter.

**Whose clock.** The viewer's. Times are drawn in the viewer's zone and 12- or
24-hour convention, and the agenda's days are the viewer's local days, as on the
booking page for anyone who is not the owner. Floating times have no zone of
their own, so the server resolves them in your home timezone before sending; the
zone name itself is never sent. The server widens its window by a day on each
side so that a viewer on the other side of the date line has events for every day
they draw.

**How far ahead** is a per-share setting: today, 1, 2 or 4 weeks. Only those four
values are accepted. The server expands recurrences on every poll, so a free
number would let a PATCH ask a public route to expand a year. Whatever the
horizon, today and tomorrow are always drawn, because "nothing today" is worth
saying; after them, only days with something on them are.

**Revocation, and what the page does.** Switching a share off, making a new link
and deleting it all take effect on the viewer's next request, because the row is
read on every request and there is no cache. An unknown, switched-off, rotated,
deleted or malformed link gets the same 404, so a revoked link teaches its holder
nothing. The page wipes what it was holding from memory and from the screen,
says "This page isn't available right now", and stops polling. Only the *Check
again* button asks again, and a switch back to the tab does not. A rate limit, a
server error or a dropped connection says nothing about the link, so those keep
what is on screen and retry with backoff.

**A password change switches every share off.** A share remembers the credential
version it was switched on under. When the password, the user name or the session
secret changes, none of them matches, and each link answers 404 until you turn it
on again in Settings, where it says why it is off. Switching on is you vouching
for it under the new credentials. Making a new link does not do that, so a link
that a password change switched off stays off. Displays are not covered: they
keep working across a password change, so check Settings → Displays as well
(`docs/DEPLOY.md`). With sign-in disabled there is no credential to change, and
shares behave as if it never does.

**Deleted and archived collections.** Deleting a collection removes it from every
share in the same transaction, so a collection recreated at that href is not
shared again without you picking it. That narrows the case to one discovery
interval; it does not close it, because a collection deleted and recreated
between two discovery runs is never seen as deleted. An archived calendar is not
shown, and a slug two live collections share is shown for neither.

**No connector tools.** Nothing in the connector reads or writes shares, so a
prompt-injected connector cannot mint a bearer URL to your account.

**Nothing leaks around it.** Every public response, the page shell included,
carries no-store, noindex, no-referrer, nosniff and `X-Frame-Options: DENY`.
Titles are drawn as inert text with its own direction. The access log keeps only
the first four characters of a share, display or booking token. A chat app that
previews links by running JavaScript can load a share, so re-key one that was
sent where previews are on.

**Home shows the state, not the address.** The Shares module on Home lists each
link's name, whether it is on (a share switched off by a sign-in change says
so), when it was last opened, and a switch to turn it on or off. The token and
the URL are never drawn, because the board may be on a screen other people can
see. Switching a share back on after a sign-in change sends `enabled: true`, so
the server stamps it again. Everything else stays in Settings → Shares. The
module re-reads on the `share_*` events (App's `sharesRev`, which still never
bumps the task and calendar `rev`) and every 30 seconds while the page is
visible, because opening a link publishes nothing.

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

One appearance choice is not the account's: in the Android client a phone can
take its accent from the wallpaper (see Android client). It is written over the
theme's inline tokens and never into a theme, so it is not synced, exported or
applied on any other device.

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

Dialogs take focus and give it back. Every dialog, sheet and popover is a layer
(`layers.ts`). A layer notes what had focus while it renders open, because React
focuses an `autoFocus` field during the commit, before any effect could look. A
dialog with nothing focused inside takes focus on its own element
(`tabIndex={-1}`, drawn with no ring), so a screen reader starts inside it. When
a layer closes and focus went with it, focus returns to what opened it. If that
has gone too (Settings handing over to Appearance), it returns to what opened
the layer before. A text field is never refocused, because that opens a phone's
keyboard, and focus the closing action put elsewhere is left there. This applies
in browsers and the desktop clients as well.

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

## Android client

**The server's origin, not a local server.** The desktop clients serve the app
from a loopback HTTP server and proxy `/api`. On a phone any app can connect to
a loopback port, so the Android client opens none. The WebView loads the app at
the server's own address, and `shouldInterceptRequest` answers requests for the
app's files from the downloaded build. `/api` is left to the WebView's network
stack, so the session cookie, same-origin API calls and the SSE stream work
exactly as in a browser, and nothing is rewritten. The split between local
files and the network is `LocalServer.HandleAsync`'s, so the web build can't
tell the hosts apart. Interception can't read request bodies, and every desktop
bridge verb is a POST with one, so `/desktop/*` answers 404 and the desktop
settings don't render. The status and navigation bars follow the page's
`theme-color` meta tag instead, which `appearance.ts` already keeps on the live
`--bg` for mobile browsers. A watcher injected after each load reports it
through
the page bridge (below), whose colour method takes only a colour. The document
served from disk
gets a port of `csp.py`'s policy (`Csp.kt`), which `test_csp.py` checks as it
checks the desktop's copy.

**An outdated WebView says so.** The page needs Chromium 111, and below it the
page loads broken with no message. Its stylesheet writes the palette in
`oklch()` and the tints in `color-mix()`, both 111, and a WebView without them
drops every colour that uses them: a done task's check and today's date vanish.
Below 108 the layout collapses as well (`dvh`), and below 85 the script doesn't
parse and the page is blank. Android 11 images without Google Play ship WebView
83.

So before start-up the client reads the engine's version from the `Chrome/`
token of its default user agent and, below 111, shows the failure screen,
naming the WebView and asking for an update, without downloading anything. It
reads the user agent rather than the provider package's `versionName`, because
a provider can number its package its own way: Huawei's WebView 14.0.0.331 is
Chromium 99. From Chromium 156 the token is itself the package's `versionName`,
so a number below 70, older than any WebView Android 11 can run, is taken for
such a numbering and let through, as is a version that can't be read. A page
that loads degraded is better than a phone turned away for good. For the same
reason the failure screen still checks the release and offers a newer APK,
which may accept the WebView (a lower floor, or a better reading of its
version); it never offers a staged web build, whose Reload would open the page
this WebView can't run.

The frontend's `webview-floor.test.ts` fails when the page uses a feature newer
than the floor, from a list of likely ones with their WebView versions, and
when nothing on that list needs the floor any more. An Android test fails if the
frontend sets a build target of its own or moves off Vite 7, either of which can
let newer script syntax through.

**An app, not a page in a browser.** A WebView's defaults give the page away in
a few places, and the client changes the ones that are WebView settings.
- Its edge effect is off. WebView draws the stretch (a glow on Android 11) over
  the whole view, header and tab bar included, while what actually scrolls is a
  list inside a fixed shell.
- Page zoom stays off, as it already was by default, and is stated so nobody
  turns it on. The shell is a fixed `100dvh` box that clips, so a zoom could
  only pan a cropped layout, and the system's magnification works over any app.
- Text size is set by the client. WebView takes the system font scale only once,
  when it is created, while this activity handles font-size changes itself
  instead of being recreated. So the client sets the text zoom at creation and
  on every configuration change.
  - The zoom is the ratio of the body size converted as sp to the same size
    converted as dp, not `fontScale`. Android 14 scales text non-linearly, and
    the converted size follows that curve.
  - Its bounds (50% to 300%) lie outside anything Android offers, so they cap
    nothing. A layout that breaks at the largest sizes is fixed in the page.

The rest belongs to the SPA and applies in every client: a long press selects
content, including a pressable row's title, but never a control's label; and a
refusal is shown in the app's toast rather than in `window.alert`.

**One bridge, and every method optional.** The page reaches the host through one
JavaScript interface, `window.SmylteAndroid` (`PageBridge`), and the host
answers through one DOM event, `smylte-android`. The web build updates on every
start and the APK rarely, so a page routinely runs in an older client and an old
page in a newer one. The page checks each method with `typeof` before calling
it, as `desktop.ts` checks its routes, and the host acts on a capability only
when the page announces it in `hello`. `hello` returns what the page may want to
know about the device, as JSON. The page reads each field on its own, so adding
one breaks nothing, and `v` changes only when a field changes meaning. Any
script on the page can call the bridge, so every method is harmless or needs the
user, and the host validates every argument (`HostProtocol`, covered by the JVM
tests). Only primitives and strings cross, and the host never writes CSS or
opens anything the page names. Theme export calls `saveFile`, which opens
Android's own save dialog. A blob download can't work, because the page revokes
the blob URL as soon as it has clicked it, and native code can't fetch `blob:`
URLs. The dialog is the user's consent, so it isn't tied to a touch, which a
TalkBack or keyboard activation doesn't produce. Instead only one save is
pending at a time, the window must be in front with the app's own page loaded,
and a new dialog waits two seconds after the last one closed, so a script can't
hold the user in a loop of them. A save whose window was recreated while the
dialog was open reports in a native toast, because the page that asked is gone.

**The clock starts from the phone's.** `hello` reports the phone's 12/24-hour
setting (`DateFormat.is24HourFormat`, which follows the locale until the user
picks one), and the env event repeats it when it changes. While the account has
no `time_format`, the page shows the phone's setting from the first frame, and
the first settings read that finds none saves it to the account. The server
formats reminders, the digest and the wall displays, and falls back to 12-hour
for an account with no clock, so a default kept only in the page would show
24-hour in the app and 12-hour in everything the server writes. A choice the
account holds is never replaced, and neither is a toggle made while the read was
in flight. Once the account has a clock, the phone's setting no longer applies.
The settings API has no "only if absent" write, so a choice made on another
device during that one round trip would be overwritten; that can happen once per
account.

**An accent from the wallpaper, on this phone only.**
- On Android 12 and later `hello` also reports the phone's accent palette. That
  is Material You's `system_accent1` colours, 13 tones from 0 to 1000, each read
  by its own named resource id and sent as `#rrggbb`.
- Appearance shows a switch only when the palette is there. The switch is
  remembered in the WebView's own storage (`smylte-device-accent`) and never in
  the account, so the owner's other devices, the theme and its exports keep the
  theme's accent.
- When it is on, the page writes `--accent` inline after the theme's tokens, so
  it beats a custom theme's accent on this phone. It is written again on every
  theme or mode change, because `applyTokens` clears every token first. main.tsx
  writes it once before the first render.
- The shade is Material's own accent tone for each mode, 600 on light and 200 on
  dark, stepping darker or lighter until one clears 3:1 against all three
  backgrounds (`--bg`, `--bg-elev`, `--paper`). That is the floor the shipped
  accents are held to; if no tone clears it, the theme's accent stays.
- A custom background may be any CSS colour. One the contrast code cannot read,
  a `color-mix()` for instance, is painted on a canvas and read back, as the
  bar-colour watcher does. The pick is checked again once painted, since a
  background may itself be defined from the accent.
- A new palette arrives with a rebuilt window's `hello`, or as the env event
  when the window is not rebuilt (the manifest's `configChanges` lists
  `assetsPaths`).
- Any script on the page can read the palette, as it can the clock. It says
  something about the wallpaper and nothing else, and goes only to the user's
  own server's page.

**Back closes what is open, and asks before it discards.** Every dialog, sheet
and popover registers as a layer (`layers.ts`), in the order it opened, and the
page reports how many are open through `layers(n)`, which the host clamps to 16
and forgets with each new document. The host sends `back` only while that count
is above zero, and the page closes the top layer with the same handler it gives
Escape, so a scope prompt still closes before its editor and Settings still
steps back one level. With no layer open, Back walks the page's history (the
focus view has an entry of its own) and then leaves. On Android 13 and later
that is an `OnBackInvokedCallback` held only while there is a layer or history
to walk, so the system's back-to-home animation still plays when there is not;
on 11 and 12 it is `onBackPressed`. It is not a synthetic Escape: `useEscape`
binds the window, so one Escape would close every open layer at once, and it
would never reach an inline field, which stops the key at the field. An edge
swipe is far more often an accident than Escape, and the usual sequence is one
Back that closes the keyboard and a second that would close the form. So a layer
that holds unsaved input gets an in-app "Discard changes?" first, whose own Back
keeps editing, so a second Back can never be the one that discards. Back never
saves. It leaves the focused field first, as a tap elsewhere would, so the
settings fields, which are not layers and commit on blur, keep what was typed,
which is what Back does in a settings section. Text that goes only by Enter or a
button (a share's or a display's name in its add field, a mail password not yet
saved) is counted as unsaved input in Settings (`useUnsent`), so the Back that
would close Settings asks first; stepping back to the phone's index keeps the
section mounted, so that step does not. The two rituals keep their notes
the same way, because they commit on blur and on close, as the ✕ and Escape
already do, so there is nothing to discard. While a layer's write is in flight
(a booking link being saved, a display, share or habit being added) Back does
nothing: "Discard" could not recall it, and a write that fails puts its input
back for a retry, which needs the layer still open; after a failure Back asks
as before. The question goes by itself when the input it asked about does (a
reload replaced it), so its "Discard" never runs a step it did not offer. Tab
stays on its two answers, and for a moment after it closes a tap lands
nowhere: on a phone "Keep editing" sits over the editor's own Save, and the
second tap of a double tap saved the form. A count left stale by a document
change costs one Back press: the host drops a report that belongs to a replaced
document, and a Back that finds no layer makes the page report zero. Browsers
and the desktop clients never hear `back`, so Escape is exactly what it was
there.

**A tap can be felt.** The page can ask the host for four haptics, `confirm`,
`reject`, `toggleOn` and `toggleOff`, and the host ignores any other name. One
capture-phase `click` listener on the document, installed only when the host has
`haptic`, decides which one a tap plays, so no control carries a call of its own.
A task's check going on is `confirm`. Anything that tells a screen reader it is
a toggle (`aria-pressed`, `aria-checked` or a checkbox) plays the state it goes
to, read before the app's own handler changes it. A button that cycles values,
such as the clock row, is not a toggle to a screen reader and plays nothing, and
neither does any other button; `data-haptic` names one outright, which is how the
focus view's Done button, a completion that is no toggle, plays `confirm`.
`reject` comes with the app's error toast, which every failed write and every
refusal shows, so one call covers task writes, entry ticks, event writes and
settings alike. A load that a tap started and that fails within the window shows
the same toast and so plays `reject` too. The mapping is `CONFIRM` and `REJECT`
for those two, and `TOGGLE_ON` and `TOGGLE_OFF` on Android 14 and later; on 11 to
13, which lack them, both toggles are `CLOCK_TICK`, because a constant the
platform does not know plays nothing. The host makes the one-argument
`performHapticFeedback` call, so the phone's touch feedback setting decides, and
it needs no VIBRATE permission. Any script on the page can ask, so a haptic plays
only when the window is in front, the page is the app's own, and a finger is down
or lifted at most 1.5 s ago, and at most twice in one touch: a tap's own haptic
and the reject of the write it started. There is no minimum gap between the two,
because a write refused at once on a fast network would lose its reject to one.
TalkBack, Switch Access and a keyboard produce no touch, so they get none, and
TalkBack gives its own. Drags play nothing yet, because whether HTML5 drag works
on touch in WebView is unverified.

**The splash screen lasts until the app has signed in.** On Android 12 and later
the system shows a splash screen, the icon on the window's background, until the
app's window first draws. The window used to draw at once, so a cold start
showed that splash, then the client's own "Starting…", then an empty page until
the app painted. Now, on a fresh launch from the launcher, the window holds its
first draw with an `OnPreDrawListener` on the content view (the technique
AndroidX's splash library uses), and the listener reads one flag, because it
runs before every frame while it holds. The page announces `ready` in `hello`
and calls `ready()` once its first view is real. App does so the first time its
sign-in check answers (signed in, signed out or offline), and the routes without
a sign-in do so as soon as they render. The call comes from an effect, never a
frame callback, because frames may not come while the window does not draw. A
page from before `ready` ends the hold when it has loaded, at `onPageFinished`,
by which time its scripts, and so its `hello`, have run. `onPageCommitVisible`
would not do, because it needs a drawn window and can come before `hello`. The
failure screen ends the hold at once, and nothing holds it past about 3 seconds
from the tap. On a cold launch (the process's first window) the cap counts from
the process's start, when the platform splash went up (on Android 13 and later,
from when that start was asked for), so the time to reach the window does not
come on top, and a start that took the whole cap to get there holds nothing. A
first window that comes 10 seconds or more after the process started is taken
for a warm one, since the process most likely started for something else before
the tap; a cold start that slow is held for up to 3 seconds more. Start-up is
serial (a release check, the session check, the page, the app's own `/api/me`),
so on a slow network "Starting…" then shows how far it got. A window that has
never drawn also has no input focus, so a key event waiting 5 seconds for one is
an ANR. A window rebuilt from saved state, after a renderer crash or a wallpaper
change, has no splash in front of it, and the window the settings screen opens
may have none, so neither holds: holding their draw would show a blank window.
Any script can call `ready()`; at worst the splash ends early.

**An optional app lock.**

The session cookie lasts seven days, so anyone holding the unlocked phone has
the account. Server settings has an opt-in lock, kept in the app's own
preferences rather than the account, because it concerns this phone.

**The prompt.**
- It asks through the platform's `BiometricPrompt` (there is no AndroidX here)
  for a Class 3 biometric or the screen lock
  (`BIOMETRIC_STRONG | DEVICE_CREDENTIAL`).
- Allowing the screen lock is what lets every phone with one unlock. It also
  rules out a cancel button, which the platform refuses alongside it.
- The lock is offered only while `KeyguardManager.isDeviceSecure`, and a phone
  without a screen lock is never locked: nothing could unlock it, and anyone
  holding it can open the app anyway.

**When it locks.**
- It locks when the process starts, and when the app comes back after
  five minutes or more with none of its windows visible.
- The time is `SystemClock.elapsedRealtime`, which counts deep sleep, recorded
  when the last window stops and compared when one starts. So a window rebuilt
  by a configuration change or a renderer crash, or a quick trip to the save
  dialog or another app, never locks.
- The state is one object for the process (`AppLock`, tested on the JVM). The
  settings window, which the launcher's shortcut opens on its own, therefore
  locks with the app.
- A visit counts only once one of its windows has drawn a frame (an
  `OnDrawListener` on the decor view, taken off again with the window, which a
  rebuilt one can keep). Android can take a window from `onStart`
  to `onStop` unseen: `recreate()` of a stopped activity, which the host does
  when the renderer dies in the background (after which it sends that WebView no
  more scripts), runs the new instance through start,
  resume, pause and stop in one go. Such a pass leaves the time away as it was,
  and the prompt it would have opened by itself is dropped, since that waits for
  a window still started. A stop with no window started changes nothing.

**While locked.**
- Each window hides everything but a lock view. The container is `INVISIBLE`
  (the page keeps its size) and `NO_HIDE_DESCENDANTS`, and it drops the
  accessibility events a page sends up through it. The WebView itself is
  `INVISIBLE` too, so WebView treats the page as hidden.
- The hold on the platform splash ends at once, and the app goes on starting
  behind the lock.
- Only the prompt's success unlocks.
- Server settings cancels autofill's session as it locks, so fields that vanish
  behind the lock don't bring up its save dialog over it; they are the
  platform's own fields, which start a new session when next touched. The app's
  window does not: WebView keeps its own autofill state, which a cancel from
  outside would put out of step, and hiding a WebView brings up no save.
- Back, in either window, moves the task to the back rather than reaching the
  page or finishing the window, which would drop whatever was open in it.
  Closing the settings would also show the window under them, whose last picture
  may be from before the lock.
- The page cannot open a save dialog over the lock.
- A picker's answer that comes back to a locked window waits for the unlock. So
  does one that comes before the window has started: Android 11 delivers
  activity results before `onStart`, which is where the lock takes hold again
  (`HostProtocol.holdsResult`). A held save goes into the saved state with its
  payload.
- A dialog is a window of its own, outside the lock view and its `FLAG_SECURE`.
  WebView's dialogs for `alert`, `confirm` and `prompt`, which the app never
  uses, are always answered as dismissed, because one raised while the app is
  away, or left open, would stand over the lock. The `beforeunload` question,
  and a download handed to the browser, are refused while the window is stopped
  or locked (`HostProtocol.pageOutOfSight`). With the lock on, a date or time
  picker left open is closed as the window stops, and again as it locks, by
  blurring its field (`HostProtocol.CLOSE_PICKER_SCRIPT`); a select's list
  closes by itself when the WebView is hidden.

**Recents.** The preview is taken when a window leaves, so it stays blank for as
long as the lock is on: `setRecentsScreenshotEnabled(false)` on Android 13 and
later, and `FLAG_SECURE` on 11 and 12, the only way there, which also blocks
screenshots (README.md has the trade-off). While a window is locked it is
`FLAG_SECURE` on every version, because hiding the views does not keep the
digital assistant's screen-text request from reading them, and a secure window
is the one thing it skips.

**No page involvement.** The page is never told about the lock, and there is no
bridge method, so the lock works the same with any web build. The one thing the
window does in the page is blur a date or time field as it locks.

**Stage, then swap.** Android keeps processes alive for days, so the client also
checks for updates when it returns to the foreground after six hours or more. A
build must never change under a running page, so downloading and swapping are
separate steps. A new build is unpacked into `web.next` and swapped in only
before a load: at start-up, or when the user picks **Reload**. Each build
records its release asset id and `updated_at` inside its own directory, so the
record moves with the build in the same rename. GitHub's anonymous API limit
is 60 requests an hour per address, and a phone on a carrier's shared address
shares it with strangers. So a start within ten minutes of the last check
reuses that answer, and the in-app check waits six hours. (A 304 is free only
for a request with a token.)

**The APK update.** As on the desktop, the client compares the published
digest with the installed APK, which Android keeps byte for byte, and CI
republishes only when the client changed. The key is `android/` minus the
README, tests and helper files. It is an exclusion list on purpose: forgetting
to exclude a file costs one needless update, while forgetting to include one
would ship a change nobody is told about. Android needs a version code that
rises, so CI uses minutes since 2026-01-01, which nobody has to bump. The notes
record the published APK's key and version code, a run that publishes no APK
writes them back unchanged, and a lower code is never published, because only a
re-run of an old run can produce one and every phone would refuse it. The
download is checked against GitHub's digest, then for package name, signer and
version, and handed to the system installer with `ACTION_VIEW`. The session
installer can't restart an app that updates itself, while the system installer
ends with **Open**.

**The signing key stays out of the build.** Android accepts an update only when
it is signed with the installed app's key, so the key is permanent and can't be
revoked. Gradle runs the Android Gradle Plugin and whatever it resolves from
Maven, so the build job produces an unsigned APK and a separate job signs it
using only the SDK's tools. The key lives in a GitHub environment that only
`main` may use, because a repository secret is readable from any pushed branch,
and only `main` signs or publishes. Keeping the key out of the build keeps it
secret, but the key still vouches for whatever the build produced. So Gradle
checks every artifact against `verification-metadata.xml`. A job that holds
nothing reads the APK before anything signs it, and refuses a wrong package, a
debuggable build, or a version code ahead of the clock. That last would make
every later update a downgrade that phones refuse. It reads the compiled
manifest attribute by attribute, because `aapt2 dump badging` prints the
version name unescaped, so a planted quote could fake a second, smaller version
code. Its parsers are native code reading an untrusted file, so they don't run
where the key is: the signing job signs only the file whose hash the inspection
reported. Only the newest commit on `main` publishes, so re-running an old run
can't roll clients back. Without the secrets nothing is signed, and the web
build and the desktop binaries keep publishing.

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
