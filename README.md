# Smylte

A self-hosted **tasks + calendar** web app (TickTick-style) backed by the
existing Radicale CalDAV server, live at `radicale.nicholaskmitchell.com`
(raw CalDAV for devices lives under `/dav`; clients that take only a hostname —
Apple's — find it via RFC 6764 discovery at the root). It is one CalDAV client among
several — Tasks.org (DAVx⁵), jtx Board, and Thunderbird share the same
collections and have equal rights. **Radicale is the source of truth; SQLite
is a disposable cache** (except the app-only sidecar — pins, manual order, the
day plan, habits, the displays you have paired and what you wrote about each
day: things that have nowhere to live on the wire, so a resync cannot rebuild
them and a backup must include them. See
`docs/phase0-findings.md`, and `docs/DEPLOY.md` for which tables those are).

The stack is a FastAPI backend (`tasksd`) that owns the CalDAV/sync/write path
and serves a React + Vite single-page app.

## Features

**Tasks.** Lists (create, rename, recolor, reorder, delete) and tasks with
subtasks, due dates (all-day or timed), priority, tags, and notes. List /
3-Day / Week layouts, quick-add, and drag-to-reschedule across day columns.
Every list is merged into one pane, dotted by list color; the sidebar works
just like the calendar's — each list is a row you click anywhere to show or hide
it individually, no separate "all" toggle — plus collapsible **groups** to
organize lists without widening the sidebar. Tags on every task, shown as chips on the row and edited in the task editor. Full-text search ships on the API (`GET /api/search`) and on the MCP connector (`smylte_search_tasks`) — there is no search field in the web UI yet.

Rows sort by one rule everywhere (`order.ts`): manual position, then due date
(undated last), priority, title, and finally uid — which is what makes it a
*total* order, so the array's own order stops mattering and an optimistically
added task paints where it belongs instead of jumping when the server catches
up. In the list view you can **drag rows into a manual order**; it is global
rather than per-list, because the pane is always the merged view. That order
lives in the app-only sidecar, so it is Smylte's own and does not reach the
other CalDAV clients.

**Subtasks drag too**, among their own siblings — a subtask lands between the
steps of the thing it is a step of, never on a top-level row, because moving a
subtask out from under its parent would be re-parenting rather than ordering.
Subtasks are usually a sequence ("prep, cook, serve") and a sequence is not
something the sort keys can express: undated and unprioritised, they come out in
title order, which is an order nobody chose. One drag writes the whole sequence,
the same one the top-level rows use.

**A task can also be parked**, which is the fourth answer and the only neutral
one. iCalendar gives a task three: needs action, done, and cancelled — and
cancelled reads as a verdict, so it never gets used, and nothing ever leaves the
list. Parking is "not now": the task leaves the lists, the day's automatic rows,
the open counts and the digest, and it comes back exactly as it was whenever you
want it. It is not done and is never reported as done, on any surface.

It lives in the app-only sidecar rather than on the wire, and that is forced
rather than preferred. There is no neutral fourth status in the spec, and an
invented one — or an `X-` property — would be written verbatim onto collections
Tasks.org, jtx Board and Thunderbird share, where all three would render it as
nothing. So the honest cost is stated rather than hidden: **a task parked here
still sits in those clients' lists.** Parking is a statement about which of your
own views something appears in, which is what the sidecar is for — the same call
the per-item reminder makes, for the same reason.

Nothing clears it by itself. Completing a parked task, or reopening one, leaves
it parked, because completion can arrive from a phone through the sync path and
a flag that cleared on Smylte's own write but not on a foreign one would leave
two tasks in the same state disagreeing about it. Bringing something back is an
act, exactly as setting it aside was.

**Ticking the last step finishes the thing it is a step of.** A parent with
every step done is finished, and leaving it open is how a list fills with rows
nobody can act on — no work in them, just something to read past. The test is
"nothing left", not "everything done": a step marked won't-do is not happening,
so it leaves nothing to do either, while a *parked* step does not close its
parent, because parked work is still coming back. It walks up, so finishing the
last box can close a checklist and the thing that checklist was a step of.

It fires only on a write made here — another client ticking the last box changes
nothing, since a sync engine that wrote back would turn every incoming change
into an outgoing one, a full resync included. And it is the one preference in
this app that writes to the calendar server on your behalf: the close is a real
completion, in Tasks.org and Thunderbird within a sync. So it is a switch in
Settings → Tasks, on by default, rather than a rule.

**Calendar.** Month grid across multiple calendars, each with a visibility
toggle and non-destructive **archive** (hide without deleting; restore from
Settings → Calendar). Events support all-day and timed spans, drag to move or
resize, and a mobile day-agenda. **VEVENT recurrence is implemented** — author
repeats and edit/delete a single occurrence, this-and-following, or the whole
series (`docs/recurrence-findings.md`). **Task (VTODO) recurrence stays gated**
pending real-device captures.

A **Tasks** group in the same sidebar puts task lists on the grid: pick which
ones appear, and whether completed tasks stay visible. Nothing shows until a
list is opted in — unlike the calendar toggles, this one is an allowlist, since
tasks are an overlay on a view that never had them. A task draws as its own
chip (a checkbox and its list's color, not an event's tinted block), and
clicking it opens the same editor the Tasks tab uses.

**Scheduling.** Calendly-style booking links: weekly availability, buffers,
minimum notice, and a horizon, with a public booking page at `/book/{token}`
that writes a real event onto the target calendar.

What blocks a slot is the owner's to decide, and iCalendar already has the field
for it: every event has a **Show as** of Busy or Free (`TRANSP` — what Apple
Calendar and Google Calendar call Busy/Free and Thunderbird "Show Time As"), and
an event marked Free is left out of the busy set behind the booking page, out of
the redacted busy shown on it, and out of `smylte_find_free_time`. It reads what
the other clients on these collections write, so a hold someone marked Free on
their phone already means it here. Absent is Busy — RFC 5545's own default — and
so is anything unrecognised, because the only direction a page that hands
availability to anonymous visitors may be wrong in is over-blocking.

**Home.** The landing tab: a 12-column canvas of modules — Today, Overdue,
Upcoming, mini calendar, recently completed, booking links, upcoming bookings,
quick add — that you drag, resize and add/remove in **Arrange** mode. The layout
is account-synced. Arranging is desktop-only for now; phones render the same
modules stacked in the saved order. The mini calendar dots each day in its
calendars' colors, and a day opens a read-only list of its events.

**Today.** The one surface that holds state of its own. Every other task view
renders a *query* — "what is due today", recomputed on every paint, so the list
moves under you all day. This one renders a *snapshot*: the first time you open
a day the backend freezes what it held — what is due that day, and what you
left unfinished on your last planned day — and from then on the day is
something you arrange rather than something that arranges itself. A task list
grows without bound and a day does not, and the commitment step is the part
worth keeping.

**What is already late is offered, not placed.** A deadline you set for today is
a commitment you made, and the day is entitled to hold you to it. A deadline you
have already missed is a decision you have *not* made yet, and putting it back on
every morning makes that decision for you — badly, by deferring it another day at
the cost of a row you read and skip. So an overdue task appears in the strip
underneath the day, alongside what is due tomorrow and what has sat untouched for
three weeks, and moving it onto the day is an act you perform. Nothing is hidden:
it is still on its list, still marked overdue everywhere overdue is shown, and
still one press away.

**And past a few days it stops being offered at all, and is asked about.** Three
days by default, in Settings → Tasks, and 0 turns it off. A task that late has
been read and skipped every morning it sat there, and each of those readings cost
more than deciding would have — so the strip gives it a heading of its own and
two answers instead of an add button: **a new date**, or **park it**. Adding it
to the day is deliberately not among them, because it is the answer that has
already failed: putting the task on today leaves its deadline where it is, so
tomorrow it is late again and one day staler. Only a new date ends that, and it
ends it everywhere rather than in this one strip.

It never hides anything, and this is worth saying plainly: the Tasks tab shows
every task it always did, the Home Overdue module still lists all of them — it
just says how many are waiting on a decision — and nothing about the deadline
changes until you change it. "Stops appearing" means stops being offered as
ordinary work, not stops existing. A list you cannot trust to show your tasks is
worse than a long one.

A day holds three kinds of row, and the tab says which is which — a filled
square is a **task** (a real VTODO on a list, so it reaches Tasks.org,
Thunderbird and your phone), a hollow one is a **note** (text that lives only
in that day and never leaves Smylte), and `↻` is a **habit**. The add box takes
a line of prose — "invoice friday", "gym at 7" — and states underneath exactly
what Enter will create and where it will end up, with a one-press switch
between the two and a list picker when there is a choice to make. Drag rows
into the order you will actually work them.

A **habit** is a rule that puts a line on your day, on the weekdays you choose.
It is not a second system: each occurrence is an ordinary row in the day plan,
so it ticks and drops like anything else. No VTODO is written, no RRULE, and
nothing about it reaches the CalDAV collections the other clients share. Its
weekly count is over the occurrences that *exist*, not over scheduled weekdays,
so days you never opened the app are not counted against you — and it is never
coloured as a failure.

**Planning your day** is a three-step ritual rather than a running total: how
long today is, what goes on it, and how long each thing takes. Say the length
either way — "until 6pm" or "5h" — and Settings holds a default per weekday for
the days you do not want to think about it. From then on the day says how full
it is, and when the plan runs past what you said you would work it says so in
words, *before* the day starts. An account that has never stated a capacity is
told nothing at all, because inventing an eight-hour day for someone is the one
thing this must not do.

**It never blocks: it records a decision rather than enforcing one** — and both
halves of that sentence are now true. Committing an overfull day is still one
press, but never an unlabelled one: the button reads *Start it anyway*, with
*Trim something* beside it going back to the step where a day gets shorter.
Naming the act is not the same as refusing it, and it is the difference between
a warning read after the decision and one read as part of it. The add box says
the same thing a moment earlier — if the day is already over, the line under
what you are typing says by how much — and a task in the strip that remembers
how long it takes says what adding it would cost, on the button that would add
it. Neither guesses: a line being typed has no estimate, so nothing is
projected from it.

And the day remembers. How far over it was at the moment you committed is
recorded on the day and read back once in the look-back, in words. No colour, no
comparison, nothing scored — a day knowingly started over is a fact about it,
not a mark against it. Recording it is what makes "records a decision" mean
something rather than merely say something.

**Shutting it down** is the matching three steps at the other end: what
happened, what follows you, and a line about how it went. Each unfinished row
gets three honest answers — tomorrow, a day you name, or off the plan — and
leaving one alone is the fourth, which the automatic carry still answers.
Moving work is not the same as dropping it: the day that planned it still shows
it planned it, and the look-back says *where it went* rather than filing it
under abandoned. Nothing here scores the day. There is no percentage, no streak
and no colour on the numbers.

**Review** shows how a day went: split by where each row came from (chosen,
carried over, derived, habits), what you moved to another day, what you
dropped, and what you finished that day without ever planning it — opening with
whatever you wrote about it at shutdown. It works on today while today is still
running, and the `‹` `›` picker steps back a fortnight. **A past day is a
finished record** — read-only end to end, because a log you can fill in
afterwards is a scorecard. Reading a day never creates one: only today can be
opened, which is what keeps the record honest about what was actually intended.

**What you finished this week** is one number, and until now nothing anywhere
said it. Every count in the app describes a day, and a day is exactly the unit
that makes a week of real work look like nothing much. It sits in the Today
header beside the day's own count, and as a Home module with the last few weeks
under it so the figure has a shape — 23 means nothing on its own. The connector
answers it too, as `smylte_review_week`.

It counts **tasks**, by the `COMPLETED` stamp on the wire, so a task ticked in
Tasks.org counts exactly as one ticked here and the number answers for weeks
before any of this existed. Not notes, and **not habits**: habits have their own
weekly count and this app never colours one as a failure, so folding them in
would make a productivity figure that can rise on a day nothing was finished.
There is no target, nothing to compare it against, and no colour on it. It is a
number, said once.

**Working the day.** Today's header has a *Start working* button, and it opens
`/focus`: the display's now + next face brought inside the app and given a
clock. One thing, in the largest type the screen holds — the first open row of
the plan — the one after it in small, a count of what is behind that, and a
pomodoro interval the row rides: 25 minutes on, 5 off, a longer rest every
fourth, all of it in Settings → Focus. A row either **stops at its estimate**,
in which case the surface sets it aside the moment its worked time reaches the
figure and moves on, mid-interval if need be — or **runs until done**, in
which case it stays until you tick it or say *not now*. The choice is per row,
with a default in Settings, and the default is *until done*: the app never
moves you off a thing you did not ask to be moved off. When the queue is dry
it says so, counts what was set aside, and offers another round over those.
Escape, or the back gesture, is the way out; the session keeps running.

Three things hold it up, and each is a rule rather than a feature. **The
server keeps anchors, not counters.** It never ticks; it stores when the
current run of a phase began and how much was banked before it, and every
transition settles first, crediting the time since the anchor to the row —
*clamped to what the phase has left*. That is why two windows show the same
second, why a refresh loses nothing, and why closing the laptop mid-interval
and opening it tomorrow credits the rest of that one interval and not the
night. **The server names the row.** Ticking it anywhere — in Today, on a
phone, in Thunderbird — moves the cursor, and the surface follows. **A clock
that ran out while nobody was there waits.** Rolling straight into the next
phase is a setting, and it means a live screen rolling on; a session found
past its end after lunch says so and asks, whatever the setting says.

It refuses two things on purpose. It never opens a day — Today is the only
opener, exactly as the dashboard and the connector are held to — so a cold
load of `/focus` on an unplanned day points you at Today rather than planning
one for you. And it records one number and no others: each row's *worked*
time, which the look-back shows beside the estimate in the same unit and never
as a ratio, a streak or a colour. Nothing here scores the day either. A chime,
made on the device rather than shipped, and a browser notification, asked for
only from a click, are each a switch in Settings; the notification is silent
because the chime is the sound. The connector reads the same figure as
`worked_minutes` beside `planned_minutes`, the one measured number next to two
guesses.

**Notifications.** Optional, off until you turn them on, and Telegram-only for
now. Four things earn a message, and the list is short on purpose: Smylte
already holds everything you will come looking for, so a notification has to be
something you *cannot* recover by opening the app later. A **daily digest** at
an hour you pick — today's events, what is due, how much is overdue — which
exists to replace opening the app rather than to advertise it. A nudge **before
a meeting starts**, the one thing a morning digest structurally cannot cover. A
note when **someone books you** through a scheduling link, the only information
in the app that arrives from outside while you are not looking. And a warning
when **sync has stopped working**, the one state where the app is actively
lying: everything on screen looks normal and the data is simply frozen.

The first two buzz; a booking and a sync failure always arrive **silent** — they
land in the chat and wait, because nothing can be done about either at 3am.
That is fixed in code rather than configured, which is why there are no quiet
hours to set up. Past eight buzzing messages in a day the rest are downgraded to
silent rather than dropped, so a pathological day costs you the interruption but
never the information.

**And a reminder you set yourself.** Any task or event takes a "Remind me"
lead — *20 minutes before*, *a day before* — and that one is the exception to
everything below: there is no blanket "task due soon" rule, on purpose, but a
lead set on one item is you asking rather than the app guessing, and an explicit
request outranks any bar the app would otherwise apply. It is stored app-side
rather than as a VALARM, deliberately: Tasks.org, Thunderbird and Apple Calendar
share these collections and would each fire their own alarm off a VALARM, buying
interoperability by notifying you three times. It reaches the MCP connector too,
so Claude can set one when you ask it to.

Setup lives in Settings → Notifications: the bot token, the chat, which rules
are on, and a **Send a test message** button — because every way of getting a
bot token and a chat id wrong fails identically and silently, and without that
button the only feedback loop is waiting for tomorrow's digest not to arrive.
The token is write-only: the app accepts it and never shows it again, since the
settings the page loads would otherwise carry a working bot into the browser.

**And eight more, off.** Everything usually built and not defaulted on here —
before every task is due, what is overdue, today isn't planned, the plan runs
long, today wasn't shut down, habits left, a broken booking link, sync recovered
— is in Settings, switched off, each carrying the reason it is off. Those
reasons are real: a deadline warning is noise or stress, "overdue" is true every
minute until you act, a plan-your-day nudge is the app asking for attention on
its own behalf, and the habits one sits awkwardly with the app's own position
that a habit is never coloured as a failure. That is why none of them greets a
new account.

It is also not a verdict. You know your own days better than the app does, and a
default is a starting position. So the argument is written next to the switch
rather than used to hide it, and turning one on is an informed choice instead of
a blind one. The switches that stay off are the app's opinion; the switches
existing at all is the app not mistaking an opinion for a rule.

Two things hold whatever you turn on. Nothing that buzzes is timed by anything
but you — an hour you set, or a moment already in your calendar — which is why
there are still no quiet hours to configure. And a sweep that would produce
three or more messages sends one instead, so switching on the whole morning tier
costs you one interruption at 07:30, not four.

`backend/tasksd/notify/rules.py` is the whole policy, including the admission
test any fifth rule has to pass. Setup — and the systemd egress rule it needs,
which is the easy step to miss — is in `docs/DEPLOY.md`.

**Displays.** A display is a screen with nothing to tap — the calendar in the
hallway, today's habits in the kitchen, the thing you are on at your desk. It
shows one of three things and accepts no input, which is the specification
rather than a limitation: there is no session, no control and nothing focusable
anywhere on the page, and the only call its URL reaches is one read.

**The month**, drawn the way a paper wall calendar is drawn — six fixed weeks,
Sunday-first like the app's own grid, every day placed relative to the days
around it. Not an agenda: an agenda is a thing you consult, and a wall calendar
is a thing you glance at. Or **habits + today**, which is the other thing that
earns a wall: a list short enough to read from the doorway that gets *shorter as
the day goes*, because a completed habit leaves the screen. That is on by
default and off in a switch, and the count in the corner is taken before the
hiding — with the list emptying as the day goes, "4 / 5" is the only thing left
that remembers there was anything on it.

Or **now + next**, which is the same day asked a different question: not what is
on it, but what to do about it. One thing, in the largest type the panel can
hold — the first row of today's plan that is not done — the one after it in
small, and a count of everything behind that. It **cycles as things get
finished**, and nothing cycles it: a display writes nothing and takes no input,
so ticking a task off on a phone, in the app, or in any other CalDAV client
moves the cursor and the panel finds it moved on its next poll. The plan's order
is the queue, so reordering today in the Today tab reorders the wall. The honest
caveat is on the settings screen rather than buried here — it moves on the
panel's *next refresh*, which on e-ink is never sooner than three minutes.

There is still deliberately no plain "tasks" mode, and the argument against one
has not weakened: every task view in the app is a query over a list that grows
without bound, and a screen with no scroll would show the first eight of forty
while implying that was all of them. Now + next is not that list with a smaller
cap. A capped list is a truncation the reader cannot see; two rows and a "+6" is
the whole day, said in the only shape a screen with no scroll can say it in.

**A display never opens a day.** On a day nobody has opened it shows a clearly
labelled preview of what opening it would derive, and writes nothing — the same
rule the MCP connector is held to, and for the same reason. The plan is worth
keeping only while it records what was actually intended, and a panel in a
hallway intends nothing.

**It is the app's own design, not a second one.** A display is set in the same
three typefaces everything else is: Fraunces at 500 for the month, the day
numbers and a screen's name, tracked uppercase JetBrains Mono for every
micro-label and every clock, Inter for the things that are read rather than
scanned — the same slots, at the same weights, as `.cal-title` and `.task-meta
.due` in the app. The server-side renderer draws in them too, from static
instances of the very woff2 the frontend ships, so a bitmap panel and a browser
panel are one design rather than two that agree about the content.

Two type decisions are the eink constraint rather than taste, and both were
measured against a thresholded render. Fraunces is pinned to the **bottom** of
its optical-size axis: its display cut is high-contrast with fine hairlines,
which is precisely what one bit deep destroys — at the top of the axis "August
2026" loses its stems and a day number turns to mush. And the mono micro-labels
sit one weight step above the app's, because a label read at arm's length and a
label read at three metres are not the same label.

**And it works on eink, where every pixel is binary.** That is a design under a
constraint, not a dark theme inverted. There is no grey, because an intermediate
value on a one-bit panel becomes a dither pattern that shimmers between
refreshes and turns small text to mush — so hierarchy is carried by size, weight
and rule, all of which survive being thresholded, and never by opacity, which
does not. That rule has teeth: a day outside the current month is drawn one size
step smaller rather than merely fainter, because "fainter" on a panel with one
ink is not drawn differently at all. There is no colour either, so *which calendar* an event belongs to is
carried by the shape of its mark: filled, hollow, a left bar, a dotted outline.
Four, because four are what stay apart across a room; a fifth calendar does not
get a fifth pattern nobody can read, it gets a letter on every chip and the
shapes keep cycling underneath. The grid is a fixed six weeks even in a month
five would hold, since a layout that changed height on the 1st would flash the
whole panel for no new information.

**Small panels are told, not smeared.** The month grid needs seven readable
columns and so it has a floor — roughly 360×260. Under it the panel draws a
sentence saying it is too small and naming the mode that does fit, and Settings
says the same beside the size field the moment you type it, because the
alternative is finding out on a wall in another room. Above it the grid is sized
by the *column* rather than by the panel's height, which is what a portrait
screen needs: seven columns of a 600px-wide Kindle are narrow whatever its
height, and a clock that cannot leave room for the event beside it is dropped so
the row says *what* rather than *when*. The other two modes have no floor at all
— habits + today shows what fits and counts the rest, down to a 2.9" panel
showing one line and "+6", and now + next is the mode a 2.9" panel is actually
*for*: one item, one line, one number. Its type is the one thing on a display
that is fitted rather than scaled, because it is the one face whose content is
fixed — two items whether the day holds three or thirty — so a bigger panel has
no "more" to spend its pixels on and spends them on the headline instead.

Three ways to drive one, because three kinds of hardware turn up. **A browser**
— a Pi in kiosk mode, an old tablet, a Boox — opens `/display/<token>` and
renders the page. **A microcontroller** — a Pico 2 W with a Waveshare panel on
it — fetches `/api/public/display/<token>.bin` and gets the **packed one-bit
framebuffer itself**: eight pixels a byte, MSB leftmost, bit 1 = white, which is
`framebuf.MONO_HLSB`, which is the `bytearray(800 * 480 // 8)` the driver
already holds. So the whole client is `sock.readinto(epd.buffer)` — no decoder,
no copy, exactly 48,000 bytes. That format exists because the other two are out
of reach from there: the PNG is saved with adaptive row filtering, so decoding
it needs zlib *and* all five unfilters, and the BMP is a container stored
bottom-up with padded rows. **A board with a decoder** takes `.png` or `.bmp`
instead, and anyone who would rather draw it themselves takes the same frame as
JSON. `firmware/` has a worked example for the Pico.

One trap worth naming, because it is closed rather than avoided: on `.png` and
`.bmp` the one-bit guarantee holds only while the display is *configured* as
e-ink — flip it to colour and the same URL serves 24-bit BGR, 1,152,054 bytes
against the 48,000 a board just allocated. `.bin` is one-bit by construction and
refuses a palette parameter at all.

**And e-ink refreshes no faster than every three minutes.** Not our preference —
the panel makers rate these screens at that and require them to sleep in
between, and say the alternative damages them permanently. A colour screen is a
backlight and keeps the minute. All three are one content model with
different rasterizers, so what a display *says* is fixed in one place and only
how it *looks* is written twice; every string arrives already formatted in the
account's language and clock, which is what stops a panel and a browser
disagreeing about a date. Everything answers 304 to a matching `If-None-Match`,
and that is the one piece of HTTP that matters here: a full eink refresh flashes
the panel for the better part of a second, and a screen polling every five
minutes would otherwise do it 288 times a day to redraw a month that changed
twice.

Each screen is its own row in Settings → Displays — name, mode, palette, which
calendars, how often, and the panel's own pixels and rotation — because the
kitchen and the hallway want different things and neither has a settings button.
The honest caveat is stated on that screen rather than buried here: **the URL is
the whole credential**, and unlike a booking link it shows the calendar itself
rather than a redacted busy grid. It is 32 bytes, it reaches one read-only call,
nothing behind it can write, and *New URL* re-keys a display in place — keeping
its name, mode and geometry — so a leaked token never costs you the screen's
configuration, which is the thing that would otherwise tempt anyone to leave one
in place.

**Tabs.** Settings → General → Tabs reorders the top strip and picks which tab
the app opens on — a fixed one, or wherever you left off. Both follow the
account.

**Appearance.** Settings → Appearance opens a live editor over the design
system: every color token (with a picker and a raw OKLCH/hex field), corner
radius, text scale, gutter and row density, the serif / sans / mono families,
and whether micro-labels are uppercase and how far they track. Save named
themes, export and import them as JSON, reset a single token, one mode, or
everything. A theme carries separate light and dark maps.

Two designs ship. **Smylte** is the default and the editorial one — warm
off-white, orange accent, Fraunces headlines, sharp corners, uppercase mono
micro-labels. **Workspace** is the restrained alternative: neutral greys, a
blue accent, one system sans in every type slot, 6px corners and sentence-case
labels.

**Neither shipped design is ever edited.** Customization is a sparse override
layer written as inline custom properties on `<html>`, so `styles/tokens.css`
stays the product's design and "Reset to Smylte" is simply dropping the
overrides. A preset is not a stored theme either — it lives in `tokens.css`
under `:root[data-preset=…]` and is selected by an attribute, which is what
keeps it un-editable and lets a palette fix reach everyone on the next deploy.
Editing while either is active forks a new theme rather than modifying it; a
fork of a preset is seeded with that preset's values, so it starts out
identical. Overrides are validated against a token allowlist on both sides of
the wire — the blob is re-read by a pre-paint script that writes straight into
the CSSOM, so a `url()` beacon or a property break-out must never survive
storage. `appearance.test.ts` asserts the defaults *and* the presets still
match `tokens.css`.

**Connect it to Claude.** Settings → Account → Connected apps, once
`TASKS_MCP_ENABLED=true`, exposes a remote **MCP server** at `/mcp` that Claude
(or any MCP client) can be pointed at as a custom connector — around forty
tools over lists, tasks (including parking one), subtasks, search, tags,
calendars, events including the recurrence scopes, free/busy, booking links, the
day plan and the week's finished count.

The day tools are read-only about *whether a day exists*: a connector can see
today, put something on it, estimate it, send it to another day, tick a note and
review how a day went, but only the owner can open a day in the app. Asking
about a day nobody has opened returns a clearly-labelled preview of what opening
it would derive, and writes nothing — the plan is worth keeping only while it
records what was actually intended, so nothing here can manufacture one, and a
day in the past cannot be planned at all.

It **reports** what you said about a day — your capacity, when you started it
and shut it down, the line you wrote — so a model can see you are already an
hour over before it proposes an eleventh thing. It cannot **write** any of it.
Those are your declarations about your own day, and a connector able to make
them would be manufacturing the record they exist to keep honest: the same call
that gives habits no tool for creating a rule. An estimate is refused on a past
day for the same reason a tick is — one written afterwards is a number chosen
with the answer in hand.

It is an OAuth 2.1 authorization server as well as the resource server, because
there is one account here and no identity provider to delegate to. Knowing the
URL gets you nothing: connecting means passing a consent screen that asks for
the app password, and you choose there whether to grant read-only or full
access. Tokens are opaque and stored only as hashes, bound to this server as
their audience, and refresh tokens rotate — presenting a used one revokes the
whole grant, on the assumption that a copy is loose. Disconnect any of them from
Settings and it stops working at once.

Off unless asked for. Turning it on adds publicly reachable OAuth endpoints, so
a deploy never grows that surface on its own — and with it on, the app refuses
to start without a public URL, app auth and a persistent session secret.

**Across the app.** Optimistic writes (paint immediately, reconcile with the
server DTO, roll back on failure), live updates over Server-Sent Events, and
account-synced UI preferences (theme, appearance, dashboard layout, task view,
sidebar state, hidden/archived calendars, hidden lists, task groups, clock,
which task lists show on the calendar). The public gate is the app's own
username/password (scrypt-hashed, cookie session); Cloudflare Access is an
optional second layer.

Settings → General → Clock switches every time the app draws between **12- and
24-hour**; `time.ts` is the only thing that formats a clock, so there is one
place for the choice to land. Date and time *pickers* are drawn by the browser
rather than by us, and read the element's `lang` to decide — which works in
Chrome, Edge and the Windows client, and is ignored by Firefox, which follows
the OS. The public booking page is deliberately left on the visitor's own
locale.

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
    mcp/        remote MCP server: OAuth 2.1 AS + resource server (oauth.py),
                Streamable-HTTP JSON-RPC transport (server.py), the tool table
                (tools.py) and its adapter onto the service (api.py)
    notify/     outbound notifications: the Telegram sender (borrowed from
                Søren), the trigger rules, and the sweep that claims/sends/
                settles against the delivery ledger
    display/    passive screens: frame.py builds what one SAYS (pure, no I/O),
                render.py rasterizes it for a panel with no browser (Pillow +
                the app's own three typefaces under fonts/, built by
                dev/build_display_fonts.py)
    due.py      one answer to "when is this due, and when is it late", shared
                by the connector and the notifier
    scheduling.py, auth.py, access.py, config.py,
                csp.py (Content-Security-Policy), limits.py (request-body cap)
  tests/        api + security + sync + concurrency + fidelity + scheduling (pytest)
  dev/          empirical probes (fidelity comparison, normalization, smokes)
                + the display fonts build (build_display_fonts.py)
frontend/
  src/
    components/ TodayView, FocusView, TasksView, CalendarView, SchedulingView,
                HomeView, BookingPage, DisplayView, Sidebar, Login, TaskModal,
                AppearancePanel, ArchivedCalendarsSection, DisplaysSection,
                FocusSection
    api.ts      typed, same-origin API client (+ SSE subscribe)
    App.tsx     shell: tabs, settings, theme, live-refresh
    appearance.ts  token allowlist + validation, apply/reset, theme import/export
    dashboard.ts   Home grid math (pack/move/resize) — pure, unit-tested
    daytext.ts     reading one typed line ("gym at 7") — pure, unit-tested
    order.ts       the one task sort — total, so array order can't leak through
    focus.ts       the focus clock, derived from the server's anchors — pure, unit-tested
    chime.ts, notify.ts  a tone made on the device, and a browser notification
    time.ts        every clock the app draws, 12- or 24-hour
    styles/     design tokens + app.css + display.css (the wall screens, which
                deliberately do NOT read the appearance override layer)
firmware/       MicroPython example for a Pico 2 W + Waveshare 7.5" e-paper:
                reads the raw framebuffer straight into the panel's own buffer
                (firmware/README.md)
desktop/        Windows client: a WebView2 window that serves the CI-built SPA
                from disk and proxies /api to the server (desktop/README.md)
scratch/        disposable Radicale 3.7.4 in Docker on :5233 (NEVER production)
deploy/         systemd unit, Caddy path-split snippet, cloudflared, setup.sh
docs/           DEPLOY.md, phase0-findings.md, recurrence-findings.md
```

## Windows client

`desktop/` builds a small native window around the app. It is not a rewrite —
it hosts WebView2, the Edge engine already on Windows 10 and 11, so rendering is
exactly the browser's. What it changes is that the app shell, CSS, JS and fonts
load from local disk instead of over the network, and that installing is one
`.exe` that keeps itself current: CI publishes the built SPA to a rolling
release, and the client picks it up on the next launch. API calls still go to
the server, so nothing about CalDAV latency changes. See `desktop/README.md`.

The one thing the client draws that the browser cannot is the **floating focus
window**: the clock and the row you are on, in a small frameless window above
everything else while the app itself waits in the taskbar. Drag it by its body,
resize it from its edges, pin it or let it fall behind, dock it to bring the
app back. It is the same `/focus` page at a small size, in the same session, so
it and the app agree to the second.

## Panel firmware

`firmware/` is a worked MicroPython example: a **Pico 2 W** and a **Waveshare
Pico-ePaper-7.5** showing a Smylte display. It is about sixty lines because the
server does the hard part — `.bin` hands back the framebuffer the panel already
holds, so the client reads a socket into `epd.buffer` and shows it.

It is an example, not a library and not a product, and it deliberately does not
vendor Waveshare's driver — that is third-party code with its own licence and
its own release cadence, and a stale copy here would be worse than none. A test
in `backend/tests/` parses the file and checks its constants against the live
endpoint, because every CI job in this repo is scoped to a directory and a new
top-level one would otherwise ship with no check at all. See
`firmware/README.md`.

**Settings → Developer** draws every display mode at the sizes real panels come
in — a 296×128 badge that cannot hold a month at all, the 800×480 the firmware
example drives, a 1872×1404 10.3" — so a layout can be judged against hardware
nobody in the room owns. It renders through the same frame builder and
rasterizer the token routes use, so what is previewed is what would ship, and
it is behind the session and writes nothing: checking a layout at ten panel
sizes should not mean minting ten live tokens and remembering to revoke them.

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
