// The Today tab: one day, held in state, that the owner actually works.
//
// Every other task surface in this app renders a QUERY — "what is due today",
// recomputed from the wire on every paint, so the list moves under you all day.
// This one renders a SNAPSHOT. The backend freezes what a day held the first
// time it was opened (`day_plan`), and from then on the day is something the
// owner arranges: adding to it, ticking it off, dropping what is not going to
// happen, and putting it in the order it will actually be worked. That is why
// the rows here come from `/api/day` and not from `tasks`.
//
// Two truths meet on this screen and only one of them lives in the day plan:
//
//   * whether a TASK is done is its VTODO STATUS, and `useTaskData().toggle` is
//     the single place in this app that writes it (through `api.complete`). A
//     day entry naming a task is a POINTER — the wire deliberately stores no
//     title and no done flag for one — so ticking a task row here goes through
//     that same call. Recording it on the entry as well would be a second
//     answer to the same question, and the two would disagree the moment the
//     task was ticked in the Tasks pane, on a phone, or in Thunderbird.
//   * whether a NOTE is done is the entry's own `done_at`, because a note
//     exists nowhere but in the day. That one is a PATCH. A HABIT OCCURRENCE is
//     on this side of the fence too, for exactly the same reason — see below.
//
// ── the add box, and saying which of those two you are making ──────────────
//
// One input, and a line of prose in it: planning a day has to be cheap or it
// does not get done, which is why there is no title field plus two pickers.
// `daytext.parseEntry` reads the line, and a reading plus somewhere to put it
// authors a REAL TASK (a thing with a due date belongs on a list the whole
// account can see, and the day entry then points at it); anything else authors
// a NOTE, which lives only in the day.
//
// That rule is unchanged and it is a good rule. What was wrong for a long time
// is that NOTHING ON THE SCREEN SAID WHICH WAY IT HAD GONE. The preview chip
// appeared only when a date was recognised, and even then it reported the
// READING rather than the consequence — so the case it never covered was the
// one that needed covering most: a plain line quietly becoming a thing that
// exists nowhere but in this day and reaches no other client on the account.
// Two very different outcomes, chosen by a parser, announced by neither.
//
// So `willBe` is the one expression that answers "what will Enter do", and the
// line under the box states it in the same three words the rows use for the
// same three things (KIND_LABEL) — plus where the thing will end up, which is
// the half that actually differs. The override is two-way, so "make this a
// task" is as sayable as "make this a note", and it does NOT reset on a
// keystroke: the boolean it replaced did, correctly, because it declined a
// PARSE and one more character can withdraw a parse, but a choice of kind is
// about intent and survives typing the rest of the line.
//
// THE FAST PATH IS UNTOUCHED: type, press Enter. The picker appears only when a
// task is being made and there is more than one list to choose, and it appears
// BESIDE a line already typed — it is never a field to fill in first.
//
// It is also where the target list stopped being a guess. `GET /api/lists`
// answers CALENDARS alongside task lists and flags which is which, and nothing
// in this app read that flag outside a test fixture — so `lists[0]` meant
// "whatever sits first in the sidebar", and on an account whose first
// collection is a calendar every dated line authored its VTODO into it.
//
// One asymmetry worth keeping straight: a task's title is the parser's, because
// the recognised phrase has been lifted out of it and into the due date; a
// note's is the LITERAL line, always. The parser deletes what it reads, and a
// note that quietly lost its "at 7" is the silent loss `daytext.ts`'s own header
// is written to avoid. And a task pinned onto a line with no date in it gets NO
// due: `dueFromParse` would fall back to the day being planned, stamping a
// deadline onto a VTODO every other client then shows as due, off the back of
// the owner asking only for it to be a task.
//
// ── habits ─────────────────────────────────────────────────────────────────
//
// A habit is A RULE THAT INSERTS ENTRIES. Opening a day gives it one ordinary
// `day_plan` row per active habit due that weekday, and that row is the whole
// of it: there is no second ledger, no per-habit history table, nothing on the
// wire. So a habit occurrence ticks like a note (its own `done_at`, a PATCH),
// drops like anything else, and is ordered by the same key.
//
// What it does NOT do is mix in. Habits paint in their own group above the rest
// of the day — a RENDER-LEVEL partition over the same ordered array, not a
// second ordering — because they are the repeating spine of the day rather than
// today's news, and a habit sitting between two one-off jots reads as a jot.
// They are also absent from the suggestions below: a habit is scheduled, and
// offering to add something that is already coming back tomorrow is offering
// the owner a decision they have already made. (That one holds by construction
// — suggestions are drawn from `tasks`, and a habit is never a task — so the
// test that pins it is guarding the property, not a branch.)
//
// ── what is on screen before the server answers ────────────────────────────
//
// Two gaps, and this tab used to fall into both while no other did.
//
// THE MOUNT GAP. Every other data surface in the app renders a query over
// `tasks` or `events`, which `cache.ts` has mirrored to disk all along, so it
// paints last-known-good rows on the first frame and replaces them when the
// fetch lands. A day plan is a SNAPSHOT and exists nowhere but in `day_plan`,
// so there was nothing to paint: the tab was blank until
// `POST /api/day/{today}/open` came back, and that call derives its snapshot
// from CalDAV — the slowest read this app makes. App.tsx renders this view
// behind `tab === 'today'`, so switching tabs unmounts it and EVERY return
// replayed the blank. Three things are mirrored now, on the same debounced
// trailing edge `data.tsx` uses: the day itself, the fortnight behind the habit
// counts and the "still open" suggestions, and the habit rules the sheet edits.
// The contract is the mirror's usual one — the server is the source of truth,
// this is only what to show until it answers, and nothing here gates rendering
// on freshness.
//
// Only TODAY is written, and every read is keyed to the day it was written for.
// `day` is seeded from the wall clock, so a mount always lands on today and a
// look-back never survives one; a past day in the mirror could therefore never
// be read back, and would only evict the entry that is. The key matters for the
// same reason the `plan.day === day` guard does everywhere below: the rows on
// screen and the day every write carries have to be the same day or the surface
// lies about what was planned.
//
// THE GESTURE GAP. Every write here paints first and reconciles after —
// including the two that did not: the add box's TASK path (which has to author
// a VTODO before the day can point at it, and used to show nothing at all for
// the length of both round trips) and the two rituals' last presses, which held
// their overlay open over the day until the server answered. The uid a create
// will land under is known up front (`uidFor`), which is what lets a day row
// point at a task that does not exist yet.
//
// AND EVERY SETTLE IS FIELD-TARGETED. `PATCH /api/day` answers with the whole
// plan and `PATCH .../entries/{id}` with the whole row, so a reply taken
// wholesale carried an opinion about fields the call never asked about — and
// two writes on one day, or on one row, then raced. The shutdown ritual issues
// two by design: the reflection commits on the blur that the "Shut down" press
// itself causes. Each writer settling exactly what it wrote makes that
// impossible rather than unlikely.
//
// ── the midnight problem ───────────────────────────────────────────────────
//
// Nothing else in this app recomputes on a day boundary, and nothing else has
// to: `rev` only moves when the server publishes, and HomeView computes today
// at render, so its worst case is a stale-looking card that repaints on the
// next SSE bump. A STATEFUL surface cannot get away with that. Left open
// overnight — which is the normal way a daily surface is used — a day key
// computed once at mount would still say yesterday, and every write this view
// makes carries the day in its URL. The check-off the owner made over breakfast
// would land on YESTERDAY's plan: it would not appear on the screen in front of
// them, and it would silently rewrite a day that is supposed to be a finished
// record. So the day is state, a timer re-reads the wall clock at the next
// local midnight, and every write carries the key explicitly.
//
// ── the look-back, and the one rule that makes it safe ─────────────────────
//
// The picker steps back through recent days and forward again to today. TWO
// day keys therefore exist here where one used to: `today`, which the midnight
// timer tracks, and `day`, which is what the owner is looking at.
//
// `api.openDay` IS CALLED FOR `today` AND FOR NOTHING ELSE. That is the whole
// contract of this surface, not a nicety. Opening a day is the only call that
// can CREATE a plan, and on a day that has never been opened it derives a
// snapshot — what is due, what is late, what was left over — from the wire AS
// IT IS NOW. Pointed at a past day it would write today's leftovers into a day
// that has already happened, and the `planned` marker would then claim the
// owner planned a day they merely glanced at: exactly the fabricated record
// this feature exists to avoid. The backend deliberately does not stop it. It
// gates HABIT minting on pastness (`service._habit_minting_allowed`, one day of
// grace) because an occurrence exists nowhere but in its row, but the TASK
// snapshot still derives on a first open whatever the day — see the four-case
// table in `service.open_day`. So the ternary in the read effect below is the
// only thing standing here. Every other day is read through `api.day`, which is
// `open_day(create=False)` and writes nothing at all.
//
// A PAST DAY IS THEREFORE READ-ONLY END TO END: no add box, no suggestions, no
// checkbox, no drop control, no habits sheet, no arranging. That is the same
// line `mcp/api.py::update_day_entry` draws for the connector, which refuses
// `done` on a past day because "a tick is a record that something was done AT
// THE TIME" — a habit occurrence's stamp is the only record of it anywhere, and
// a log that can be filled in afterwards is a scorecard. The browser must not
// be the hole in a rule the model is held to.
//
// What a past day shows instead is the RECORD: the day split by where each row
// came from (`source`), the rows that were dropped, and what was finished that
// day without ever being on the plan. It answers the same question
// `smylte_review_day` answers, and it is bucketed the same way on purpose —
// two surfaces disagreeing about one day is worse than either being slightly
// wrong. See REVIEW_ARM.
//
// THE RECORD IS NOT ONLY A PAST DAY'S. `mode` shows the same thing for TODAY,
// and the whole of that feature is a render-level switch: `review` and `offPlan`
// are pure memos over `allEntries` and `tasks`, both already in hand, so
// pressing Review issues no request whatsoever. `mode` is deliberately absent
// from the read effect's dependency list — there is nothing for it to be in it
// for, and a review that re-read the day would be a second caller of the one
// call that can create a plan. `LookBack` is reused verbatim rather than
// reimplemented, for the same reason the buckets match the Python's arm for arm.
//
// The two cases stay honestly different, and READ-ONLY-NESS IS KEYED ON
// `isToday`, NEVER ON `mode`. Today reviewed is today: its rows still tick, its
// add box stays (noting down what actually happened is the commonest reason to
// be here at 9pm), and only the suggestions go, because a review is not a place
// to be handed more work. A finished day hands out nothing whichever mode today
// was left in.
//
// ── the two rituals ────────────────────────────────────────────────────────
//
// The day now has a SHAPE as well as contents, and the two overlays are where
// it gets one. `PlanRitual` in the morning — how long today is, what goes on
// it, how long each thing takes — and `ShutdownRitual` at the end: what
// happened, what follows you, a line about how it went. Both are three steps,
// every step skippable, closable at any point, because a ritual you cannot
// leave is a wizard and this tab is also the place you merely glance at.
//
// Neither is opened for you. The morning one is reached from a dismissible
// band and the evening one from a header button, and that asymmetry is
// deliberate: the morning is when a plan is worth prompting for, while a band
// offering to close the day would be on screen from breakfast onwards.
//
// WHAT THE OWNER SAYS ABOUT A DAY lives in `day_ritual`, not in `day_plan`:
// a capacity, a `committed_at`, a `shutdown_at` and a reflection belong to the
// day rather than to any row on it. `capacity` on the plan DTO is RESOLVED —
// this day's statement, else the weekday default, else the account's, else
// NONE — and none is a real answer that means no total and no warning. An
// account that never stated a capacity must not be told it has overcommitted
// against a number it never gave, which is the one thing this feature must not
// do. `capacity_minutes` beside it is what was stated for THIS day, so a day
// that merely inherited stays distinguishable from one the owner set.
//
// THREE RULES ARE LIFTED INTO `ShutdownRitual` RATHER THAN RE-DERIVED THERE,
// and each of them was a bug before it was a prop: `isDone` (a task's doneness
// is its VTODO's — see the fence above), `titleOf` (a task entry carries NO
// title, so reading `entry.title` printed a placeholder against every task on
// the one screen whose job is deciding about them), and `renderRow` itself.
// The ritual holds no second opinion about any row.
//
// ── moving work, which is not dropping it ──────────────────────────────────
//
// `rolled_to` is the second stamp a row can carry and it is emphatically not
// `dropped_at`. "This is happening on Thursday" and "this is not happening" are
// different answers, and the whole point of recording the decision WITH its
// destination is that a look-back can say where the work went instead of
// filing it under abandoned. `service.roll_entry` MOVES NOTHING: it writes a
// row on the target day and stamps this one, so the day that planned the work
// still shows it planned the work.
//
// The difference shows in exactly three places here, and all three are load-
// bearing: `entries` filters both stamps out (so a decided row leaves the list
// AND the day's total, which is how you get back under a capacity you have
// overrun); `onDay` filters only `dropped_at` back IN, so a declined task can
// be chosen again this afternoon while one with a destination is not offered
// back under "Due today"; and the look-back gives `moved` its own heading with
// the destination in place of the due date.
//
// This deliberately does not touch `service._carry_into`'s carry-once rule.
// That rule is about work the system moves FOR you — "a task the owner chose on
// Monday and then ignored on Tuesday has been declined" — and work you CHOSE to
// move is a different thing. Both survive, and the automatic carry stays the
// safety net for a day you never shut down: leaving a row alone in the shutdown
// is a real answer, and it is the one the carry still answers.
//
// ── arranging ──────────────────────────────────────────────────────────────
//
// The fourth verb, and for a long time the only one of the four this file
// promised and did not deliver. `day_plan.position` is a REAL, the server orders
// on (position IS NULL, position, created_at, entry_id), and it positions every
// row it writes — so a drop is ONE write: the moved row takes a midpoint between
// its new neighbours and nothing else changes. That is the whole reason not to
// copy the Tasks pane's whole-list renumber, which exists because ITS order is
// global across lists and lives in the sidecar.
//
// Both drag directions land between the same pair, `without[to - 1]` and
// `without[to]`, because removing the dragged row shifts every later index down
// by one. Habits are excluded: an occurrence's position is minted fresh by its
// rule each morning, so an order dragged into the spine would be gone tomorrow,
// and a gesture whose effect silently expires is worse than none. So is any day
// holding a row with no position yet — an optimistic add, which `orderEntries`
// sorts to the end, and which a midpoint would therefore be measured against
// wrongly for the length of one round trip.
//
// Pointer-only, as every other drag in this app is (sidebar, tasks, dashboard,
// calendar). A phone cannot arrange its day, and that gap is the app's rather
// than this screen's — written down here rather than closed with a bespoke
// touch gesture that would behave differently from the other four.
//
// One consequence of the fence above falls out here and is worth stating, since
// the record depends on it: a day entry keeps no done flag for a TASK, so on a
// finished day "was this done?" cannot be the task's current status — that is a
// fact about now, not about the day. It is the task's COMPLETED stamp falling
// on that day, by `dayKey`. Planned on the 15th and ticked on the 22nd is a
// completion belonging to the 22nd, and the 15th must not claim it. See
// `rowDone`, which every mark and every count on this screen goes through.

import {
  useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode,
} from 'react'
import {
  api, clientId, HABIT_DAYS, uidFor,
  type CalEvent, type DayEntry, type DayPlan, type Habit, type PatchHabitBody, type Task,
} from '../api'
import { useCalendarData, useTaskData } from '../data'
import { useEscape } from '../hooks'
import {
  CACHE_DEBOUNCE_MS,
  cacheDayPlan, cacheDayRange, cacheHabits,
  readCachedDayPlan, readCachedDayRange, readCachedHabits,
} from '../cache'
import {
  addDays, cssColor, dayKey, isOverdue, makeGuard, msUntilMidnight, parseDate,
  textDir, ymd,
} from '../util'
import { fmtClock, fmtDue, fmtDuration } from '../time'
import { useI18n } from '../i18n'
import { habitDayLabel } from '../names'
import { useTimeFormat } from '../timeformat'
import { sortByCompletion, sortTasks, taskKey } from '../order'
import { bucketByDay, eventKey, monthGrid, type DayEv } from '../calendar'
import { parseEntry, type ParsedEntry } from '../daytext'
import { AgendaEvent } from './DayPopover'
import { PlanRitual } from './PlanRitual'
import { ShutdownRitual } from './ShutdownRitual'
import { useT } from '../i18n'

/** How far ahead the "next 7 days" suggestions reach. Same horizon as the Home
 *  dashboard's Upcoming module, so the two never disagree about what is soon. */
const SOON_DAYS = 7

/** How far back the look-back reaches: the earliest day the picker will step
 *  to, and the span of the ONE `api.days` read behind this screen.
 *
 *  ONE NUMBER, TWO WINDOWS, ANCHORED DIFFERENTLY — they are not the same span,
 *  and making them one would be a bug. The picker's floor (`earliest`) is
 *  measured from TODAY, so it stays put as the view steps back; measured from
 *  `day` it would recede a day with every click and the look-back would have no
 *  bound at all. The range read is measured from `day`, so the habit counts
 *  answer the week the REVIEWED day fell in. The two coincide only while the
 *  view is on today. Parked on the floor the read asks for
 *  `[today - 28, today - 13)` — twice as far back as the picker will go — and
 *  that is deliberate: the week containing the floor day begins up to six days
 *  BEFORE it, so clamping `rangeFrom` to `earliest` would cut that week short
 *  and under-report every habit on the oldest days the picker can reach.
 *
 *  That one read feeds the habit counts (which need Monday of the week the day
 *  on screen falls in — at most six days back) and the "still open from a
 *  recent plan" suggestion (which needs the days the owner actually chose
 *  things on), and a second range call for the second job would be the same
 *  rows fetched twice.
 *
 *  A fortnight is a judgement call, not a derived number: long enough that last
 *  week is reachable — the week you would actually want to look back at on a
 *  Monday — and short enough that a look-back is recent work rather than an
 *  archive. It is well inside the 190-day span the endpoint will answer
 *  (`service.DAY_RANGE_MAX_DAYS`), and it is NOT the carry-over's reach: that is
 *  `service._CARRY_LOOKBACK_DAYS`, 30 days, answering the different question of
 *  how far back to look for a plan to carry FROM. */
const LOOKBACK_DAYS = 14

/** How long a task with NO DUE DATE may sit untouched before the day offers it
 *  back, measured from `last_modified` (or `created` — see the suggestion).
 *
 *  Three weeks, and the number has two jobs. It must clear SOON_DAYS by a
 *  distance, or the group would be describing a stretch of time the three dated
 *  groups already cover. And it has to be long enough that "you have not looked
 *  at this in a while" is TRUE: a task left alone for a fortnight is a task
 *  someone is getting to, while one nobody has touched in three weeks has
 *  stopped being live, which is the only thing worth interrupting the day for. */
const STALE_DAYS = 21

/** How many of a suggestion group's tasks are shown before the rest are put
 *  behind one press.
 *
 *  There are FIVE groups, and every one of them rendered every task it matched.
 *  On an account with a real backlog that is a wall — "Overdue" alone can be
 *  fifty rows — and it sits directly beneath the day it is offering things to,
 *  so the day itself scrolls off the top. A surface for planning one day should
 *  not open onto a list of everything that is wrong.
 *
 *  Five is a judgement call in the same shape as the constants above it: enough
 *  that a group reads as a list rather than a teaser, few enough that all five
 *  groups plus the day fit on a screen. It bounds what is PAINTED and nothing
 *  else — see the render, and the comment on `offered` below, which is why the
 *  cap cannot be applied where the groups are built. */
const SUGGEST_MAX = 5

/**
 * A day entry's `source` → the arm a look-back files it under.
 *
 * Arm for arm with `mcp/api.py::review_day`'s `arm_of`, deliberately, down to
 * the words: that tool answers this same question for the connector, and one
 * day of the owner's life described two different ways by two surfaces is worse
 * than either description being slightly off.
 *
 * Keyed by plain string, and read with a fallback, because the RESIDUAL is the
 * point rather than an oversight. `source` is chosen server-side and this map
 * enumerates the four values that exist today; a fifth would match none of them
 * and — with an exhaustive `Record<DayEntrySource, …>` and a bare lookup —
 * would land in `undefined` and be dropped from the screen in silence. That is
 * precisely the bug the Python's own comment records: three equality tests
 * covered the three sources that existed when they were written, and habit
 * occurrences fell out of the retrospective when they arrived. A row under an
 * unfamiliar heading costs nothing; a row that vanishes costs the record.
 */
const REVIEW_ARM: Record<string, string> = {
  user: 'chosen', carried: 'carried', auto: 'derived', habit: 'habits',
}

/** The look-back's groups, in reading order, and the only place their headings
 *  are written.
 *
 *  The last two are NOT sources: the day stamps rather than deleting, and
 *  "planned it and decided against it" is one answer whatever put the row there
 *  — the same reason `review_day` keeps it out of the source buckets.
 *
 *  `moved` is the other one, and it is separate from `dropped` because they are
 *  DIFFERENT ANSWERS: work that is happening on Thursday and work that is not
 *  happening. Filing both under "Dropped" would be the one thing `rolled_to`
 *  exists to stop — it records a decision AND its destination, so a look-back
 *  can say where the work went instead of reporting it abandoned.
 *
 *  Every key here is a key of the bucket record built below, so a heading cannot
 *  name a bucket nothing fills. */
const REVIEW_GROUPS = [
  { key: 'chosen', label: 'today.group.chosen' },
  { key: 'carried', label: 'today.group.carried' },
  { key: 'derived', label: 'today.group.derived' },
  { key: 'habits', label: 'today.group.habits' },
  { key: 'other', label: 'today.group.other' },
  { key: 'moved', label: 'today.group.moved' },
  { key: 'dropped', label: 'today.group.dropped' },
] as const

/**
 * A day entry's `kind` → what that kind is called, for the row's mark.
 *
 * Keyed by plain string and read with a fallback, for exactly the reason
 * `REVIEW_ARM` is: `DayEntryKind` widens SILENTLY — api.ts says so in as many
 * words, because nothing in this app switches on it exhaustively — and an
 * unfamiliar kind announcing itself as "Entry" costs a reader nothing, while a
 * lookup that came back `undefined` would hand assistive tech a nameless
 * `role="img"` on every row of a kind this build has not heard of.
 *
 * The three names are the ones the add box uses for the same three things, on
 * purpose: what the box promises to create and what the row then calls itself
 * have to be one vocabulary, or the teaching the box now does is undone by the
 * list directly beneath it.
 */
const KIND_LABEL: Record<string, string> = {
  task: 'today.kind.task', note: 'today.kind.note', habit: 'today.kind.habit',
}

/** The smallest denominator the weekly count is willing to be shown at.
 *
 *  With one occurrence there is nothing to say: "0 of 1 this week" on a Monday
 *  morning is a scoreboard opened on the first play, and "1 of 1" is a
 *  congratulation for getting out of bed. Two is the smallest number that
 *  describes a habit rather than a single day, so below it the count is omitted
 *  ENTIRELY rather than shown as an empty or zeroed one. */
const MIN_WEEK_COUNT = 2

/**
 * The Monday of the week the day key `day` falls in, as a day key.
 *
 * THE ONE PLACE the two week conventions in play are converted between, which
 * is why it is a named function rather than an expression inline at its single
 * call site. `Date.getDay()` is 0=SUNDAY. Everything else in reach is
 * Monday-first: a habit's `days` is written mon..sun (`HABIT_DAYS`), the server
 * derives a weekday with Python's `date.weekday()` (0=Monday), and the booking
 * availability map has keyed "0" to Monday since long before habits existed.
 * `(getDay() + 6) % 7` is that shift — Sunday's 0 becomes 6, Monday's 1 becomes
 * 0 — and it is used for exactly one thing: finding where the week the count
 * spans begins.
 *
 * It deliberately does NOT go the other way. Turning a weekday number back into
 * one of the `HABIT_DAYS` names would be a second copy of the mapping the
 * server already owns, and which day a habit runs on is the server's decision
 * (taken off the day key's own characters, so no clock and no zone is involved).
 * Two copies of that mapping is how "wed" comes to mean Wednesday on one side
 * and Thursday on the other, for one weekday only, silently.
 *
 * The key is parsed as LOCAL midnight — the same `${day}T00:00` spelling the
 * suggestion horizon uses below — because a bare "2026-08-21" parses as UTC and
 * lands on the previous day for every viewer west of it.
 */
export function weekStartOf(day: string): string {
  const d = new Date(`${day}T00:00`)
  return ymd(addDays(d, -((d.getDay() + 6) % 7)))
}

/**
 * A day's entries in reading order, as a new array.
 *
 * The same total key the server reads them by (`store._DAY_ORDER`:
 * `position IS NULL, position, created_at, entry_id`) — unpositioned rows TRAIL
 * rather than lead, and the last two keys are what make it total. Re-applied
 * here rather than trusting the fetched order because the array is edited
 * locally between fetches: an optimistic add is appended, and a row that
 * painted at the bottom must not jump somewhere else when the server's copy of
 * the day arrives. `created_at` is millisecond-resolution, so a whole snapshot
 * can share one value; without `entry_id` behind it two rows would be free to
 * swap places between two renders of an unchanged day.
 */
export function orderEntries(entries: DayEntry[]): DayEntry[] {
  return [...entries].sort((a, b) => {
    const an = a.position == null
    const bn = b.position == null
    if (an !== bn) return an ? 1 : -1
    if (!an && !bn && a.position !== b.position) return a.position! - b.position!
    return a.created_at.localeCompare(b.created_at) || a.entry_id.localeCompare(b.entry_id)
  })
}

/**
 * The `due` a parsed line should author, on the day being planned.
 *
 * A time with no date is the ordinary reading — "gym at 7" names an hour and
 * leaves the day alone — and `daytext` refuses to guess a day from the clock on
 * purpose, so supplying one is the caller's job. This view is planning a
 * particular day already, which makes it the right caller: the day on screen is
 * the day the line lands on, including after a midnight rollover.
 */
export function dueFromParse(p: ParsedEntry, day: string): string {
  const date = p.dueDate || day
  return p.dueTime ? `${date}T${p.dueTime}` : date
}

/**
 * Was this row done ON THE DAY IT BELONGS TO?
 *
 * THE ONE PLACE that question is answered, because two things ask it about the
 * same rows — the row's own mark and the header's "N done" — and a day whose
 * header disagrees with the list under it is a record nobody can reconcile.
 *
 * A note's and a habit occurrence's doneness is the entry's own stamp, and that
 * stamp can only ever be written on the day itself (`update_day_entry` refuses
 * `done` on a past day, because a log that can be filled in afterwards is a
 * scorecard), so for them `done_at` already answers the day question.
 *
 * A TASK is the one that needed fixing. A task entry deliberately stores no done
 * state — the VTODO STATUS is the single truth, see this file's header — and
 * that flag says whether the task is done NOW, not whether it was done on the
 * day being read. On a finished day the flag is simply the wrong question: a
 * task planned on the 15th, left undone, and ticked on the 22nd would paint the
 * 15th as a day it was completed on, a completion that day never held. So a past
 * day asks the COMPLETED stamp instead, bucketed with `dayKey` — never by
 * slicing the string, since a stamp another client anchored to a zone and one
 * this app wrote floating do not agree lexically, and slicing files a
 * late-evening tick on the wrong day for anyone west of UTC. That is the rule
 * `offPlan` on this same screen has always applied, and the rule
 * `_completions_by_day` applies server-side; before this, one screen answered
 * "was it done that day?" two different ways.
 *
 * `live` — the day on screen is today — keeps the flag, and must. A task ticked
 * a moment ago has to show ticked on the click, and its COMPLETED stamp is not
 * in hand until the write comes back. On today the two rules agree anyway,
 * except for a task some other client completed without ever writing COMPLETED,
 * where the flag is the only evidence that exists.
 *
 * A task completed on the day and RE-OPENED since reads as NOT done, and that is
 * the chosen answer rather than an accepted loss. Re-opening CLEARS the
 * COMPLETED property (`ical/edit.py::_set_status` — completion is a coupled
 * write and re-opening is its inverse) and the entry keeps no done state of its
 * own, so afterwards nothing anywhere records that the day ever held that
 * completion. A mark would be evidence this app invented; no mark is the
 * conservative direction and the only one the data supports.
 *
 * Keyed on the ENTRY's own day rather than on the view's, so the answer travels
 * with the row into whichever list paints it.
 */
/**
 * What a row READS AS, wherever it is painted.
 *
 * Module-level and shared for the reason `rowDone` is: the shutdown ritual asks
 * this question too, and a row whose title is resolved twice is a row that
 * eventually reads two different ways in two places. It resolves the day's
 * hardest case — a task entry carries NO title of its own, because the VTODO's
 * summary is the truth and copying it into the day would freeze a rename.
 *
 * A habit occurrence takes the `!isTask` arm and reads its own title, which IS
 * the copy taken from the rule when the row was minted. Deliberate on both
 * sides: renaming a habit leaves last Tuesday saying what the owner planned
 * last Tuesday, and deleting one leaves the row perfectly readable.
 *
 * The empty string is a real answer, and is why `tasksLoaded` is a parameter:
 * before the tasks land, "no longer in your lists" would be a confident claim
 * about a fetch still in flight, so the row waits rather than lying.
 */
export function entryTitle(
  e: DayEntry, task: Task | undefined, tasksLoaded: boolean,
  // The translator, passed in rather than hooked: this is a pure function of
  // the row and is called from a memo, not from a render.
  t: (key: string) => string,
): string {
  if (e.kind !== 'task') return e.title || ''
  if (task) return task.summary || t('common.untitled')
  return tasksLoaded ? t('today.taskGone') : ''
}

/**
 * Whether a row counts as finished.
 *
 * A TASK entry never records doneness of its own — the task's own state is the
 * truth, and this file's header says why. A note and a habit occurrence exist
 * nowhere but in the day, so the day is where their stamp lives.
 *
 * `live` is what separates the two readings of a task row. On a day still
 * running, "done" means the task is done NOW; on a finished day it means the
 * task was finished ON THAT DAY, so a task ticked this morning cannot add itself
 * to last Tuesday's record.
 *
 * Exported for the dashboard's plan module, which shows the same rows and must
 * read them the same way. Two surfaces deciding doneness independently is
 * exactly the drift this function exists to prevent — the module passes
 * `live: true`, because a dashboard only ever shows today.
 */
export function rowDone(e: DayEntry, task: Task | undefined, live: boolean): boolean {
  if (e.kind !== 'task') return !!e.done_at
  if (live) return !!task?.completed
  return !!task?.completed_at && dayKey(task.completed_at) === e.day
}

export function TodayView({
  rev, onExpire, hiddenCalendars = [], archivedCalendars = [], onStartWorking,
}: {
  rev: number
  onExpire: () => void
  /** The way into the focus surface. Optional, because the header only offers
   *  it where App can honour it: a dashboard module or a test rendering this
   *  view on its own has nowhere to send the click. */
  onStartWorking?: () => void
  // Read-only here, exactly as on the Home dashboard: the calendar strip honours
  // the Calendar tab's visibility choices, and that tab stays the sole owner of
  // editing (and pruning) these sets.
  hiddenCalendars?: string[]
  archivedCalendars?: string[]
}) {
  const { lang, locale, t: tr } = useI18n()
  // A STABLE guard, so it can sit in an effect's dependency list honestly
  // instead of behind an eslint-disable. `makeGuard(onExpire)` written at the
  // top of a render mints a fresh function on every paint, which would re-run
  // every effect that named it. Same shape (and same reason) as DataProvider.
  const expire = useRef(onExpire)
  expire.current = onExpire
  const guard = useMemo(() => makeGuard(() => expire.current()), [])

  const tf = useTimeFormat()
  const { lists, tasks, loaded, create, toggle } = useTaskData()

  // ── the day, and the rollover that keeps it honest ───────────────────────
  //
  // `today` is what the clock says; `day` is what the owner is looking at. They
  // are one value until the picker moves, and keeping them apart is what makes
  // the read below safe — see the header.
  const [today, setToday] = useState(() => ymd(new Date()))
  const [day, setDay] = useState(today)
  const isToday = day === today
  // Bumped every time the rollover timer fires, purely so the effect below
  // re-runs and arms the next one. It deliberately does NOT key off `today`:
  // when the timer fires and the date has not actually changed, `setToday`
  // writes the value already in state, React bails out of the re-render, the
  // effect never re-runs — and the surface is stuck on that day for the life of
  // the page, which is the exact failure the timer exists to prevent.
  const [armed, setArmed] = useState(0)

  // Both keys as the timer will need to read them, without either going in the
  // effect's dependency list. Stepping the picker must not re-arm the timeout:
  // the next local midnight does not depend on which day is being looked at, so
  // naming `day` there would claim a dependency that is not real and would
  // restart the countdown on every click. Same shape as `expire` above.
  const view = useRef({ day, today })
  view.current = { day, today }

  useEffect(() => {
    // `msUntilMidnight` carries the arithmetic and the slack — see util.ts. What
    // stays here is what this surface does when it fires, which is more than
    // `useToday` does: the picker moves only while it is parked on today.
    const t = setTimeout(() => {
      // The wall clock decides, never arithmetic on the key we were holding. A
      // laptop asleep through midnight fires this LATE — possibly days late,
      // and browsers throttle background timers besides — so reading the clock
      // lands on the day it actually is now rather than on the day after the
      // one it used to be.
      const nowKey = ymd(new Date())
      // The VIEW follows the clock only while it is showing today. That is the
      // original midnight fix, unchanged, and the guard is what the picker adds
      // to it: someone reviewing last Tuesday at 23:59 must not have the page
      // jump to a fresh empty day under their cursor. Reading both keys off the
      // ref rather than off the closure is what makes the comparison the CURRENT
      // one — the closure's copies are from the render that armed this timeout,
      // which may be many picker clicks ago.
      if (view.current.day === view.current.today) setDay(nowKey)
      setToday(nowKey)
      setArmed((n) => n + 1)
    }, msUntilMidnight())
    return () => clearTimeout(t)
  }, [armed])

  // ── the plan ─────────────────────────────────────────────────────────────
  //
  // SEEDED FROM THE DISK MIRROR, like every other data surface in this app. The
  // Today tab was the last one that was not, and it is the one that needed it
  // most: every other task view renders a query over `tasks`, which `cache.ts`
  // has mirrored all along, so it paints from disk on the first frame. This one
  // renders a snapshot that exists nowhere but in `day_plan` — so with nothing
  // cached the tab had no content at all until `POST /api/day/{today}/open`
  // came back, and that call derives its snapshot from CalDAV, which is the
  // slowest read the app makes. Switching tabs unmounts the view (App.tsx
  // renders it behind `tab === 'today'`), so every single return to the tab
  // replayed that blank.
  //
  // Read for `today` and not for `day`, because they are the same value on the
  // frame this runs: `day` is seeded from `today` above, so a mount always
  // lands on today and a look-back never survives one. Same contract as the
  // rest of the mirror — the server is the source of truth, this is only what
  // to show until it answers, and the fetch below overwrites it either way.
  const [plan, setPlan] = useState<DayPlan | null>(() => readCachedDayPlan(today))
  // The plan as it stands NOW, for the writers below. A `useCallback` that
  // closed over `plan` would have to name it as a dependency and be rebuilt on
  // every optimistic paint; the ones that roll back need the value they are
  // rolling back to, and reading it off a ref is how `expire` and `view` above
  // solve the same problem.
  const planRef = useRef(plan)
  planRef.current = plan
  // Every fetch is stamped and every write bumps the stamp, so a response
  // commits only while it is still the newest — the same guard `useTaskData`
  // puts on its task fetches. It matters more here than it looks: each write
  // this view makes publishes `day_updated`, which bumps `rev` a beat later and
  // re-runs the effect below, so without the stamp a refetch would routinely
  // land on top of the optimistic paint that provoked it and undo it for a
  // frame. It is also what drops a response for a day that has since rolled
  // over — the rollover re-runs this effect, which bumps the stamp.
  const token = useRef(0)

  // The day read has a THIRD outcome, and it used to have two. `plan` only ever
  // became non-null on a successful 200, a rejection was swallowed by `guard`
  // into a transient toast, and every render of the day is gated on
  // `entries !== null` — INCLUDING the empty state. So a failed read showed the
  // heading, the add box, the calendar strip and the suggestions over a blank
  // space that said nothing, with no retry short of navigating away and back.
  //
  // Worse than blank: every optimistic writer reads `setPlan((p) => (p && …))`,
  // so with `plan` null they are all no-ops. The owner typed a line, pressed
  // Add, the POST SUCCEEDED server-side, the box cleared — and no row appeared.
  // `POST /api/day/{day}/open` derives its snapshot from CalDAV, so a Radicale
  // hiccup that times out that one call while every other endpoint is healthy is
  // the realistic trigger.
  const [dayError, setDayError] = useState(false)
  // The retry's own signal, for the same reason `reloadTasks` needed one: `rev`
  // moves only when the SERVER publishes a change.
  const [dayTry, setDayTry] = useState(0)

  useEffect(() => {
    const mine = ++token.current
    setDayError(false)
    void guard(async () => {
      // THE load-bearing line of this file. `openDay` may be called for TODAY
      // and for no other day, because it is the only call that can create a
      // plan and it snapshots from the wire as it is NOW — pointed at last
      // Tuesday it would invent a plan for a day that has already happened.
      // `api.day` is `open_day(create=False)` and writes nothing whatsoever,
      // not even the opened marker, which is what makes stepping back safe.
      // Read the header before touching this.
      let p: DayPlan | undefined
      try {
        p = await (day === today ? api.openDay(day) : api.day(day))
      } catch (e) {
        // Recorded here and RE-THROWN, so `guard` still raises its toast and
        // still routes an AuthError to the login card. The flag is what the
        // screen needs; the toast is what a transient blip needs.
        if (mine === token.current) setDayError(true)
        throw e
      }
      if (mine !== token.current) return
      // A malformed body must not become the array every render maps over —
      // `guard` shields us from a rejection, not from a 200 with junk in it.
      // A 200 with junk in it is a failed read too, and said so nowhere.
      if (p && Array.isArray(p.entries)) setPlan(p)
      else setDayError(true)
    })
    // `today` alongside `day` because the effect READS it: the ternary above is
    // the load-bearing line of this file, and an effect that reads a key it has
    // not declared is one refactor from choosing OPEN over READ off a stale
    // closure. It buys exactly one re-run that `day` alone would not, and it is
    // NOT a rollover under the day being worked: when `day === today` the timer
    // sets both keys in one batched update, so the view did move and `day`
    // re-runs this by itself. The re-run `today` contributes is the other case
    // — the view parked on a PAST day at midnight, a day that was already past
    // and whose rows came from `api.day` — and all it does is read that same
    // past day again through that same `api.day`. Harmless, and cheaper than a
    // dep array that lies about what the effect looks at.
  }, [day, today, rev, guard, dayTry])

  // Mirror the day to disk on the trailing edge, so a burst of optimistic
  // paints — ticking four rows, dragging one — costs one write rather than one
  // per click. Writing on the OPTIMISTIC paint too is deliberate and is the
  // same call `data.tsx` makes for tasks: coming back to the tab straight after
  // adding a line should show the line.
  //
  // TODAY's only. The mirror holds one day (see `cacheDayPlan`) and the tab
  // always mounts on today, so a plan written while looking back at last
  // Tuesday could never be read back — it would only evict the one entry that
  // does get read. A past day is a finished record besides: there is nothing to
  // paint quickly for a screen nobody arrives on.
  useEffect(() => {
    if (!plan || plan.day !== today) return
    const t = setTimeout(() => cacheDayPlan(plan), CACHE_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [plan, today])

  // ── the picker's bounds ──────────────────────────────────────────────────
  //
  // The floor is measured from `today`, never from `day`: one that moved with
  // the view would recede a day with every step back, and the look-back would
  // have no bound at all. The ceiling needs no arithmetic — today is it.
  const earliest = useMemo(
    () => ymd(addDays(new Date(`${today}T00:00`), -LOOKBACK_DAYS)), [today])
  // The day each arrow would land on, or null when there is no such day. ONE
  // expression per direction, feeding both the button's `disabled` and its
  // click: a bound written once for the arrow and again for the step is a bound
  // that can disagree with itself, and that disagreement is an enabled control
  // that walks off the end of the window — which would fail SILENTLY, as an
  // empty day, because reading an unplanned day is a perfectly good request.
  const prevDay = day > earliest ? ymd(addDays(new Date(`${day}T00:00`), -1)) : null
  const nextDay = day < today ? ymd(addDays(new Date(`${day}T00:00`), 1)) : null

  // Every row the day holds, dropped ones included, in reading order. Keyed on
  // the day it was fetched for, so a rollover — or a step of the picker — shows
  // NOTHING rather than yesterday's rows under today's heading; the rows on
  // screen and the day every write carries have to be the same day or the
  // surface lies. `null` means "not known yet", which is what keeps the empty
  // state from flashing before the first read lands.
  const allEntries = useMemo(
    () => (plan && plan.day === day ? orderEntries(plan.entries) : null),
    [plan, day])

  // The LIVE rows: what the day currently holds. Dropped and MOVED entries come
  // back on every read by design (the server stamps rather than deletes, so a
  // day can still say what was declined and where work went) and are filtered
  // out here, the one place with a reason to — everything that paints the day
  // as a list of things to do reads this. The look-back is the exception and
  // reads `allEntries`, because "I decided against this" and "I moved this to
  // Thursday" are two of the most useful things a finished day can say.
  //
  // Both leave the day's list and its TOTAL. Moving something forward is how
  // you get back under a capacity you have overrun, so a total that kept
  // counting it would make the one control that helps useless — the same
  // reasoning that takes a dropped row out.
  const entries = useMemo(
    () => allEntries?.filter((e) => !e.dropped_at && !e.rolled_to) ?? null,
    [allEntries])

  // A RENDER-LEVEL partition over the array `orderEntries` already ordered —
  // both halves keep the positions the server gave them, and nothing is sorted
  // a second time.
  //
  // The split is doing real work rather than confirming an order that is already
  // there. Habits lead the FIRST snapshot of a day and nothing else: a habit
  // created at 18:00 is topped up onto the END of a day the owner has spent all
  // day arranging (`service.open_day` — a late arrival must not renumber the
  // arrangement it is joining), so without this it would appear under the last
  // thing they typed rather than with the rest of the spine.
  const habitRows = useMemo(() => entries?.filter((e) => e.kind === 'habit') ?? [], [entries])
  // `!== 'habit'` rather than a list of the other two: a kind this build has
  // never heard of belongs with the day's ordinary rows, where it is at worst
  // in the wrong order, rather than silently vanishing off the screen.
  const dayRows = useMemo(() => entries?.filter((e) => e.kind !== 'habit') ?? [], [entries])

  // ── the fortnight behind the counts and the suggestions ──────────────────
  //
  // ONE read, feeding two things. `api.days` answers a whole span in a single
  // call — a `DayPlan[]` holding the days in it that have a plan, which the two
  // memos below key by day for themselves — so the habit counts and the "still
  // open from a recent plan" group share it rather than issuing a range call
  // each. And it is `api.days`, never `openDay`, because reading a fortnight
  // must not OPEN the fourteen days behind the one on screen — the window is
  // `[day - 14, day + 1)`, fifteen days, of which fourteen are days the owner is
  // not looking at. Opening them would fill the record with plans they never
  // made, each frozen at whatever happened to be due at prefetch time. Same
  // rule as the read above, from the other direction.
  //
  // `[day - LOOKBACK_DAYS, day + 1)`, `to` being EXCLUSIVE. It is anchored to
  // the day ON SCREEN rather than to today so that stepping back re-answers the
  // habit counts for the week that day fell in — a look-back at last Tuesday
  // showing this week's counts would be reporting a week that had not started
  // yet. The window is a superset of that week by construction: Monday is at
  // most six days before any day, and LOOKBACK_DAYS is 14.
  //
  // Stored WITH the day it was fetched for, for the same reason `plan` carries
  // its own `day`: both ends move at a rollover and at every step of the
  // picker, and until the refetch lands the plans in hand are the ones the
  // previous range answered. See the guard in `recentPlans`.
  // Declared ABOVE the state they seed, which is the only reason they moved:
  // all three are pure functions of `day` and nothing else reads them earlier.
  const weekStart = weekStartOf(day)
  const rangeFrom = ymd(addDays(new Date(`${day}T00:00`), -LOOKBACK_DAYS))
  const rangeTo = ymd(addDays(new Date(`${day}T00:00`), 1))
  // Seeded from the mirror for the same reason the plan above is, and stamped
  // with the day it answers exactly as a fetched one is — a cached window is
  // still a window, and the guard in `recentPlans` has to hold for it too. On
  // the frame this runs `day` is `today`, so the ends match the ones the mirror
  // was written under.
  const [recent, setRecent] = useState<{ day: string; plans: DayPlan[] } | null>(() => {
    const rows = readCachedDayRange(rangeFrom, rangeTo)
    return rows ? { day, plans: rows } : null
  })
  const recentToken = useRef(0)

  useEffect(() => {
    const mine = ++recentToken.current
    void guard(async () => {
      const ps = await api.days(rangeFrom, rangeTo)
      if (mine !== recentToken.current) return
      if (Array.isArray(ps)) setRecent({ day, plans: ps })
    })
    // `day` alongside the two ends it derives: both are pure functions of it,
    // so naming it adds no re-runs, and it is what the response is stamped with.
  }, [day, rangeFrom, rangeTo, rev, guard])

  // …and mirrored back, on the same trailing edge and under the same rule as
  // the day itself: only while the view is on TODAY, because the window is
  // anchored to the day on screen and one written for a look-back would evict
  // the only window a mount can read.
  useEffect(() => {
    if (!recent || recent.day !== day || day !== today) return
    const t = setTimeout(() => cacheDayRange(rangeFrom, rangeTo, recent.plans), CACHE_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [recent, day, today, rangeFrom, rangeTo])

  /** The fetched span, or nothing while it is known to be stale.
   *
   *  Keyed to the day it was fetched for, exactly as `entries` is: a step of the
   *  picker (or a rollover) moves BOTH ends of the range, and until the refetch
   *  lands the plans in hand answer the PREVIOUS window. Counting them under
   *  this day's headings would say "5 of 7 this week" about a different week,
   *  which is the staleness this file refuses everywhere else — showing nothing
   *  is the honest answer while the surface does not know yet. */
  const recentPlans = useMemo(
    () => (recent && recent.day === day ? recent.plans : []), [recent, day])

  /**
   * Per habit id, this week so far: how many occurrences were ticked, out of how
   * many EXIST.
   *
   * The denominator is what makes the number honest, and it is deliberately not
   * the count of scheduled weekdays. An absent row conflates three different
   * facts: the habit was not scheduled that day, it was scheduled and missed, or
   * THE APP WAS NEVER OPENED THAT DAY. Only the middle one is a miss, and after
   * the fact nothing can tell them apart — a day nobody opened has no plan, so
   * it has no rows either way, and the habit that "should" have run on it never
   * did. Counting scheduled weekdays would quietly charge the owner for the days
   * they were on holiday, ill, or simply not at a screen, which is the single
   * most demoralising thing a habit tracker does.
   *
   * So the count is over the occurrences that exist: of the days this habit
   * actually came up, how many were done.
   *
   * Dropped occurrences leave BOTH halves. "I decided not to do this" is a
   * decision the day recorded, not a failure to act on one, so counting it as a
   * miss would be the same lie pointing the other way.
   */
  const habitWeek = useMemo(() => {
    const byDay = new Map<string, DayEntry[]>()
    for (const p of recentPlans) {
      // THIS WEEK, out of a fortnight. The one range read behind this screen is
      // wider than the count is, so the days before Monday are dropped here
      // rather than at the fetch — without this line "3 of 5 this week" would
      // quietly be counting a fortnight, and the number would jump every Monday
      // for no reason the owner could see. Nothing bounds the top end because
      // nothing needs to: the range itself ends the day after the day on screen,
      // which is where the week being counted ends too.
      if (!p || p.day < weekStart) continue
      if (Array.isArray(p.entries)) byDay.set(p.day, p.entries)
    }
    // Today comes from the plan in hand, REPLACING the range read's copy of it
    // rather than adding to it — the range covers today too, and counting the
    // day twice would double every habit's numbers. The local copy is the one
    // that has already absorbed the optimistic tick, so the count moves on the
    // click rather than a round trip later.
    if (entries) byDay.set(day, entries)
    const out = new Map<string, { done: number; total: number }>()
    for (const rows of byDay.values()) {
      for (const e of rows) {
        if (e.kind !== 'habit' || !e.habit_id || e.dropped_at) continue
        const c = out.get(e.habit_id) ?? { done: 0, total: 0 }
        c.total += 1
        if (e.done_at) c.done += 1
        out.set(e.habit_id, c)
      }
    }
    return out
  }, [recentPlans, weekStart, entries, day])

  /** Replace one entry of the plan in hand, by id.
   *
   *  A no-op once the plan has been replaced by another day's — entry ids are
   *  uuid4 hex, so a stale write cannot collide with a row of the new day. */
  const patchEntry = useCallback((entryId: string, patch: Partial<DayEntry>) => {
    setPlan((p) => (p
      ? { ...p, entries: p.entries.map((e) => (e.entry_id === entryId ? { ...e, ...patch } : e)) }
      : p))
  }, [])

  /**
   * Swap the server's row in for the one painted optimistically under `localId`.
   *
   * The add is idempotent three ways — same entry_id, same task, or same note
   * text on the same day — so the row that comes back may be one that was
   * ALREADY on the day under a DIFFERENT entry_id. Collapsing both onto the DTO
   * rather than mapping each to it is what stops two identical rows fighting
   * over one React key. Appending is gated on the day still matching, so a
   * response that lands after midnight cannot resurrect an entry onto a day it
   * does not belong to.
   */
  const settleEntry = useCallback((localId: string, dto: DayEntry) => {
    setPlan((p) => {
      if (!p) return p
      let placed = false
      const next: DayEntry[] = []
      for (const e of p.entries) {
        if (e.entry_id !== localId && e.entry_id !== dto.entry_id) { next.push(e); continue }
        if (placed) continue
        placed = true
        next.push(dto)
      }
      if (!placed && p.day === dto.day) next.push(dto)
      return { ...p, entries: next }
    })
  }, [])

  const dropLocal = useCallback((entryId: string) => {
    setPlan((p) => (p ? { ...p, entries: p.entries.filter((e) => e.entry_id !== entryId) } : p))
  }, [])

  /** Tick or un-tick an entry whose doneness lives ON THE ENTRY: a note, or a
   *  habit occurrence. A task row never reaches this — see the header.
   *
   *  Named for the property rather than for the kind because there are two
   *  kinds in it now. The backend permits `done` on both for the same reason it
   *  refuses it on a task: a note and a habit occurrence exist nowhere but in
   *  the day, so the day is the only place their doneness can live. (Ticking a
   *  habit occurrence says the owner did it TODAY. It says nothing about the
   *  rule, which is not a thing that can be completed.) */
  const toggleEntry = useCallback(async (e: DayEntry) => {
    const done = !e.done_at
    token.current += 1
    // A local stand-in for the instant between the click and the reply; the
    // server's own stamp is what the row settles on below.
    patchEntry(e.entry_id, { done_at: done ? new Date().toISOString() : null })
    const dto = await guard(() => api.patchDayEntry(day, e.entry_id, { done }))
    // THE STAMP ONLY, on both arms. `patchDayEntry` answers with the whole row,
    // and settling all of it meant this reply carried an opinion about every
    // other field — so a tick and an estimate typed a moment apart on the same
    // row raced, and whichever replied last wrote its own idea of the other's
    // field back. Each writer settling exactly what it asked for is what makes
    // that impossible rather than merely unlikely. On failure, the old stamp,
    // rather than leaving the UI claiming a tick that never landed — `guard`
    // has already raised the toast.
    patchEntry(e.entry_id, { done_at: dto ? dto.done_at : e.done_at })
  }, [day, guard, patchEntry])

  /**
   * Set or clear how long an entry is expected to take. Every kind takes one:
   * a task, a note and a habit occurrence are all things that cost time.
   *
   * `null` clears, and the wire spells that -1 — an int has no spare falsy value
   * to mean "unset", because 0 is a real estimate. The translation happens here,
   * at the one call site, rather than leaking the sentinel into the component
   * that collects the number.
   */
  const setEstimate = useCallback(async (e: DayEntry, minutes: number | null) => {
    token.current += 1
    patchEntry(e.entry_id, { estimate_minutes: minutes })
    const dto = await guard(() => api.patchDayEntry(day, e.entry_id, {
      estimate_minutes: minutes ?? -1,
    }))
    // The estimate only — see `toggleEntry`. Back to the old value on failure
    // rather than leaving a number on screen that the day does not hold;
    // `guard` has already raised the toast.
    patchEntry(e.entry_id, {
      estimate_minutes: dto ? dto.estimate_minutes : e.estimate_minutes,
    })
  }, [day, guard, patchEntry])

  /** Replace part of the plan in hand, while it is still the day named.
   *
   *  The `patchEntry` of the day itself, and it exists for the same reason:
   *  every writer below carries its own day key (`on`) rather than reading
   *  `day` after an await, so a reply that lands after a rollover — or after a
   *  step of the picker — cannot write itself onto whatever day is now on
   *  screen. A no-op when the day has moved. */
  const patchPlan = useCallback((on: string, patch: Partial<DayPlan>) => {
    setPlan((p) => (p && p.day === on ? { ...p, ...patch } : p))
  }, [])

  /** The plan as it stands for `on`, or null if that is not the day in hand.
   *  What the rollbacks below restore to, read off the ref so a writer does not
   *  have to name `plan` as a dependency and be rebuilt on every paint. */
  const planFor = useCallback(
    (on: string) => (planRef.current?.day === on ? planRef.current : null), [])

  /** Say how long today is. `null` clears, spelled -1 on the wire — the same
   *  sentinel an estimate uses, and needed for the same reason: 0 is a real
   *  capacity ("not working today").
   *
   *  Settles the two capacity fields and NOTHING ELSE, which is the rule every
   *  writer on this screen now follows. `PATCH /api/day` answers with the whole
   *  plan, and taking it wholesale meant one write's reply could undo another's
   *  optimistic paint: the shutdown ritual commits its reflection on blur and
   *  the shutdown on the click that follows, so two PATCHes on one day are in
   *  flight together by design, and whichever answered last wrote its own idea
   *  of every field over the other's. Settling only what this call asked for
   *  makes that impossible rather than unlikely. */
  const setCapacity = useCallback(async (minutes: number | null) => {
    token.current += 1
    const on = day
    const was = planFor(on)
    patchPlan(on, { capacity_minutes: minutes, capacity: minutes })
    const dto = await guard(
      () => api.patchDay(on, { capacity_minutes: minutes ?? -1 }))
    // The RESOLVED capacity is the server's to compute — clearing this day's
    // statement falls back to the weekday default, then the account's, then
    // nothing — so the optimistic paint is provisional and the reply settles it.
    if (dto) patchPlan(on, { capacity_minutes: dto.capacity_minutes, capacity: dto.capacity })
    else if (was) patchPlan(on, { capacity_minutes: was.capacity_minutes, capacity: was.capacity })
  }, [day, guard, patchPlan, planFor])

  /** Mark the day begun. The ritual's last act, and the moment the
   *  overcommitment is stated — it records a decision rather than enforcing
   *  one, so nothing about the day changes except that it now knows it started.
   *
   *  OPTIMISTIC, and the ritual closes on the click rather than a round trip
   *  later. It was the one write on this screen that still made the owner watch
   *  a request finish — with the overlay standing over the day the whole time,
   *  which is the worst place in the app to spend a round trip, because it is
   *  the last press of a three-step flow and it looks like the flow has hung.
   *  A failure puts the stamp back and `guard` has already raised the toast, so
   *  the band returns and the day is honestly un-begun again. */
  const commitDay = useCallback(async () => {
    token.current += 1
    const on = day
    const was = planFor(on)
    patchPlan(on, { committed_at: was?.committed_at ?? new Date().toISOString() })
    setRitual(false)
    const dto = await guard(() => api.patchDay(on, { committed: true }))
    if (dto) patchPlan(on, { committed_at: dto.committed_at })
    else if (was) patchPlan(on, { committed_at: was.committed_at })
  }, [day, guard, patchPlan, planFor])

  /**
   * Write the day's reflection.
   *
   * Trimmed here as well as server-side, so what the field shows back and what
   * the day holds are the same string — an untrimmed local copy would leave the
   * textarea claiming a trailing newline the day does not have.
   *
   * NOT optimistic in the way a tick is. It is written on blur, from prose
   * nobody is racing on, and the round trip is invisible; painting it early
   * would only buy the chance to paint it wrong.
   */
  const setReflection = useCallback(async (text: string) => {
    token.current += 1
    const on = day
    // "" CLEARS rather than storing an empty string, which is `set_day_ritual`'s
    // rule and the reason "nothing written" has one representation. So an
    // emptied box is a real edit and has to be sent, not skipped as falsy.
    const dto = await guard(() => api.patchDay(on, { reflection: text.trim() }))
    // The reflection ALONE. This is the write the field-targeted settle exists
    // for: it goes out on blur, and the press that blurs the textarea is
    // usually the "Shut down" button itself, so its reply and the shutdown's
    // are in flight together on the same day.
    if (dto) patchPlan(on, { reflection: dto.reflection })
  }, [day, guard, patchPlan])

  /** Close the day. The shutdown ritual's last act, and the mirror of
   *  `commitDay`: it stamps, and nothing else about the day changes. Unfinished
   *  work has already been decided about by the step before it — or left alone,
   *  which the automatic carry still answers.
   *
   *  Optimistic, and the overlay closes on the click, for the reason
   *  `commitDay` gives. The reflection is unaffected: `ReflectStep` commits on
   *  unmount as well as on blur, so closing early still saves what was typed,
   *  and the two replies can no longer overwrite each other now that each
   *  settles only its own field. */
  const shutdownDay = useCallback(async () => {
    token.current += 1
    const on = day
    const was = planFor(on)
    patchPlan(on, { shutdown_at: was?.shutdown_at ?? new Date().toISOString() })
    setShutdown(false)
    const dto = await guard(() => api.patchDay(on, { shutdown: true }))
    if (dto) patchPlan(on, { shutdown_at: dto.shutdown_at })
    else if (was) patchPlan(on, { shutdown_at: was.shutdown_at })
  }, [day, guard, patchPlan, planFor])

  /**
   * Send one entry to another day.
   *
   * A CREATE, not a move: the server writes a row on the target day and stamps
   * this one with where it went, because the day that planned the work is still
   * the day that planned it. Nothing here reaches the target day's state — it
   * is not the day on screen — so the only local change is the stamp.
   *
   * That stamp is what makes the row leave the list: `entries` filters
   * `rolled_to` out, exactly as it filters a dropped row out, so deciding about
   * something removes it from the day's total as well as from the shutdown's
   * list of what still follows you.
   */
  const rollEntry = useCallback(async (e: DayEntry, to: string) => {
    token.current += 1
    patchEntry(e.entry_id, { rolled_to: to })
    const dto = await guard(() => api.rollDayEntry(day, e.entry_id, to))
    // The destination only — see `toggleEntry`. Back to where it was on failure
    // rather than leaving the row hidden from a day it is still on; `guard` has
    // already raised the toast.
    patchEntry(e.entry_id, { rolled_to: dto ? dto.rolled_to : e.rolled_to })
  }, [day, guard, patchEntry])

  /** Take a row off the day. Every row can be dropped, task or note alike. */
  const drop = useCallback(async (e: DayEntry) => {
    token.current += 1
    dropLocal(e.entry_id)
    const dto = await guard(() => api.patchDayEntry(day, e.entry_id, { dropped: true }))
    // A failed drop has to come BACK, in its old place — the sort key is the
    // row's own (position, created_at, entry_id), so restoring the entry
    // unchanged puts it exactly where it was.
    if (!dto) setPlan((p) => (p && p.day === e.day ? { ...p, entries: [...p.entries, e] } : p))
  }, [day, guard, dropLocal])

  // ── arranging the day ────────────────────────────────────────────────────
  //
  // The verb this file's header has always promised — "the day is something the
  // owner arranges: adding to it, ticking it off, dropping what is not going to
  // happen" — and the only one of the four that was never implemented. The
  // column has been there since the first commit: `day_plan.position` is a REAL,
  // the server orders on (position IS NULL, position, created_at, entry_id), it
  // gives every snapshot row a position and every add `max + 1`, and
  // `PATCH .../entries/{id}` has always taken one.
  //
  // Because those positions are FRACTIONAL, a drop is ONE write: the row being
  // moved takes a value between its new neighbours and nothing else has to
  // change. A whole-list renumber (which is what the Tasks pane does, for a
  // different reason — its order is global across lists and lives in the
  // sidecar) would be N writes for a gesture that moved one row.
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)

  /**
   * Move `id` to where `target` currently sits, and write the one position that
   * changes.
   *
   * Both ends are looked up in `dayRows` — the array actually on screen, minus
   * the row in flight — so "between its new neighbours" means between the rows
   * the owner can see, not between whatever the unfiltered plan happens to
   * hold. Habits are not in it (they paint above, in their own group) and
   * dropped rows are not in it, which is what stops a drop landing a row into a
   * gap that is invisible.
   */
  const moveRow = useCallback(async (id: string, target: string) => {
    if (id === target) return
    const rows = dayRows
    const from = rows.findIndex((r) => r.entry_id === id)
    const to = rows.findIndex((r) => r.entry_id === target)
    if (from < 0 || to < 0) return
    const without = rows.filter((r) => r.entry_id !== id)
    // Dragging DOWN lands the row AFTER the target; dragging UP lands it
    // BEFORE. That is what a drop on a row means in every other list in this
    // app, and downward it is the only reading under which the gesture moves
    // anything — inserting before the target would put the row back exactly
    // where it started.
    //
    // Both directions come out at the SAME pair of neighbours in `without`,
    // which is why there is no branch here. Removing the dragged row shifts
    // every index after it down by one: dragging down, the target lands at
    // `to - 1` and "after it" is index `to`; dragging up, the target is still
    // at `to` and "before it" is also index `to`. So the new row goes at index
    // `to` either way, between `without[to - 1]` and `without[to]`.
    const before = without[to - 1]
    const after = without[to]
    const lo = before?.position ?? null
    const hi = after?.position ?? null
    // A fractional index. `lo == null` is the top of the list and `hi == null`
    // the bottom; both null cannot happen, because a list with one row has
    // nowhere to drop.
    const next = lo == null ? (hi ?? 1) - 1
      : hi == null ? lo + 1
        : (lo + hi) / 2
    const old = rows[from].position
    token.current += 1
    patchEntry(id, { position: next })
    const dto = await guard(() => api.patchDayEntry(day, id, { position: next }))
    // The position only — see `toggleEntry`. Back to the exact key it had on
    // failure, so a rejected move puts the row where it was rather than
    // somewhere approximate.
    patchEntry(id, { position: dto ? dto.position : old })
  }, [dayRows, day, guard, patchEntry])

  /**
   * Paint a task row on `on` and hand back the id it was painted under — which
   * is also the id the add will carry, so the server stores the row the owner
   * is already looking at.
   *
   * `on` is passed rather than read from `day` inside the awaits, here and in
   * every writer below it: a line typed at 23:59:59 belongs to the day it was
   * typed on, and the rollover timer may fire while this is in flight.
   *
   * SPLIT FROM THE SEND, and that split is the whole of the add box's fix. A
   * suggestion's `+` names a task that already exists, so paint-then-send was
   * one step; a line typed into the box has to AUTHOR the task first, and that
   * create is its own round trip to CalDAV. `addParsedTask` used to await it
   * before anything was painted, so the commonest gesture on the tab — type a
   * line, press Enter — cleared the box and then showed nothing at all for two
   * sequential round trips. The row can be painted immediately because the uid
   * the create will land under is known up front (`uidFor`), which is the same
   * fact `data.tsx` uses to paint its own stand-in.
   */
  const paintTask = useCallback((on: string, list: string, uid: string): string => {
    token.current += 1
    const entry_id = clientId()
    // Carries the id the server will store it under, so a retry lands on this
    // row rather than beside it. `position` is null because the server assigns
    // it (max + 1) — and `orderEntries` sorts an unpositioned row to the END,
    // which is exactly where the server is about to put it, so the row does not
    // move when the DTO arrives.
    const optimistic: DayEntry = {
      entry_id, day: on, kind: 'task', list, uid, title: null,
      // `habit_id` is null on everything a client can add: an occurrence is
      // minted by its rule when a day is opened, never posted from here.
      source: 'user', position: null, done_at: null, dropped_at: null, habit_id: null,
      // Null, even for a task the account has estimated before. The remembered
      // estimate lives in the sidecar, which only the server has read — so this
      // row paints unestimated for the length of one round trip and takes the
      // real answer from the DTO. Guessing here would mean guessing wrong
      // whenever the sidecar disagreed, and a number that flickers to a
      // different number is worse than one that arrives a beat late.
      estimate_minutes: null,
      // A row that has just been added has not been moved anywhere.
      rolled_to: null,
      // …nor worked, nor told whether to stop at an estimate it does not have.
      worked_seconds: null, capped: null,
      created_at: new Date().toISOString(),
    }
    setPlan((p) => (p && p.day === on
      // `planned` too — but note what that does and does not mean. Adding a row
      // makes the day report planned, because a plan holding a row while still
      // claiming planned=false would contradict itself. It does NOT open the
      // day: the snapshot marker stays unset, so a later open still derives the
      // due-today, overdue and carried rows around what was hand-added.
      ? { ...p, planned: true, entries: [...p.entries, optimistic] }
      : p))
    return entry_id
  }, [])

  /** Send the add for a row already painted under `entry_id`, and settle it.
   *
   *  Takes (list, uid) rather than the row it painted, because the task the
   *  create ANSWERS with is the authority on both: a replayed create is
   *  answered by the resource already written, and settling by `entry_id`
   *  repairs the row either way. */
  const sendTask = useCallback(async (
    on: string, entry_id: string, list: string, uid: string,
  ): Promise<boolean> => {
    // Again here, not only at the paint: a refetch may have started while the
    // create was in flight, and a response whose snapshot predates this row
    // must not land on top of it. Same double bump, same reason, as
    // `data.tsx::create`.
    token.current += 1
    const dto = await guard(
      () => api.addDayEntry(on, { entry_id, kind: 'task', list, uid }))
    if (!dto) { dropLocal(entry_id); return false }
    settleEntry(entry_id, dto)
    return true
  }, [guard, settleEntry, dropLocal])

  /** Put a task that already exists on `on`. Returns whether it landed.
   *
   *  The two halves back to back, which is all a suggestion's `+` needs: there
   *  is no VTODO to author first, so nothing sits between the paint and the
   *  send. The add box is the caller that needs them apart. */
  const addTask = useCallback((on: string, t: Task): Promise<boolean> =>
    sendTask(on, paintTask(on, t.list, t.uid), t.list, t.uid),
  [paintTask, sendTask])

  /** Put a note on `on`. Same optimistic shape as `addTask`. */
  const addNote = useCallback(async (on: string, title: string): Promise<boolean> => {
    token.current += 1
    const entry_id = clientId()
    const optimistic: DayEntry = {
      entry_id, day: on, kind: 'note', list: null, uid: null, title,
      source: 'user', position: null, done_at: null, dropped_at: null, habit_id: null,
      // A note has nothing to remember an estimate for it, so this one is not
      // even provisional — it starts unestimated and the ritual asks.
      estimate_minutes: null,
      // A row that has just been added has not been moved anywhere.
      rolled_to: null,
      // …nor worked, nor told whether to stop at an estimate it does not have.
      worked_seconds: null, capped: null,
      created_at: new Date().toISOString(),
    }
    setPlan((p) => (p && p.day === on
      ? { ...p, planned: true, entries: [...p.entries, optimistic] }
      : p))
    const dto = await guard(() => api.addDayEntry(on, { entry_id, kind: 'note', title }))
    if (!dto) { dropLocal(entry_id); return false }
    settleEntry(entry_id, dto)
    return true
  }, [guard, settleEntry, dropLocal])

  // ── the add box ──────────────────────────────────────────────────────────
  const [text, setText] = useState('')
  /**
   * What the owner has said this line should BECOME, or null to let the reading
   * decide. This replaces a boolean `declined`, and the widening is the point.
   *
   * `declined` could only ever say "not the thing you read", which was enough
   * when the only two outcomes were "task, because a date was found" and "note,
   * because one was not". But that made the box a coin the parser tossed: a
   * line with a time silently authored a REAL VTODO on a real list, and a line
   * without one silently authored a note that exists nowhere but in this day
   * and reaches no other client on the account. Those are very different
   * things to have done by accident, and nothing on the screen named either.
   *
   * So the override is now two-way — "make this a task" is as sayable as "make
   * this a note" — and the chip below states the answer either way.
   *
   * IT DOES NOT RESET ON A KEYSTROKE, and that is a deliberate departure from
   * `declined`, which did. `declined` was about a PARSE, and one more character
   * can withdraw a parse, so the thing that had been declined stopped existing.
   * A choice of kind is about INTENT: it survives typing the rest of the line,
   * and clearing it under the owner's fingers would be a fresh instance of
   * exactly the silent surprise this whole change removes. It clears on commit.
   */
  const [pinned, setPinned] = useState<'task' | 'note' | null>(null)
  // Re-read on every keystroke, which is what makes the chip a live preview
  // rather than something the user has to ask for. `day` is in the deps for the
  // same reason it is in the window's: `parseEntry` resolves "tomorrow" and
  // "friday" against the clock it is handed, so a line left sitting in the box
  // across midnight has to be read again or the chip would promise a date one
  // day behind the one the entry would actually get.
  // The GRAMMAR follows the language setting, not just the words around the box.
  // A German account typing "Rechnung Freitag" is typing a date, and a parser
  // that only ever knew English would leave it whole while the chip beneath
  // promised it a note. `lang` in the dependency list because switching the
  // setting has to re-read the line already typed.
  const parsed = useMemo(() => parseEntry(text, new Date(), lang), [text, day, lang])
  const reads = !!(parsed.dueDate || parsed.dueTime)

  /**
   * The collections a task can actually be created in.
   *
   * `useTaskData().lists` is every collection on the account — `GET /api/lists`
   * answers calendars alongside task lists and flags which is which — and
   * NOTHING in this app has ever read that flag outside a test fixture. So the
   * old `lists[0]` was "whatever happens to sit first in the sidebar", which on
   * an account whose first collection is a calendar meant the box authored its
   * tasks into a calendar. Filtering here is what makes the picker below honest
   * and fixes the automatic path at the same time.
   */
  const taskLists = useMemo(() => lists.filter((l) => l.is_task_list), [lists])
  const [listId, setListId] = useState('')
  // Keep the target valid as the visible set changes — a list that has been
  // deleted, hidden or was never a task list must not stay selected. Same shape
  // and same reason as the Tasks pane's quick add.
  useEffect(() => {
    if (!taskLists.some((l) => l.id === listId)) setListId(taskLists[0]?.id ?? '')
  }, [taskLists, listId])

  /**
   * What Enter will actually create — the one expression the chip, the swap
   * control, the submit button's name and `commit` all read.
   *
   * The automatic arm is byte-for-byte the rule this box has always followed:
   * a reading plus somewhere to put it makes a task, everything else makes a
   * note. What changed is that it is now WRITTEN DOWN in one place instead of
   * being spelled out again at the branch, and that a pin can override it.
   *
   * `listId` is part of it rather than checked later, because "there is nowhere
   * to put a task" has to resolve to `note` BEFORE anything paints: a chip
   * promising a task on an account with no task lists would be a promise the
   * commit could not keep.
   */
  const willBe: 'task' | 'note' = listId
    ? (pinned ?? (reads ? 'task' : 'note'))
    : 'note'

  // What a FAILED line left behind, so pressing Enter again finishes the write
  // instead of starting a second one. `addParsedTask` is a compound write —
  // author the task, then point the day at it — with no idempotency across the
  // pair, so a failure of the second half replayed the first and authored a
  // duplicate VTODO on the CalDAV list, one of which was on no day at all.
  //
  // Keyed on the LINE, because that is what the box puts back and therefore what
  // the user retries. A different line is a different task and mints its own id.
  const retry = useRef<{ line: string; cid: string; task?: Task } | null>(null)

  const commit = async () => {
    const raw = text.trim()
    if (!raw) return
    // Cleared first: the box has to be ready for the next line before the round
    // trip finishes, which is the whole bargain of a frictionless add. The text
    // goes back on failure (as the dashboard's quick add does), so a rejected
    // line is never simply lost.
    setText('')
    setPinned(null)
    const on = day
    // A task's title is the parser's — the recognised phrase has been lifted
    // out of it and into the due date. A NOTE's is the LITERAL line, always:
    // the parser DELETES what it recognised, and a note that quietly lost its
    // "at 7" is the silent loss daytext.ts's own header is written to avoid.
    // That rule held for the old decline path and it has to hold for a pinned
    // note as well, which is why it is keyed on `willBe` and not on `reads`.
    const ok = willBe === 'task'
      ? await addParsedTask(on, listId, parsed, reads, raw)
      : await addNote(on, raw)
    if (!ok) setText(raw)
    else retry.current = null
  }

  /**
   * Author a real task for this line, and point the day at it.
   *
   * `dated` is whether the parser actually found something. It decides whether
   * a DUE is written at all, and the distinction only became reachable when the
   * box grew a way to say "make this a task" about a line with no date in it.
   * `dueFromParse` falls back to the day being planned, which is right when a
   * time was given ("gym at 7" means 07:00 today) and wrong here: it would
   * stamp a deadline of today onto a VTODO that every other client on the
   * account will then show as due, off the back of the owner asking only for it
   * to be a task. Being on today's plan is the day entry's job; a due date is a
   * claim about the task itself, and this is not the place to invent one.
   */
  const addParsedTask = async (
    on: string, list: string, p: ParsedEntry, dated: boolean, raw: string,
  ): Promise<boolean> => {
    // The SAME line retried keeps its client_id, so the create is idempotent:
    // the backend derives the VTODO's uid from it and answers a replay with the
    // resource already written. And if the task itself landed last time, it is
    // held here and the create is skipped outright — the retry re-sends only the
    // half that failed.
    const prior = retry.current?.line === raw ? retry.current : null
    const cid = prior?.cid ?? clientId()
    // PAINTED FIRST, before the task exists anywhere. `uidFor(cid)` is the uid
    // the create is contractually going to land under — `engine.create_task`
    // builds it from the slug this request sends — and it is the same uid
    // `data.tsx::create` gives the stand-in it paints into `tasks` on the very
    // same tick. So `taskFor` resolves this row to that stand-in immediately
    // and it reads its title, its list colour and its checkbox from the first
    // frame, instead of the box clearing to nothing for two round trips.
    //
    // On a retry whose task already landed, the real uid is in hand and is
    // better than the derived one — they agree, but only one of them is a fact.
    const entry_id = paintTask(on, prior?.task?.list ?? list, prior?.task?.uid ?? uidFor(cid))
    const t = prior?.task ?? await create(list, {
      // TRIMMED at the call site, not in `parseEntry`. When the parser
      // recognises nothing it returns `summary: text` byte for byte — its
      // documented "'' in, '' out" rule, which `daytext.test.ts` pins — so the
      // pinned-task path was the one branch sending raw input, while the note
      // path beside it sends `text.trim()` and the parsed path sends `without()`'s
      // trimmed remnant. A leading space is invisible in the chip preview and
      // real in the VTODO: `sortTasks` orders by summary, so the task sorts ahead
      // of everything, on every client on the account.
      summary: p.summary.trim() || raw,
      // Omitted rather than sent empty — `CreateTaskBody`'s optional keys mean
      // "leave unset", and the backend only copies non-None fields onto the
      // VTODO.
      ...(dated ? { due: dueFromParse(p, on) } : {}),
    }, undefined, cid)
    if (!t) {
      // `create` has already raised the toast. The row painted for it comes off
      // the day — there is no task for it to point at — and the id is
      // remembered so the retry is the same create rather than a new one.
      dropLocal(entry_id)
      retry.current = { line: raw, cid }
      return false
    }
    // The task's OWN (list, uid) on the wire, never the pair painted above: a
    // create answered from an existing resource is the authority on both, and
    // `settleEntry` repairs the painted row by `entry_id` whatever they say.
    if (await sendTask(on, entry_id, t.list, t.uid)) return true
    retry.current = { line: raw, cid, task: t }
    return false
  }

  // ── suggestions: tasks ───────────────────────────────────────────────────
  // (list, uid) is a task's identity everywhere in this app — a UID is unique
  // per COLLECTION, not per account (see order.ts and the backend's invariant
  // #4) — so a day entry is joined back to its task on BOTH halves. Matching on
  // the uid alone would tick the wrong copy of a task that has been copied
  // between lists in Tasks.org or Thunderbird.
  const taskFor = useCallback(
    (e: DayEntry) => (e.uid ? tasks.find((t) => t.uid === e.uid && t.list === e.list) : undefined),
    [tasks])

  /** The tasks a set of day rows names, keyed the way `sortTasks` keys a task.
   *
   *  Built by resolving each entry to its task rather than by rebuilding
   *  `taskKey`'s string from (list, uid) here, so this and the ordering can
   *  never drift apart.
   *
   *  The `kind !== 'task'` skip already covered habit occurrences the day `kind`
   *  widened, and covers them for the right reason rather than by luck: a habit
   *  carries no (list, uid) at all, so it names no task and can exclude none
   *  from anything. Spelling it `=== 'note'` would have been the same behaviour
   *  written as a claim that stops being true on the next kind. */
  const keysOf = useCallback((rows: DayEntry[]) => {
    const s = new Set<string>()
    for (const e of rows) {
      if (e.kind !== 'task') continue
      const t = taskFor(e)
      if (t) s.add(taskKey(t))
    }
    return s
  }, [taskFor])

  // What the day already holds, so the suggestion lists cannot offer something
  // that is already on screen above them.
  //
  // Dropped rows are NOT in it, and that is deliberate: having dropped
  // something this morning, choosing it again this afternoon has to work — the
  // server's add is idempotent EXCEPT over dropped rows for exactly that
  // reason.
  //
  // MOVED rows are, which is why this reads `allEntries` and filters rather
  // than reading `entries`. The two stamps mean different things and this is the
  // one place the difference shows: "I decided against this" leaves the task
  // undecided-about and it is right to offer it back, while "this is happening
  // on Thursday" is a decision WITH A DESTINATION — the work already has a row
  // on another day, and re-offering it under "Due today" would contradict the
  // answer given ten seconds earlier in the shutdown.
  const onDay = useMemo(
    () => keysOf((allEntries ?? []).filter((e) => !e.dropped_at)), [allEntries, keysOf])

  // What the day held at all, dropped rows included. The look-back's off-plan
  // list is what needs this rather than `onDay`: a task that was planned and
  // then declined is already painted under "Dropped", and listing it again as
  // something finished off-plan would show one task twice under two headings
  // that contradict each other.
  const everOnDay = useMemo(() => keysOf(allEntries ?? []), [allEntries, keysOf])

  /**
   * The tasks the owner CHOSE on an earlier day in the window and never
   * finished, as a key set.
   *
   * This is the gap the carry-over deliberately leaves, and it is emphatically
   * NOT a second copy of it. `service._carry_into` moves source="user" rows
   * forward exactly ONCE — "a task the owner chose on Monday and then ignored
   * on Tuesday has been declined, and following them all week is how a plan
   * turns into a list nobody reads" — so from Wednesday on, that task is gone
   * from every day and from every suggestion here too, since it is (say)
   * undated and so appears in none of the three dated groups. It has not been
   * finished, dropped or reconsidered; it has simply stopped being visible.
   * Offering it back as a SUGGESTION rather than putting it on the day is the
   * whole distinction: the carry is a decision made for the owner, this is a
   * question put to them.
   *
   * `p.day >= day` skips the day on screen, because it is not "a recent plan",
   * it is the plan. Its own rows are kept out of every group by `onDay` once
   * the open has landed — but the range read covers the day on screen too and
   * can land FIRST, and without this skip a task the owner can already see on
   * the day would be offered back to them for as long as the open took.
   *
   * Done and dropped rows are excluded here; whether the TASK is still open is
   * settled by `open` below, which every group is drawn from. Notes and habit
   * occurrences fall out through `keysOf`, which names only task rows — a note
   * is source="user" too, and it exists nowhere but in the day it was written
   * on, so there is nothing to offer.
   */
  const recentlyChosen = useMemo(() => {
    const s = new Set<string>()
    for (const p of recentPlans) {
      if (!p || !Array.isArray(p.entries) || p.day >= day) continue
      // `!e.rolled_to` as well as `!e.dropped_at`, and it is the same rule
      // `onDay` states one screen down: a row with a DESTINATION has been
      // decided about, and the work already has a row on the day it went to.
      // Without this, something moved to Thursday came back on Tuesday under
      // "you did not finish these last time" — the plan offering back the
      // answer the owner gave it forty seconds earlier in the shutdown.
      //
      // This was the one reader of `rolled_to` the column did not reach.
      const chosen = p.entries.filter(
        (e) => e.source === 'user' && !e.done_at && !e.dropped_at && !e.rolled_to)
      for (const k of keysOf(chosen)) s.add(k)
    }
    return s
  }, [recentPlans, day, keysOf])

  const suggestions = useMemo(() => {
    // A finished day is a record, and a record does not take additions. The
    // whole panel is gated here rather than at the render so nothing downstream
    // has to remember: every group below ends in an "add to today" button, and
    // there is no such thing as adding to last Tuesday.
    if (!isToday) return []
    // Top-level only, matching the snapshot the backend builds: a checklist
    // item is not a separate thing to plan, and admitting subtasks would let
    // one parent task drag twenty rows onto the day (service.py's
    // `_snapshot_for` skips anything with a `related_parent` for that reason).
    const open = tasks.filter((t) => !t.parent && !t.completed && !t.cancelled)
    const free = open.filter((t) => !onDay.has(taskKey(t)))
    // Measured from the day on screen, not from `new Date()`: after a rollover
    // the horizon has to move with the day, and the two are the same value on
    // every other render anyway.
    const soon = ymd(addDays(new Date(`${day}T00:00`), SOON_DAYS))
    // The day after the one on screen. Through `addDays` like every other day
    // arithmetic here: a bare +86_400_000 lands at 23:00 on a 25-hour day and
    // "tomorrow" comes back as today.
    const tomorrow = ymd(addDays(new Date(`${day}T00:00`), 1))
    // The day a task has to have been left alone since to count as untouched.
    const stale = ymd(addDays(new Date(`${day}T00:00`), -STALE_DAYS))

    // `todayKeys` generalised, now that there are five groups rather than
    // three. A task due at 09:00 today is BOTH `dayKey(due) === today` and
    // `isOverdue` from 09:01, and one task offered twice is two "add" buttons
    // for one row — the first press makes the second a no-op the user cannot
    // explain. With five groups that is ten pairs to keep apart by hand, so
    // instead each group takes what the groups ABOVE it have not: the earlier
    // heading wins, which is why the order of the calls below is the order of
    // precedence and not just the reading order.
    const groups: Array<{ key: string; label: string; items: Task[] }> = []
    const offered = new Set<string>()
    const group = (key: string, label: string, pick: (t: Task) => boolean) => {
      const items = sortTasks(free.filter((t) => !offered.has(taskKey(t)) && pick(t)))
      for (const t of items) offered.add(taskKey(t))
      if (items.length > 0) groups.push({ key, label, items })
    }

    // Resolved HERE rather than at the render, unlike `REVIEW_GROUPS`. A
    // `SuggestGroup.label` is text by contract — `PlanRitual` renders one
    // straight into the DOM and swaps its own wording in for the leftovers —
    // and one of these carries an interpolated number besides.
    group('today', tr('today.sug.today'), (t) => !!t.due && dayKey(t.due) === day)
    group('overdue', tr('today.sug.overdue'), (t) => isOverdue(t.due, t.due_is_date))
    // Tomorrow, out of the seven-day block and under its own heading. It is the
    // one future day a plan for today is routinely about — the thing you pull
    // forward because this afternoon is free, or look at to decide whether it
    // can wait — and inside a list headed "Next seven days" it was a row like
    // any other, six days out of context.
    //
    // Between "Overdue" and the horizon rather than beside "Due today": the
    // block above is what the day is answerable for and the block below is what
    // is coming, and this is the first line of the second block rather than the
    // last of the first.
    group('tomorrow', tr('today.sug.tomorrow'), (t) => !!t.due && dayKey(t.due) === tomorrow)
    // The HORIZON, unchanged, and still `> day` rather than `> tomorrow`: the
    // `offered` set above has already taken tomorrow's tasks, and a second copy
    // of that fact in the predicate is a second thing to keep in step. Same
    // reason "Due today" leaves the overdue-from-09:01 case to precedence.
    //
    // The window is still SOON_DAYS, so this and the Home dashboard's Upcoming
    // module still surface the same set of tasks — they only differ now in how
    // many headings this screen puts over them.
    group('soon', tr('today.sug.soon'),
      (t) => !!t.due && dayKey(t.due) > day && dayKey(t.due) <= soon)
    // Below the dated three, and after them in precedence: a task that is both
    // overdue and was chosen last Monday is more usefully described by its due
    // date, which is a fact about the task, than by a plan it fell out of.
    group('open', tr('today.sug.open'), (t) => recentlyChosen.has(taskKey(t)))
    // UNDATED ONLY, and that restriction is what makes this group additive
    // rather than a fourth way to surface the same rows. All three dated groups
    // require a `due`, so an undated task appears in none of them and — unless
    // it was recently chosen — is invisible on this screen however long it has
    // sat there. A DATED task that has not been edited in three weeks is not
    // neglected, it is scheduled, and this is the last surface that should be
    // nagging about it. Disjointness from the dated three therefore holds by
    // construction, not by the `offered` set.
    //
    // The number is interpolated from the constant so the words and the figure
    // cannot drift apart the way a hard-coded "three weeks" would.
    group('stale', tr('today.sug.stale', { days: STALE_DAYS }), (t) => {
      if (t.due) return false
      // LAST-MODIFIED, falling back to CREATED. Both are OPTIONAL iCalendar
      // properties and both are declared nullable on `Task` for that reason —
      // plenty of clients write neither. A task carrying neither is not
      // evidence of neglect, it is the absence of evidence, so it is left out
      // rather than treated as infinitely old: an account synced from such a
      // client would otherwise see its ENTIRE undated backlog under this
      // heading on the first render.
      const touched = t.last_modified || t.created
      // Compared as day keys, through the same `dayKey` the rest of this file
      // buckets by, because a stamp another client anchored to a zone and one
      // this app wrote floating do not agree lexically.
      return !!touched && dayKey(touched) <= stale
    })
    return groups
  }, [tasks, onDay, day, isToday, recentlyChosen, tr])

  // ── the look-back ────────────────────────────────────────────────────────

  /**
   * A finished day, split by where each row came from.
   *
   * `source` is what makes a look-back worth reading: it separates what the
   * owner CHOSE from what merely turned up, and habits from both. The buckets
   * are `review_day`'s, arm for arm — including the residual, which is why the
   * lookup has a fallback rather than an exhaustive map. See REVIEW_ARM.
   *
   * Over `allEntries`, in reading order, so a dropped row is still here to be
   * filed under its own heading. Dropped is checked FIRST and is not a source:
   * "planned it and decided against it" is one answer whatever put the row
   * there, which is the same call the Python makes.
   */
  const review = useMemo(() => {
    // `allEntries` and nothing else. This used to be `isToday || !allEntries`,
    // and the `isToday` half was the only thing that made a day's own record
    // unreadable until the day was over: everything the record is made of is
    // already in hand for today (these are pure memos over `allEntries` and
    // `tasks` — no call, no fetch, and above all no `openDay`), so withholding
    // it meant the one question a daily surface should be able to answer at
    // 9pm — how did today go? — could only be asked tomorrow.
    if (!allEntries) return null
    const buckets: Record<string, DayEntry[]> = {
      chosen: [], carried: [], derived: [], habits: [], other: [], moved: [],
      dropped: [],
    }
    for (const e of allEntries) {
      // Dropped first, then moved, then the source. Both stamps outrank where
      // the row came from, for the same reason: what was decided about a row is
      // what a look-back is asking. The order between them only matters for a
      // row that somehow carries both, and "declined" is the later word.
      const arm = e.dropped_at ? 'dropped'
        : e.rolled_to ? 'moved'
          : (REVIEW_ARM[e.source] ?? 'other')
      buckets[arm].push(e)
    }
    // Empty groups are dropped rather than printed as empty states: five
    // headings over nothing is a form, not a record of a day.
    return REVIEW_GROUPS
      .map((g) => ({ key: g.key, label: g.label, rows: buckets[g.key] }))
      .filter((g) => g.rows.length > 0)
  }, [allEntries, isToday])

  /**
   * What was finished on the day under review without ever being on its plan.
   *
   * Usually the more interesting half of a look-back, and the half that answers
   * for days BEFORE any of this existed: the stamp comes off the VTODO's own
   * COMPLETED property, not from the plan, so a day from last month reads
   * exactly as well as yesterday.
   *
   * Bucketed with `dayKey`, never by slicing the string. `completed_at` is
   * whatever the client that finished the task wrote — one that anchored it to
   * a zone and one this app wrote floating do not agree lexically, and slicing
   * would file a late-evening completion on the wrong day for anyone west of
   * UTC. That is the same rule `_completions_by_day` applies server-side, which
   * is what keeps this list and the connector's agreeing.
   *
   * The stamp alone decides, with no second look at `completed`, because that
   * is what `_completions_by_day` does and the two have to agree. It is also
   * the right reading on its own: re-opening a task through this app DELETES
   * the COMPLETED property (`ical/edit.py::_set_status` — completion is a
   * coupled write and re-opening is its inverse), so a stamp that is still
   * there is a completion that still stands.
   */
  const offPlan = useMemo(() => {
    // Ordered by WHEN, through the helper the app's other two completion lists
    // already share (HomeView's "recently completed" and the Tasks pane's
    // completed view). The clock is the only thing these rows carry besides a
    // title, so an ordering that never looks at `completed_at` — `sortTasks` is
    // due date, then priority, then summary, then uid — prints a day's times of
    // day in what reads as no order at all. Every task here has a `completed_at`
    // by construction (it is what put it in this list), so every one lands in
    // `sortByCompletion`'s `stamped` branch: newest first, tie-broken into a
    // total order so an unchanged day never permutes between renders.
    return sortByCompletion(tasks.filter((t) => t.completed_at
      && dayKey(t.completed_at) === day
      && !everOnDay.has(taskKey(t))))
  }, [tasks, day, isToday, everOnDay])

  // Through `cssColor` at the accessor, so every downstream style site is
  // covered: these values are whatever another CalDAV client wrote into the
  // collection's calendar-color, and they land in inline styles — see util.ts.
  const colorOf = useCallback(
    (listId: string | null) => cssColor(lists.find((l) => l.id === listId)?.color), [lists])

  // ── the calendar strip ───────────────────────────────────────────────────
  const { cals, loaded: calsLoaded, eventsFor, requestWindow, windowErrors } = useCalendarData()
  const archived = useMemo(() => new Set(archivedCalendars), [archivedCalendars])
  const hidden = useMemo(() => new Set(hiddenCalendars), [hiddenCalendars])

  // The Home dashboard's window, expression for expression (HomeView.tsx ~120):
  // the six-week grid around the current month, `to` exclusive. Sharing the
  // EXPRESSION is what makes the two views share the FETCH — `requestWindow`
  // dedupes on (from, to, rev, calendar ids), so a window differing by one day
  // would fan out over every calendar a second time and repoint the provider's
  // single-slot `latest`/`seeded` refs at it, which is how the disk mirror ends
  // up holding a window nothing reads.
  //
  // Keyed on `today` rather than on `rev`, and deliberately NOT on the day
  // being looked at: this view's clock is the day key, so a rollover into a new
  // month has to move the grid, while a step of the picker must not — a window
  // that followed the picker would stop being HomeView's and would cost every
  // account the shared fetch. Both views still spell `monthGrid(new Date())`,
  // so on any render they name the same window. It is also why the strip itself
  // is painted for today only; see the render.
  const days = useMemo(() => monthGrid(new Date()), [today])
  const from = ymd(days[0])
  const to = ymd(addDays(days[41], 1))
  // Archived calendars are dropped before the fetch, merely hidden ones are
  // filtered at render — the same split HomeView and CalendarView make. It has
  // to be the same split here, or the calendar SET differs and the shared
  // window is lost along with it.
  const wanted = useMemo(() => cals.filter((c) => !archived.has(c.id)), [cals, archived])

  useEffect(() => {
    requestWindow(from, to, wanted)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // `requestWindow`, deliberately, and NOT `rev`. It is a useCallback over
    // [rev, enabled, fetchWindow], so its identity already carries the SSE bump
    // — naming `rev` beside it would be a second source of truth for one
    // signal, and the dep array would still be lying about what the effect
    // reads. See the same note at HomeView.tsx ~146. Deduping is unaffected:
    // `requestWindow` stamps `asked` with `rev`, so a re-run within one rev is
    // a no-op.
  }, [from, to, wanted.map((c) => c.id).join(','), requestWindow])

  // `fetchWindow` uses `allSettled`, so one calendar answering 502 never
  // rejects, never reaches `makeGuard`'s catch, and never raises the error
  // toast — the day would simply be short of events with nothing to say so. A
  // confidently short day is worse than a visibly broken one, so the failures
  // are read back by name and rendered. Same banner, same words, as HomeView.
  const calErrors = windowErrors(from, to)
  const events = eventsFor(from, to)

  // An event carries its collection href, not a calendar id — that is what maps
  // it back to the calendar whose colour it should wear, and to the id the
  // hidden set is written in.
  const calByHref = useMemo(() => new Map(cals.map((c) => [c.href, c] as const)), [cals])
  const todaysEvents = useMemo(() => {
    const visible = events.filter((e) => !hidden.has(calByHref.get(e.calendar)?.id || ''))
    // Through the shared bucketer rather than a local `start` filter: a span is
    // listed on every day it covers and continuation days are marked `cont`,
    // which is what `AgendaEvent` reads to label a mid-week day of a long event
    // correctly. A one-day filter would drop a three-day conference on days two
    // and three.
    return bucketByDay(visible, days).get(day) ?? []
  }, [events, hidden, calByHref, days, day])

  const eventStyle = useCallback((e: CalEvent): CSSProperties | undefined => {
    const c = cssColor(calByHref.get(e.calendar)?.color)
    return c ? { '--ev-c': c } as CSSProperties : undefined
  }, [calByHref])

  const heading = new Date(`${day}T00:00`).toLocaleDateString(locale,
    { weekday: 'long', month: 'long', day: 'numeric' })
  /** Whether a row counts as finished.
   *
   *  `rowDone` with the day's own `isToday`, named once here because three
   *  surfaces ask it — the header count below, the shutdown ritual, and each
   *  row's own mark — and a second spelling of it is how they come to describe
   *  one day two different ways. */
  const isDone = useCallback(
    (e: DayEntry) => rowDone(e, taskFor(e), isToday), [taskFor, isToday])

  /** What a row reads as. Same lifting, same reason, as `isDone` — a task entry
   *  carries no title of its own and only this view can resolve one. */
  const titleOf = useCallback(
    (e: DayEntry) => entryTitle(e, taskFor(e), loaded, tr), [taskFor, loaded, tr])
  // Through `rowDone`, the same call each row's own mark makes and with the same
  // `isToday`, which is the whole point of that helper existing: on a finished
  // day this figure counts what was done ON THAT DAY, and a header answering
  // that question differently from the list beneath it would be the one number
  // on this screen nobody could reconcile.
  //
  // Habits are counted here, in both halves. They take `rowDone`'s non-task arm,
  // which is the right answer for them for the same reason it is for a note — a
  // habit occurrence's doneness is the entry's own — so the widened `kind`
  // needed no branch, only checking. And they belong in the totals: they are on
  // the day, they are on the screen, and a "7 on the day" that disagreed with
  // the number of rows under it would be unreadable.
  const openCount = (entries ?? []).filter((e) => !isDone(e)).length

  // ── how full the day is ──────────────────────────────────────────────────
  //
  // Over the LIVE rows, so a dropped entry costs the day nothing — declining
  // something is how you get back under, and a total that kept counting it
  // would make the one control that helps useless.
  //
  // Rows with no estimate contribute NOTHING rather than some assumed default.
  // That leaves the total honestly low on a half-estimated day, which is the
  // right direction: a number that guessed would be a number nobody could act
  // on, and `unestimated` below says how much of the day it is silent about.
  const planned = useMemo(
    () => (entries ?? []).reduce((n, e) => n + (e.estimate_minutes ?? 0), 0), [entries])
  const unestimated = useMemo(
    () => (entries ?? []).filter((e) => e.estimate_minutes == null).length, [entries])

  /** Minutes of estimate on the rows that got done.
   *
   *  Read against `planned` at shutdown and NOTHING ELSE — no percentage, no
   *  ratio coloured against a target. It is honestly low on a half-estimated
   *  day, the same direction and for the same reason `planned` is: a figure
   *  that guessed at the unestimated rows would be a verdict dressed as a fact.
   */
  const doneMinutes = useMemo(() => (entries ?? [])
    .filter(isDone)
    .reduce((n, e) => n + (e.estimate_minutes ?? 0), 0), [entries, isDone])

  /** Minutes of calendar on this day. Shown BESIDE the capacity and never
   *  subtracted from it: an event is committed time, but whether a given one is
   *  work is a judgement the app does not get to make on the owner's behalf —
   *  lunch and the dentist are on the same calendar as the standup. So the
   *  collision is made visible and the arithmetic is left alone. */
  const meetingMinutes = useMemo(() => todaysEvents.reduce((n, ev) => {
    // An all-day event is a LABEL on the day, not a claim on its hours — "Anna's
    // birthday" is not eight hours of meeting — so it is skipped rather than
    // counted as the whole day and swamping the figure.
    if (ev.all_day || !ev.start || !ev.end) return n
    // Through `parseDate`, like every other reader of an event's times in this
    // app: a bare date and a datetime are different shapes, and `new Date()`
    // reads the first as UTC midnight, which is the previous day for anyone west
    // of it.
    const start = parseDate(ev.start).getTime()
    const end = parseDate(ev.end).getTime()
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return n
    return n + Math.round((end - start) / 60000)
  }, 0), [todaysEvents])

  const capacity = plan && plan.day === day ? plan.capacity : null
  const over = capacity != null && planned > capacity

  // The habits sheet edits RULES, so it is not part of any one day and does not
  // live in the day's state. It is opened from the header of the tab the habits
  // actually show up on rather than from Settings: the moment you want to change
  // one is the morning you are looking at it.
  const [sheet, setSheet] = useState(false)

  /**
   * Which half of today is on screen: the plan you are working, or the record
   * of how it has gone.
   *
   * Only ever consulted while `isToday`. A finished day has no plan half — it
   * IS the record — so `reviewing` below folds the two cases together and every
   * gate downstream reads that rather than testing the mode itself.
   *
   * NOT reset when the picker steps to a past day and back. Same call, and the
   * same reason, as `sheet` above: the gate is about what a day may PAINT, and
   * the owner never left the view they chose.
   */
  const [mode, setMode] = useState<'plan' | 'review'>('plan')
  /** The planning ritual is open. */
  const [ritual, setRitual] = useState(false)
  /** The shutdown ritual is open. Its own flag rather than a third value of
   *  `mode`: `mode` decides what the PAGE paints, and both rituals are overlays
   *  standing in front of whichever half is already there. */
  const [shutdown, setShutdown] = useState(false)
  /** The band was waved away for this session. Not persisted, and deliberately:
   *  it is a nudge about TODAY, and a dismissal that outlived the day would
   *  silently turn the feature off for good on the first impatient morning.
   *  Keyed by day so stepping the picker and coming back does not resurrect it
   *  on a day already waved away. */
  const [bandOff, setBandOff] = useState<string | null>(null)
  /** The screen is showing a record rather than a plan — because the day is
   *  finished, or because the owner asked for today's. */
  const reviewing = !isToday || mode === 'review'

  /** Rows may be dragged into a new order.
   *
   *  A live day being PLANNED, and every row on it carrying a real position.
   *  The second half is what makes the midpoint arithmetic total: the server
   *  positions every row it writes, so the only unpositioned rows that ever
   *  exist are optimistic ones between a click and its reply — and
   *  `orderEntries` sorts those to the end, so a midpoint taken against one
   *  would be measured against a neighbour that is about to move somewhere
   *  else. It resolves itself in a round trip. */
  const canArrange = isToday && !reviewing
    && dayRows.length > 1 && dayRows.every((e) => e.position != null)

  /** The suggestion groups the owner has asked to see in full, by group key.
   *
   *  Deliberately NOT reset when the day moves. Suggestions are gated on
   *  `isToday` and paint on no other day, so there is no stale state to clear —
   *  and a look-back and back would otherwise re-collapse a group the owner
   *  opened a moment ago. */
  const [expanded, setExpanded] = useState<string[]>([])

  /** One row of the day, whichever group it is painting in. Every list renders
   *  through this — today's two and the look-back's six — so a fix to a row
   *  cannot reach one group and miss the others. */
  // Where the dragged row STARTED, so each row can tell whether the drop lands
  // above it or below. Read off `dayRows` rather than a map index, because
  // `renderRow` is shared by eight groups and the index within a group is not
  // the index in the day.
  const dragIndex = useMemo(
    () => (dragId ? dayRows.findIndex((r) => r.entry_id === dragId) : -1),
    [dragId, dayRows])

  const rowFor = (e: DayEntry, worked = false) => (
    <TodayRow key={e.entry_id} entry={e} task={taskFor(e)} tasksLoaded={loaded} worked={worked}
      color={colorOf(e.list)} onToggleTask={toggle} onToggleEntry={toggleEntry}
      onDrop={drop} onEstimate={setEstimate}
      // A past day hands out no controls at all: see the header. The flag says
      // "this row is a record", and the row itself decides what that costs it.
      //
      // A DROPPED row is a record too, on whatever day it sits. It only ever
      // paints in a review — the day's own lists filter it out (`entries`) and
      // only `review` reads it back — so before today could be reviewed, "past
      // day" and "dropped" were the same set and `!isToday` covered both. They
      // came apart the moment a LIVE day could show its dropped rows: without
      // this, the Dropped group on today would hand out a checkbox for ticking
      // something the owner declined, and a ✕ for dropping what is already
      // dropped. "I decided against this" is the most useful thing the day
      // records, and neither control has anything to say about it.
      //
      // A MOVED row is the same case, arrived at from the other direction: the
      // work is on Thursday now, and Thursday's row is the one to tick. A
      // checkbox here would write today's record for work today is not doing.
      readOnly={!isToday || !!e.dropped_at || !!e.rolled_to}
      // `kind` as well as `habit_id`, so "undefined on every other kind" is a
      // fact rather than a consequence of the column being null on them today.
      count={e.kind === 'habit' && e.habit_id ? habitWeek.get(e.habit_id) : undefined}
      // ARRANGING. Three conditions, and each rules out a case where the
      // gesture would be a lie:
      //
      //  * `canArrange` — the day is live and being planned, and every row on
      //    it has a real position. An optimistically added row has none until
      //    the server answers, and `orderEntries` sorts an unpositioned row to
      //    the END, so a midpoint taken while one is in flight would be
      //    computed against a neighbour that is about to move. Off for that
      //    instant is the honest answer, and it is an instant.
      //  * not a HABIT. An occurrence's position is minted fresh by its rule
      //    every morning (`service._habit_entries_for`), so an order dragged
      //    into today's spine is gone tomorrow. Habits also paint in their own
      //    group above the day, so the arrangement would not even be visible
      //    where it was made. A gesture whose effect silently expires is worse
      //    than no gesture.
      //  * not DROPPED — those only ever paint in a look-back, which is
      //    read-only anyway, but the flag says so at the row rather than
      //    relying on that.
      draggable={canArrange && e.kind !== 'habit' && !e.dropped_at}
      dragging={dragId === e.entry_id}
      dragOver={overId === e.entry_id && dragId !== null && dragId !== e.entry_id}
      // Which EDGE the rule is drawn on. `moveRow` lands a downward drag AFTER
      // the target — deliberately, and its comment says why — while
      // `.today-row.drag-over` always painted the top edge, so on every downward
      // drag the line the owner was aiming at sat one gap above where the row
      // would actually go. The Tasks pane already carries this exact pair
      // (`drag.below` + `.task-drag.drag-over.drag-below`); the Today tab is a
      // separate, newer drag that never got it.
      dragBelow={dragIndex >= 0
        && dragIndex < dayRows.findIndex((r) => r.entry_id === e.entry_id)}
      onDragRow={setDragId}
      onDragOverRow={setOverId}
      onDropRow={(target) => {
        if (dragId) void moveRow(dragId, target)
        setDragId(null); setOverId(null)
      }}
      onDragEndRow={() => { setDragId(null); setOverId(null) }} />
  )
  const renderRow = (e: DayEntry) => rowFor(e)
  // The look-back's rows carry the one column a live list does not: what a
  // focus session actually spent on each, beside what it was estimated at.
  const renderReviewRow = (e: DayEntry) => rowFor(e, true)

  return (
    <div className="content">
      {/* `today-head` because this header holds more than any other tab's — a
          title, a two-button day nav, a date, a count and THREE named actions —
          and on a phone that is a layout question the shared rule cannot
          answer. Tasks has a title, a count and a view switcher; Calendar has a
          title and a month nav. Naming it is what lets the mobile block put the
          actions on one row here without touching the tabs that do not need
          it. */}
      <div className="content-head today-head">
        {/* The tab is Today; what is on the screen may not be. Renaming the
            title is the cheapest way to say which — a heading that still reads
            "Today" over last Tuesday's rows is the one mistake this surface
            cannot afford, because every row under it is a claim about a day. */}
        <span className="content-title">{isToday ? tr('today.title') : tr('today.lookBack')}</span>
        <div className="today-nav">
          <button type="button" className="icon-btn" aria-label={tr('today.prevDay')}
            // The floor is LOOKBACK_DAYS back from TODAY, and it stays there as
            // the view moves. It is NOT the same window as the one range read
            // behind this screen, which is anchored to `day` and so reaches
            // further back than this floor the moment the picker steps — on
            // purpose, so the oldest reachable day still has a whole week to
            // count its habits over. See LOOKBACK_DAYS.
            disabled={!prevDay} onClick={() => prevDay && setDay(prevDay)}>‹</button>
          <button type="button" className="icon-btn" aria-label={tr('today.nextDay')}
            // No future days, ever. Not a safety rule — `api.day` would read one
            // harmlessly — but a product one: only today can be opened, so a
            // future day could show nothing and accept nothing, and the Today
            // tab is not a planner for next month.
            disabled={!nextDay} onClick={() => nextDay && setDay(nextDay)}>›</button>
          {!isToday && (
            <button type="button" className="btn ghost"
              onClick={() => setDay(today)}>{tr('today.title')}</button>
          )}
        </div>
        <span className="content-sub">{heading}</span>
        <span className="spacer" />
        {entries !== null && (
          <span className="content-sub today-count">
            {/* "3 open" is a to-do list's figure and belongs on the day you can
                still act on. On a finished day the same rows are better counted
                the other way up: what got done THAT DAY is the thing a look-back
                is asking about, and that is what this counts — `rowDone` reads a
                past day's task rows off `completed_at`, so a task ticked this
                morning cannot add itself to last Tuesday's tally. Both halves
                are over the LIVE rows, so dropped entries are in neither — they
                have their own heading below.

                Keyed on `reviewing` rather than on `isToday`, so today counts
                itself the same way when it is being read as a record. Note what
                that does and does not change: only the WORDING moves. The
                arithmetic still goes through `rowDone(…, isToday)` — the LIVE
                flag on a live day — because a task ticked a moment ago has to be
                counted on the click, and its COMPLETED stamp is not in hand
                until the write comes back. The words describe the mode; the
                number describes the day. */}
            {!reviewing
              ? tr('today.countOpen', { open: openCount, total: entries.length })
              : tr('today.countDone',
                { done: entries.length - openCount, total: entries.length })}
          </span>
        )}
        {/* THE WAY IN TO A REVIEW OF TODAY, and the whole of it: this is a
            render-level switch over data already in hand, so pressing it issues
            no request of any kind. `mode` is deliberately absent from the read
            effect's dependency list and cannot go in it — there is nothing to
            re-read. That matters more than it looks: `api.openDay` is the only
            call that can CREATE a plan, and the one rule this file is built
            around is that it is called for today and nothing else. A review
            reached by any other route — a hidden day, a prefetch — would have
            had to touch it.

            Absent on a finished day rather than disabled, like every other
            control here: a past day IS the record, so a button offering to show
            one would be offering what is already on the screen. */}
        {isToday && (
          <button type="button" className="btn ghost today-review"
            aria-pressed={mode === 'review'}
            onClick={() => setMode((m) => (m === 'plan' ? 'review' : 'plan'))}>
            {mode === 'review' ? tr('today.modePlan') : tr('today.modeReview')}
          </button>
        )}
        {/* THE WAY IN TO WORKING THE DAY: the focus surface, which takes this
            plan as its queue. Today only and the planning mode only — a review
            is a record, and a record is not something to start. Absent rather
            than disabled on a past day, like every other control here. The
            word is the accessible name on every screen; on a phone the header
            is already full and the button shows a glyph instead (app.css). */}
        {isToday && mode === 'plan' && onStartWorking && (
          <button type="button" className="btn ghost today-focus" onClick={onStartWorking}
            aria-label={tr('today.startWorking')} title={tr('today.startWorking')}>
            <span className="today-focus__word">{tr('today.startWorking')}</span>
            <span className="today-focus__glyph mono" aria-hidden="true">▶</span>
          </button>
        )}
        {/* THE WAY IN TO THE SHUTDOWN, and deliberately not a band. The
            planning nudge is a band because the morning is when a plan is worth
            prompting for; a band offering to close the day would be on screen
            from breakfast onwards, nagging about an evening that has not
            arrived. A button is available the moment you want it and silent
            until then.

            `isToday` only, matching what the server will accept: `set_day_ritual`
            refuses a shutdown on a day that has already happened, because a
            shutdown performed on Thursday for Monday is not a record of Monday.
            Absent rather than disabled, like every other control here.

            The label does NOT change once the day is closed. The ritual is
            re-enterable on purpose — an evening thought belongs in the same
            reflection — and a header button that reported state would be the
            third thing on this screen doing so. The ritual says it instead, on
            the step where someone coming back would look. */}
        {isToday && (
          <button type="button" className="btn ghost today-shutdown"
            aria-haspopup="dialog" onClick={() => setShutdown(true)}>
            {tr('today.shutDown')}
          </button>
        )}
        {/* The sheet edits RULES, and its whole feedback loop is that the
            change shows up on the day behind it — creating a habit puts an
            occurrence on the day the next time that day is OPENED. A past day
            is never opened (see the read effect), so nothing done in here could
            ever show on the day it was opened from: the control would be a
            write surface offered from a screen that says it is a finished
            record. It comes back the moment the owner does. */}
        {/* A WORD, not a glyph. This was a bare `↻` carrying its name in
            `aria-label` and `title` — which meant the only thing that ever said
            "habits" to a sighted user was a tooltip, and a tooltip is a
            desktop-only affordance: there is no hover on a phone, so on the
            device a daily surface is most used on, the sole entry point to the
            feature was an unexplained symbol.

            The glyph stays, `aria-hidden`, beside the word rather than instead
            of it — so the accessible name is exactly "Habits", which is what it
            already was and what four suites match on exactly. Letting the ↻
            into the name would have renamed the control to "↻ Habits" and
            broken every one of them. */}
        {isToday && (
          <button type="button" className="btn ghost today-habits-open"
            aria-haspopup="dialog" onClick={() => setSheet(true)}>
            <span className="mono" aria-hidden="true">↻</span> {tr('today.habits')}
          </button>
        )}
      </div>

      {/* `isToday` as well as `sheet`, and that is the WHOLE gate — the same
          render-level shape `suggestions` and `review` use, rather than reaching
          for the setter at every place that moves the day. The opener was gated
          already and the sheet was not, so one opened on today survived a step
          back: `.overlay` blocks the pointer and nothing else — there is no
          focus trap in this dialog — so Tab reaches "Previous day" from inside
          it and Enter steps the view out from under it, leaving a writable
          dialog standing over a screen headed "Look back". Nothing in the sheet
          could have reached the past day (a habit is a rule, and minting is
          gated server-side by `service._habit_minting_allowed`), so what was
          broken was the claim in this file's header — which is what the header
          is for.

          `sheet` is deliberately NOT cleared on the way past. The gate is about
          what a finished day may PAINT, and the owner never closed the sheet:
          coming back to today brings it back exactly as they left it, which is
          also why one flag and one gate is the honest way to write this. */}
      {isToday && sheet && (
        <HabitsSheet rev={rev} guard={guard} onClose={() => setSheet(false)} />
      )}

      {calErrors.length > 0 && (
        <div className="cal-partial" role="status">
          Couldn&rsquo;t load {calErrors.join(', ')} &mdash; some events may be missing.
        </div>
      )}

      {/* The one box that writes to the day, and it is absent on a past one
          rather than disabled. A greyed-out field invites the question "why
          can't I?"; nothing at all, under a heading that reads "Look back",
          says what the surface is.

          Gated on `isToday` and NOT on `reviewing`, which is the one place
          those two deliberately part company. Reviewing today is not the same
          act as reading a finished day: today is still running, its rows are
          still tickable and droppable, and "note down the thing I actually did"
          is the commonest reason to be looking at this screen in the evening.
          Hiding the only writer while leaving every other control in place
          would be inconsistent in the one direction that costs something. The
          SUGGESTIONS do go — they are the surface offering more work, which is
          the thing a review is not for. */}
      {isToday && (
        <form className="quickadd today-add"
          onSubmit={(e) => { e.preventDefault(); void commit() }}>
          {/* DISABLED while the day is unknown. Not cosmetic: with no plan for
              this day every optimistic writer here is a no-op, so an add would
              reach the server, succeed, and paint nothing — a write that landed
              invisibly, which is the worse half of that finding. Refusing is
              the honest answer until there is a day to add to.

              "Unknown" is the read having failed AND nothing to paint, which is
              exactly `entries === null` — not `dayError` alone. Those were the
              same condition until the day gained a disk mirror: now a failed
              read on a tab the owner has used before still has last-known-good
              rows on screen, and refusing to write to a day that is visibly
              there would be refusing for a reason the screen contradicts. The
              add is safe against a stale snapshot besides — `add_day_entry` is
              idempotent on (day, task) and on (day, note text), and a row added
              to a day nobody has opened does not suppress its later snapshot
              (`service.open_day` merges around what is already there). */}
          <input className="input" value={text} aria-label={tr('today.addAria')}
            disabled={dayError && entries === null}
            placeholder={tr('today.addPlaceholder')}
            // The chip below DESCRIBES this field rather than announcing at it.
            // It used to be a `role="status"` live region, which was tolerable
            // while it appeared only on the rare line that parsed; now that it
            // is on for every line with a character in it, a live region would
            // re-announce on every keystroke. Described-by is read on demand,
            // and the submit button carries the same answer at the moment it is
            // acted on — see its label.
            aria-describedby={text.trim() ? 'today-add-fate' : undefined}
            onChange={(e) => {
              setText(e.target.value)
              // Emptying the box abandons the line, and the pin is a statement
              // about THAT line — so it goes with it. This is the one edit that
              // clears it, and it is not the keystroke rule the boolean it
              // replaced had: typing on is still typing the same line, and the
              // choice survives that.
              if (!e.target.value.trim()) setPinned(null)
            }} />
          {/* The consequence, in the name of the control that causes it. This is
              what a screen-reader user gets instead of the chip's colour and
              wording, and it is better placed than the chip was: it is heard
              when the button is reached, which is the instant before it fires. */}
          <button className="btn" type="submit" disabled={!text.trim()}
            aria-label={text.trim()
              ? (willBe === 'task' ? tr('today.addAsTask') : tr('today.addAsNote'))
              : undefined}>{tr('common.add')}</button>

          {/* THE LINE THAT SAYS WHAT ENTER WILL DO.
              It is on for any line with a character in it, not only for one
              that parsed. That is the change: the old chip appeared only when a
              date was recognised, so the case it never covered was the one that
              needed covering most — a plain line silently becoming a note that
              lives nowhere but in this day and reaches no other client on the
              account. Both outcomes are now stated in the same words the rows
              below use for the same three things (see KIND_LABEL).

              Advisory, never a gate: Enter commits whether or not this has been
              looked at, which is the difference between a preview and a
              confirmation step. */}
          {text.trim() && (
            <p className="today-chip" id="today-add-fate">
              <span className="label">{tr('today.willAdd')}</span>
              <span className="today-chip-kind">{tr(KIND_LABEL[willBe])}</span>
              {/* A task shows the parser's title, because the recognised phrase
                  has moved into the date beside it. A note shows the LINE, all
                  of it — what a note keeps is what was typed. */}
              <span className="today-chip-sum"
                dir={textDir(willBe === 'task' ? parsed.summary : text.trim())}>
                {willBe === 'task' ? parsed.summary : text.trim()}
              </span>
              {willBe === 'task' && reads && (
                // Through `fmtDue` with the live 12/24-hour setting, so what the
                // chip promises is exactly what the row will read once it exists.
                <span className="mono">
                  {fmtDue(dueFromParse(parsed, day), !parsed.dueTime, tf, locale)}
                  {parsed.guessed ? tr('today.guess') : ''}
                </span>
              )}
              {/* Where it ends up, which is the half the old chip never said and
                  the half that actually differs. */}
              {/* The list is named ONCE. When the picker is showing it is the
                  thing naming it, and repeating the name a line above it is the
                  same fact twice in two typefaces; when there is no picker —
                  one task list, or none — the sentence is the only place it can
                  be said. */}
              <span className="today-chip-fate">
                {willBe !== 'task'
                  ? tr('today.fate.note')
                  : taskLists.length > 1
                    ? tr('today.fate.taskAnyList')
                    : tr('today.fate.taskNamedList', {
                      list: taskLists.find((l) => l.id === listId)?.name
                        ?? tr('today.yourLists'),
                    })}
              </span>
            </p>
          )}

          {/* The CONTROLS, deliberately outside the paragraph above. Two
              reasons, and they point the same way: a control never belongs
              inside a region that describes something, and `aria-describedby`
              would otherwise read the buttons' labels out as part of the
              description. */}
          {text.trim() && (
            <div className="today-add-opts">
              <button type="button" className="btn ghost today-swap"
                onClick={() => setPinned(willBe === 'task' ? 'note' : 'task')}
                // Absent when there is nowhere to put a task: `willBe` has
                // already resolved to `note` for that reason, and offering a
                // swap that silently does nothing is worse than offering none.
                disabled={!listId}>
                {willBe === 'task' ? tr('today.makeItNote') : tr('today.makeItTask')}
              </button>
              {willBe === 'task' && taskLists.length > 1 && (
                // Only when there is a choice to make, and only when a task is
                // what is being made. The box is still ONE input on the fast
                // path — this appears beside a line already typed, it is never
                // a field to fill in first.
                <select className="input quickadd-list" value={listId}
                  aria-label={tr('today.listForNewTask')}
                  onChange={(e) => setListId(e.target.value)}>
                  {taskLists.map((l) => (
                    <option key={l.id} value={l.id}>{l.name}</option>
                  ))}
                </select>
              )}
            </div>
          )}
        </form>
      )}

      {/* THE NUDGE, and the whole of the prompting. A band rather than a wizard
          that opens itself: this tab is also the place you glance at to see
          what is next, and a flow standing in front of that on every first
          visit would be the thing people turn off in week two.
          Only on today, only before the day has been started, and gone for the
          session once waved away. */}
      {isToday && mode === 'plan' && plan?.day === day && !plan.committed_at
        && bandOff !== day && (
        <div className="today-band">
          <span className="today-band-text">
            {capacity == null
              ? tr('today.bandNoCapacity')
              : tr('today.bandCapacity', { capacity: fmtDuration(capacity) })}
          </span>
          <button type="button" className="btn" onClick={() => setRitual(true)}>
            {tr('today.planMyDay')}
          </button>
          <button type="button" className="icon-btn today-band-x"
            aria-label={tr('today.notNow')} onClick={() => setBandOff(day)}>✕</button>
        </div>
      )}

      {/* Both rituals are gated on `entries !== null` as well as on the flag —
          a flow that opened over a day still being read would ask what follows
          you out of an empty list. */}
      {isToday && shutdown && entries !== null && (
        <ShutdownRitual
          day={day} entries={entries} offPlan={offPlan}
          planned={planned} done={entries.length - openCount}
          doneMinutes={doneMinutes} unestimated={unestimated}
          shutdownAt={plan?.day === day ? plan.shutdown_at : null}
          reflection={plan?.day === day ? plan.reflection : null}
          renderRow={renderRow} colorOf={colorOf}
          isDone={isDone} titleOf={titleOf}
          onRoll={(e, to) => void rollEntry(e, to)}
          onDrop={(e) => void drop(e)}
          onReflect={(text) => void setReflection(text)}
          onShutdown={() => void shutdownDay()}
          onClose={() => setShutdown(false)} />
      )}

      {isToday && ritual && entries !== null && (
        <PlanRitual
          entries={entries} suggestions={suggestions}
          capacity={capacity} planned={planned} meetingMinutes={meetingMinutes}
          unestimated={unestimated} committedAt={plan?.committed_at ?? null}
          renderRow={renderRow} colorOf={colorOf}
          onCapacity={(m) => void setCapacity(m)}
          onAddTask={(t) => void addTask(day, t)}
          onCommit={() => void commitDay()}
          onClose={() => setRitual(false)} />
      )}

      {/* HOW FULL THE DAY IS. Present whenever the day has a capacity to be read
          against — which is any day the owner, or their weekday default, has
          given one — and absent entirely otherwise. An account that has never
          stated a capacity sees nothing here at all, because there is no honest
          number to put in it and inventing an eight-hour day for them is the
          one thing this feature must not do.

          On the day itself rather than only inside the ritual, because the
          moment it earns its keep is 2pm, when you are deciding whether to take
          one more thing on — which is exactly when nobody is running a ritual. */}
      {capacity != null && entries !== null && (
        <div className={`today-load ${over ? 'over' : ''}`}>
          <div className="today-load-line">
            <span className="today-load-fig mono">
              {tr('today.loadFigure',
                { planned: fmtDuration(planned), capacity: fmtDuration(capacity) })}
            </span>
            {meetingMinutes > 0 && (
              // Beside the figure, never inside it. See `meetingMinutes`.
              <span className="today-load-cal mono">
                {tr('today.loadCalendar', { amount: fmtDuration(meetingMinutes) })}
              </span>
            )}
            {unestimated > 0 && (
              // What the total is silent about. Without this the number reads as
              // the whole day when it may be a third of it, and quietly under-
              // reporting is worse than not reporting.
              <span className="today-load-rest mono">
                {tr('today.loadUnestimated', { count: unestimated })}
              </span>
            )}
          </div>
          {/* Decorative: the figure above already says it in words, and a bar
              that announced itself would say the same thing twice to a screen
              reader. */}
          <div className="today-load-bar" aria-hidden="true">
            <div className="today-load-fill"
              style={{ width: `${Math.min(100, capacity ? (planned / capacity) * 100 : 0)}%` }} />
          </div>
          {over && (
            // Said in WORDS as well as in colour, because the colour is the half
            // that does not survive a screen reader, a greyscale screenshot or a
            // custom theme. `role="status"` and not `alert`: this is a fact about
            // a day you can still change, not an error.
            <p className="today-load-over" role="status">
              {tr('today.over', { amount: fmtDuration(planned - capacity) })}
            </p>
          )}
        </div>
      )}

      <div className="scroll">
        {/* `reviewing`, not `!isToday`. A finished day has always taken the
            second arm; today now takes it too when the owner asks. `LookBack`
            is handed exactly what it was before and is reused verbatim — it is
            purely presentational and owns no state — so the two screens cannot
            drift into describing one day two different ways, which is the thing
            `REVIEW_ARM` exists to prevent. */}
        {!reviewing ? (
          <>
            {/* Habits first, above the day rather than mixed through it. The
                group is skipped entirely when there are none: a heading over
                nothing would advertise a feature as an empty state on every
                account that does not use it. */}
            {habitRows.length > 0 && (
              <section className="today-habits">
                <div className="label section-label">{tr('today.habits')}</div>
                {/* Named for assistive tech, which cannot see that the label
                    above belongs to this list. It is the one group on this
                    screen whose identity is the whole point of it being a
                    group. */}
                <ul className="today-list" aria-label={tr('today.habits')}>
                  {habitRows.map(renderRow)}
                </ul>
              </section>
            )}

            {/* Gated on the WHOLE day being empty, not on `dayRows`. A day
                holding three habits and nothing else is not a day with nothing
                on it, and saying so under a visible list of habits would
                contradict the screen it is printed on. */}
            {/* The day is UNKNOWN, which is neither "empty" nor "loading". Every
                other render of the day is gated on `entries !== null`, so
                without this the tab showed its furniture over a blank space and
                said nothing about why. Retry re-runs the read; `rev` cannot,
                because it only moves when the server publishes a change. */}
            {dayError && (
              <p className="empty" role="status">
                {tr('today.readFailed')}{' '}
                <button type="button" className="today-linkish"
                  onClick={() => setDayTry((n) => n + 1)}>{tr('today.tryAgain')}</button>
              </p>
            )}
            {entries !== null && entries.length === 0 && (
              <p className="empty">
                {tr('today.emptyBefore')}
                {/* The third way in to habits, and the one that reaches the
                    account most likely to need it: a brand-new day on a
                    brand-new account, where the Habits GROUP is (rightly)
                    absent because there is nothing to put in it. Without this
                    the feature was invisible until you already had one. */}
                <button type="button" className="today-linkish"
                  onClick={() => setSheet(true)}>{tr('today.setUpHabit')}</button>.
              </p>
            )}
            {dayRows.length > 0 && (
              <section className="today-day">
                {/* THE DAY'S OWN ROWS, NAMED. The habits group above has carried
                    a heading since it arrived; the rows below it never did, so
                    the boundary between the two was one heavier hairline under
                    the last habit — a line that says "something changed here"
                    only to a reader who is looking at that line. Everything
                    else about the two lists is identical: same row, same
                    checkbox, same left edge, by design.

                    Named unconditionally rather than only when habits sit above
                    it. Two reasons. The sequence on this tab is now Habits →
                    The day → On the calendar, three blocks each saying what it
                    is, and the middle one appearing only sometimes would make
                    the tab's shape depend on whether a habit happened to be due
                    — the heading would pop in on Tuesday and out on Wednesday.
                    And "On the calendar" below is already unconditional on
                    today, so a heading over the day's rows is this screen's
                    existing voice rather than a new one.

                    It is NOT the rule about headings over nothing (see the
                    habits group and the hint below it): those guard an EMPTY
                    group, which advertises a feature as a permanent blank. This
                    one is gated on the rows it names. */}
                <div className="label section-label">{tr('today.theDay')}</div>
                {/* Named for assistive tech for the same reason the habits list
                    is: the heading above is a sibling `div`, and nothing tells
                    a screen reader it belongs to this list. */}
                <ul className="today-list" aria-label={tr('today.theDay')}>
                  {dayRows.map(renderRow)}
                </ul>
              </section>
            )}

            {/* The other half of the habits trace: a day that HAS rows but no
                habit occurrences. The empty state above covers the empty day
                and this covers the worked one, and the two are mutually
                exclusive by construction (`entries.length > 0` here, `=== 0`
                there) — so the screen never says the same thing twice.

                It is a line of prose rather than an empty "Habits" section, and
                that is the same call the group above makes for the same reason:
                a heading over nothing advertises a feature as a permanent empty
                state on every account that does not want one. A sentence that
                explains what the feature IS costs a line and teaches something;
                a blank section costs a line and teaches nothing. */}
            {habitRows.length === 0 && entries !== null && entries.length > 0 && (
              <p className="empty today-quiet today-habits-hint">
                {tr('today.habitsHint')}
                <button type="button" className="today-linkish"
                  onClick={() => setSheet(true)}>{tr('today.setOneUp')}</button>.
              </p>
            )}

            {/* Today's only. The events in hand are HomeView's window — the six
                week grid around the CURRENT month, shared expression for
                expression so the two views share one fetch — and a day the
                picker reached may sit outside it. Painting the strip anyway
                would print "Nothing on the calendar today" over a day nobody
                fetched, which is a confident claim about a window that was
                never asked for; widening the window instead would cost the
                shared fetch for every account. A look-back is about what was
                planned and what got done in any case. */}
            <div className="label section-label">{tr('today.onTheCalendar')}</div>
            <CalendarStrip events={todaysEvents} day={day} loaded={calsLoaded}
              styleOf={eventStyle} />
          </>
        ) : (
          <LookBack review={review} offPlan={offPlan} renderRow={renderReviewRow}
            reflection={plan?.day === day ? plan.reflection : null}
            colorOf={colorOf} live={isToday} />
        )}

        {/* Not while reviewing. The `suggestions` memo keeps its own `isToday`
            gate — it means "what could be added to THIS day", which is still
            the right meaning — and this is the second, different question:
            a review is a place to see how the day went, not to be handed more
            work. The add box stays, though; see the form above. */}
        {!reviewing && suggestions.map((g) => {
          // CAPPED HERE, at the render, and never where the groups are built.
          // `group()` walks every item it matched into the `offered` set, which
          // is what keeps the five groups disjoint — a task due at 09:00 today
          // is also overdue from 09:01, and one task offered twice is two "add"
          // buttons for one row. Capping upstream would leave the sixth
          // due-today task un-offered, so it would reappear under "Overdue" as
          // a second chance to add the same thing.
          const shown = expanded.includes(g.key) ? g.items : g.items.slice(0, SUGGEST_MAX)
          return (
          <section key={g.key}>
            <div className="label section-label">{g.label}</div>
            <ul className="today-list">
              {shown.map((t) => (
                <li key={taskKey(t)} className="today-row today-sug">
                  <button type="button" className="today-plus"
                    aria-label={tr('today.addToToday',
                      { task: t.summary || tr('common.untitled') })}
                    onClick={() => void addTask(day, t)}>+</button>
                  {/* The same column the day's rows keep, in its task face:
                      a suggestion is a task, and one left edge has to run down
                      the whole screen or the groups stop reading as one list. */}
                  <span className="today-kind-mark" data-kind="task" role="img"
                    aria-label={tr('today.kind.task')}>
                    <span className="today-kind-box" style={colorOf(t.list)
                      ? { background: colorOf(t.list)! } : undefined} />
                  </span>
                  <span className="today-title" dir={textDir(t.summary)}>
                    {t.summary || tr('common.untitled')}
                  </span>
                  {t.due && (
                    <span className={`today-due mono ${g.key === 'overdue' ? 'overdue' : ''}`}>
                      {fmtDue(t.due, t.due_is_date, tf, locale)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {/* The count is IN the label, so a capped group never hides how much
                it is hiding — "Show all" alone would leave the owner pressing it
                to find out whether it was worth pressing. One way only: there is
                no collapse, because having asked to see the group you are
                reading it, and a control that takes the list back is a control
                whose only use is undoing a click you meant. */}
            {g.items.length > shown.length && (
              <button type="button" className="today-more"
                onClick={() => setExpanded((s) => [...s, g.key])}>
                {tr('today.showAll', { count: g.items.length })}
              </button>
            )}
          </section>
          )
        })}
      </div>
    </div>
  )
}

/**
 * A finished day, as the record of it: where every row came from, what was
 * declined, and what got done without ever being planned.
 *
 * Purely presentational — it is handed the buckets and the rows and owns no
 * state, which is the point. There is no path from here to a write: `renderRow`
 * arrives with `readOnly` already set by its caller, and nothing else in this
 * subtree is a control. See the header for why that matters.
 */
function LookBack({ review, offPlan, reflection, renderRow, colorOf, live = false }: {
  /** The day's live rows grouped by origin, plus the dropped ones, in reading
   *  order — or `null` while the read is still in flight. */
  review: Array<{ key: string; label: string; rows: DayEntry[] }> | null
  /** Tasks finished on the day that the plan never held. */
  offPlan: Task[]
  /** What the owner wrote about the day at shutdown, or null. */
  reflection: string | null
  renderRow: (e: DayEntry) => ReactNode
  colorOf: (listId: string | null) => string | null
  /** The day being read is TODAY, reviewed while it is still running. It
   *  changes one thing — the tense of the empty state — and deliberately
   *  nothing else: the buckets, the headings and the rows are the same record
   *  read the same way, which is the point of reusing this component rather
   *  than writing a second one that could describe a day differently. */
  live?: boolean
}) {
  const { locale, t: tr } = useI18n()
  const tf = useTimeFormat()
  // Nothing at all until the read lands — the same discipline the day's own
  // empty state keeps. "Nothing was planned" flashed over a fetch in flight is
  // a claim about a day the surface has not seen yet, and on a look-back that
  // claim is the entire content of the screen.
  if (review === null) return null
  return (
    <>
      {/* WHERE THE REFLECTION IS READ BACK, and the reason it is worth writing.
          The shutdown's last step promises "you will see it whenever you look
          back at today", and until this existed that promise was false: the
          text was stored, prefilled into the box that wrote it, and shown
          nowhere else.

          First, above the rows, because it is the only thing on this screen in
          the owner's own words — everything under it is the machine's record of
          the same day. */}
      {reflection && (
        <section className="today-reflection">
          <div className="label section-label">{tr('today.howItWent')}</div>
          <p className="today-reflection-text" dir={textDir(reflection)}>{reflection}</p>
        </section>
      )}
      {review.map((g) => (
        <section key={g.key}>
          <div className="label section-label">{tr(g.label)}</div>
          {/* Every list named, not just the habits: on this screen the heading
              IS the information — the same row means something different under
              "Chosen" than under "Derived" — and assistive tech cannot see that
              the label above belongs to the list below it. */}
          <ul className="today-list" aria-label={tr(g.label)}>{g.rows.map(renderRow)}</ul>
        </section>
      ))}
      {offPlan.length > 0 && (
        <section>
          <div className="label section-label">{tr('today.doneOffPlan')}</div>
          <ul className="today-list" aria-label={tr('today.doneOffPlan')}>
            {offPlan.map((t) => (
              // Not a `.today-row .today-sug`: a suggestion is something not on
              // the day yet and reads a step quieter for it, while these are
              // the one thing on this screen that definitely happened.
              <li key={taskKey(t)} className="today-row">
                <span className="today-check-gap today-mark mono" role="img"
                  aria-label={tr('today.doneMark')}>✓</span>
                <span className="today-kind-mark" data-kind="task" role="img"
                  aria-label={tr('today.kind.task')}>
                  <span className="today-kind-box" style={colorOf(t.list)
                    ? { background: colorOf(t.list)! } : undefined} />
                </span>
                <span className="today-title" dir={textDir(t.summary)}>
                  {t.summary || tr('common.untitled')}
                </span>
                {/* The clock only. The date is the heading of the whole screen,
                    and `fmtDue` would repeat it on every row. `completed_at` is
                    non-null for every task in this list by construction — it is
                    what put them in it. */}
                <span className="today-due mono">{fmtClock(t.completed_at!, tf, locale)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {review.length === 0 && offPlan.length === 0 && (
        <p className="empty">
          {live
            // Today, and still running: "was planned" would file the day as
            // over when there are hours of it left, and the add box is sitting
            // directly above this line ready to take the first thing.
            ? tr('today.reviewEmptyLive')
            : tr('today.reviewEmptyPast')}
        </p>
      )}
    </>
  )
}

/** Today's events, read-only.
 *
 *  An event is already committed time: it is context for planning the day, not
 *  a thing to plan, so it never becomes a `day_plan` entry and there is no way
 *  to add one from here. `AgendaEvent` with no `onOpen` is what makes the row
 *  static — the same lever the Home mini-calendar pulls — so this surface
 *  cannot grow an event editor by accident. */
function CalendarStrip({ events, day, loaded, styleOf }: {
  events: DayEv[]
  day: string
  /** The calendars fetch has come back at least once. */
  loaded: boolean
  styleOf: (e: CalEvent) => CSSProperties | undefined
}) {
  const tr = useT()
  // `eventsFor` answers `[]` both for "no events" and for "nothing known yet",
  // so length alone cannot tell them apart — and "Nothing on the calendar
  // today" flashing up before a busy day paints reads as a bug, exactly as it
  // does in the dashboard's TaskList. `loaded` is the calendars fetch, one hop
  // ahead of the events, and the only "it landed" signal this provider exposes;
  // it does not prove the events for THIS window have arrived, so this is a
  // floor on the claim rather than a guarantee. Staying blank is the safe side
  // of that: it asserts nothing.
  if (!loaded && !events.length) return null
  if (!events.length) {
    return <p className="empty today-quiet">{tr('today.noCalendar')}</p>
  }
  return (
    <div className="today-agenda">
      {events.map((ev) => (
        <AgendaEvent key={eventKey(ev)} ev={ev} day={day} style={styleOf(ev)} />
      ))}
    </div>
  )
}

/** The most minutes an estimate may be, matching the edge model's ceiling.
 *
 *  A day, because a plan is a plan for ONE — above that it is a typo rather
 *  than an intention. Restated here rather than imported because the two are
 *  guarding different things: the server's bound is what stops a bad request
 *  reaching SQLite as an unmapped OverflowError, and this one is what stops the
 *  owner watching a number they typed come back rejected. */
const MAX_ESTIMATE = 1440

/**
 * One row's estimate: a quiet reading that becomes an input when pressed.
 *
 * A button rather than a permanently-open field, and that is the whole design
 * question here. Every row on the day would carry one, so a field on each is a
 * column of boxes down a list that is meant to be glanceable — the estimate is
 * something you set during the ritual and read for the rest of the day. Reading
 * is the common case, so reading is what it costs nothing.
 *
 * Commits on blur AND on Enter, reverts on Escape. That is `HabitEditRow`'s
 * rename, deliberately: the two are the same interaction and a second set of
 * keys for it would be a second thing to learn.
 */
function EstimateCell({ minutes, readOnly, label, onChange }: {
  minutes: number | null
  /** The day has finished, so this is a record and not a control. */
  readOnly?: boolean
  /** What this estimates, for the control's accessible name. */
  label: string
  /** Minutes, or null to clear. */
  onChange: (next: number | null) => void
}) {
  const tr = useT()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  // A finished day shows what was estimated and offers no way to change it —
  // the same line every other control on this row draws. Nothing at all when
  // nothing was estimated: a dim "add one" on a day that has already happened
  // is an invitation to rewrite the record.
  if (readOnly) {
    return minutes == null ? null : (
      <span className="today-est mono">{fmtDuration(minutes)}</span>
    )
  }

  if (!editing) {
    return (
      <button type="button" className={`today-est mono ${minutes == null ? 'unset' : ''}`}
        aria-label={minutes == null
          ? tr('today.estimateAria', { entry: label })
          : tr('today.estimatedAt', { entry: label, amount: fmtDuration(minutes) })}
        onClick={() => { setDraft(minutes == null ? '' : String(minutes)); setEditing(true) }}>
        {minutes == null ? tr('today.est') : fmtDuration(minutes)}
      </button>
    )
  }

  const commit = () => {
    setEditing(false)
    const raw = draft.trim()
    // An emptied field CLEARS, which is the only way back to "nobody said" and
    // is why the wire needed a sentinel for it at all.
    if (!raw) { if (minutes != null) onChange(null); return }
    const n = Number(raw)
    // Bounded here as well as at the edge, and the same way `SchedulingView`
    // bounds its durations: `min`/`max` on a number input do not stop a typed
    // value, so the attributes are for the spinner and this is the rule.
    if (!Number.isFinite(n)) return
    const next = Math.max(0, Math.min(MAX_ESTIMATE, Math.round(n)))
    if (next !== minutes) onChange(next)
  }

  return (
    <input className="input today-est-input" type="number" autoFocus
      min={0} max={MAX_ESTIMATE} step={5} value={draft}
      aria-label={tr('today.minutesFor', { entry: label })}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit() }
        // Escape abandons the edit. It does NOT close anything above this —
        // `useEscape` is bound to the window and would take the habits sheet
        // with it, so the propagation stop is load-bearing rather than tidy.
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setEditing(false) }
      }} />
  )
}

function TodayRow({
  entry, task, tasksLoaded, color, count, readOnly, onToggleTask, onToggleEntry, onDrop,
  onEstimate, worked = false,
  draggable = false, dragging = false, dragOver = false, dragBelow = false,
  onDragRow, onDragOverRow, onDropRow, onDragEndRow,
}: {
  entry: DayEntry
  /** The task a task entry points at, once it is in hand. */
  task: Task | undefined
  /** The tasks fetch has come back at least once this session. */
  tasksLoaded: boolean
  color: string | null
  /** This row is a RECORD, not a control: the day it belongs to has already
   *  happened. It renders its state and hands out no way to change it — see
   *  this file's header, and `mcp/api.py::update_day_entry`, which refuses the
   *  same write for the same reason on the connector side. */
  readOnly?: boolean
  /** This week's occurrences of the habit this row is one of: how many were
   *  ticked, out of how many EXIST. Undefined on every other kind — and on a
   *  habit whose id nothing counted, which is why the render below asks whether
   *  it is here rather than assuming a habit row always has one. */
  count?: { done: number; total: number }
  onToggleTask: (t: Task) => Promise<void>
  onToggleEntry: (e: DayEntry) => Promise<void>
  onDrop: (e: DayEntry) => Promise<void>
  /** Set or clear how long this is expected to take. Null clears. */
  onEstimate: (e: DayEntry, minutes: number | null) => Promise<void>
  /** Paint the time a focus session actually spent on this row, beside what it
   *  was estimated at. A REVIEW column: the look-back is where a measurement
   *  belongs next to a guess, and a live list already has a number on every
   *  row — a second one would be a score on a screen that keeps none. */
  worked?: boolean
  /** This row may be picked up and moved. Decided by the caller — see the
   *  three conditions there; the row only wears the result. */
  draggable?: boolean
  /** This row is the one being carried. */
  dragging?: boolean
  /** Something else is being carried and is currently over this row. */
  dragOver?: boolean
  /** The dragged row started ABOVE this one, so the drop lands below it and the
   *  rule belongs on the bottom edge. Only consulted while `dragOver`. */
  dragBelow?: boolean
  onDragRow?: (entryId: string) => void
  onDragOverRow?: (entryId: string) => void
  onDropRow?: (entryId: string) => void
  onDragEndRow?: () => void
}) {
  const { locale, t: tr } = useI18n()
  const tf = useTimeFormat()
  /** The last press on this row landed in a TEXT FIELD. Written on mousedown and
   *  read on dragstart — see the row's own comment for why the obvious
   *  `e.target` test cannot do this job. */
  const grabbedText = useRef(false)
  const isTask = entry.kind === 'task'
  const isHabit = entry.kind === 'habit'
  // The task a row points at can genuinely go away — deleted in another CalDAV
  // client, or its whole list removed — and the entry survives it, because
  // `day_plan` carries no foreign key on purpose: what a day recorded should
  // not vanish because the task did. Saying so beats a blank row. But only once
  // the tasks have actually landed: before that, "gone" would be a confident
  // claim about a fetch still in flight, so the row waits with an empty title
  // instead. `tasksLoaded` is `useTaskData().loaded`, the same gate the
  // dashboard's TaskList uses.
  const gone = isTask && !task && tasksLoaded
  // Through the shared rule, so this row and the shutdown ritual's list cannot
  // come to read one entry two different ways — see `entryTitle`.
  const title = entryTitle(entry, task, tasksLoaded, tr)
  // Same fence as the header describes, through the same call the day's own
  // "N done" figure makes, so the row and the count over it cannot answer the
  // question differently. `!readOnly` is exactly "this day is still live" — see
  // the prop — and that is what decides between the task's CURRENT flag and the
  // day's own record of what happened on it.
  const done = rowDone(entry, task, !readOnly)
  // Only ever true on the look-back: the day's own lists filter dropped rows
  // out (`entries`), and only the review reads them back in, under their own
  // heading. The class exists so the row still reads as declined once it is out
  // of that heading's context — in a screenshot, or under the ⌘F of someone
  // scrolling.
  const dropped = !!entry.dropped_at
  // The other stamp that only ever paints in a look-back, and the counterpart to
  // the one above: this row is not gone, it is somewhere else. It gets its own
  // class rather than sharing `today-dropped` because the two say opposite
  // things about whether the work is still going to happen.
  const moved = !!entry.rolled_to
  // Assembled rather than interpolated: with five optional markers the template
  // runs past the line and reads as punctuation.
  const cls = ['today-row', isHabit && 'today-habit', dropped && 'today-dropped',
    moved && 'today-moved',
    done && 'done', gone && 'gone', draggable && 'today-draggable',
    dragging && 'today-dragging', dragOver && 'drag-over',
    dragOver && dragBelow && 'today-below'].filter(Boolean).join(' ')

  // The leftmost cell, in three states rather than two. Lifted out of the JSX
  // because a three-armed conditional inside it cannot be commented arm by arm,
  // and each of these arms is a decision:
  //
  //  * READ-ONLY — a record of a tick MADE ON THIS DAY, never a control and
  //    never a tick made since: `rowDone` above is what makes that true, and a
  //    row whose task was finished later carries no mark here at all. A done row
  //    gets the mark with `role="img"` and a name rather than `aria-hidden`,
  //    because
  //    whether it was done is the single most important thing a look-back row
  //    says, and a glyph or a line-through says it to sighted readers only. An
  //    undone row gets the plain gap: "not done" is the absence of the mark,
  //    and announcing it on every row would bury the rows that carry one.
  //  * GONE — nothing to tick, because the checkbox writes a VTODO STATUS and
  //    there is no VTODO. The drop control still works, which is how the row is
  //    cleared off the day.
  //  * otherwise the checkbox.
  //
  // All three occupy `.today-check-gap`'s width (the checkbox is `.check`,
  // which is sized from the same custom property), so a mixed list keeps one
  // left edge.
  const check = readOnly
    ? (done
      ? (
        <span className="today-check-gap today-mark mono" role="img"
          aria-label={tr('today.doneMark')}>✓</span>
      )
      : <span className="today-check-gap" aria-hidden="true" />)
    : gone
      ? <span className="today-check-gap" aria-hidden="true" />
      : (
        <button type="button" className={`check ${done ? 'on' : ''}`}
          // The task's own state, and its own writer. A task entry never
          // records doneness of its own — see this file's header.
          disabled={isTask && !task}
          aria-pressed={done}
          aria-label={done
            ? tr('today.uncheck', { entry: title || tr('today.entry') })
            : tr('today.check', { entry: title || tr('today.entry') })}
          onClick={() => void (isTask && task ? onToggleTask(task) : onToggleEntry(entry))}>
          ✓
        </button>
      )

  return (
    <li className={cls}
      // Native HTML5 drag and drop, the same shape the sidebar, the tasks pane,
      // the dashboard and the calendar all use. Deliberately not a library and
      // not a bespoke pointer handler: this repo has no animation or gesture
      // dependency at all, and one invented here would be a fifth answer to a
      // question the other four already agree on.
      //
      // Pointer-only, which every one of those four also is. It is a real gap —
      // a phone cannot arrange its day — and it is the app's gap rather than
      // this screen's, so it is recorded here and in the header rather than
      // papered over with a gesture that behaves differently from the rest.
      draggable={draggable || undefined}
      // WHERE THE GRAB LANDED, recorded on the way down.
      //
      // `draggable` is on the ROW and the row contains an editable control — the
      // estimate cell becomes a number input in place — so a press inside it
      // starts a drag of the whole row, and selecting the text of an estimate
      // silently reorders the day.
      //
      // The obvious guard is to test `e.target` inside `onDragStart`, which is
      // what the Tasks pane does. MEASURED IN CHROMIUM, THAT GUARD IS INERT: a
      // `dragstart` is fired at the drag SOURCE NODE — the `<li>` — not at the
      // node under the pointer, so `closest('input, …')` is always null and the
      // arm never runs. jsdom does not model that (it dispatches at whatever
      // element the test names), so such a guard passes its test and does
      // nothing in every real browser.
      //
      // `mousedown` DOES target the deepest node, so the answer is recorded
      // there and read below. Verified end to end in a real browser rather than
      // reasoned about: grabbing the input fires no drop, grabbing the title
      // does.
      //
      // TEXT FIELDS ONLY, deliberately. This once matched `button` as well,
      // which is a wider net than the problem: the failure is that dragging to
      // SELECT TEXT reorders instead, and a button has no drag semantics of its
      // own, so a press-drag starting on the checkbox or the estimate's
      // collapsed cell may as well grab the row. Guarding those would only take
      // grab area away.
      onMouseDown={draggable
        ? (e) => {
          grabbedText.current = !!(e.target as HTMLElement)
            ?.closest?.('input, textarea, [contenteditable]')
        }
        : undefined}
      onDragStart={draggable
        ? (e) => {
          // A gesture that began in a text field belongs to that field, not to
          // the row it happens to sit in.
          if (grabbedText.current) {
            e.preventDefault()
            return
          }
          onDragRow?.(entry.entry_id)
          e.dataTransfer.effectAllowed = 'move'
          // A payload, so this drag carries what every other drag in this app
          // carries. The reason given at the other four sites is that Firefox
          // will not start a drag with an empty transfer; that was true of old
          // Firefox and is not of any current one, so the honest reason to do it
          // here is consistency — a gesture with nothing on the transfer is one
          // no external drop target can read, and there is no reason for this
          // one to be the odd one out.
          e.dataTransfer.setData('text/plain', entry.entry_id)
        }
        : undefined}
      // `preventDefault` is what makes this a drop target at all — without it
      // the browser refuses the drop and the gesture silently does nothing.
      onDragOver={draggable
        ? (e) => { e.preventDefault(); onDragOverRow?.(entry.entry_id) }
        : undefined}
      onDrop={draggable
        ? (e) => { e.preventDefault(); onDropRow?.(entry.entry_id) }
        : undefined}
      // A drag abandoned outside any row still has to put the highlight back.
      onDragEnd={draggable ? () => onDragEndRow?.() : undefined}>
      {check}
      {/* ONE element, always rendered, whatever the kind — which is the fix as
          much as the marks themselves are. It used to be two conditionals, a
          `.list-dot` for a task and a `↻` for a habit, and a NOTE matched
          neither: it rendered nothing at all, so every note's title sat 13px
          left of every other row's. A single cell of a fixed width cannot
          reintroduce that, and it cannot be reintroduced by a fourth `kind`
          either — `DayEntryKind` widens silently (see api.ts) and the arm that
          would have been forgotten is now the one that no longer exists.

          The three faces say the thing the day never said out loud: a FILLED
          square is a task, which lives on a list and reaches every other CalDAV
          client on the account; a HOLLOW one is a note, which exists nowhere
          but in this day; `↻` is a habit. Fill against outline is deliberately
          the same geometry — the left edge is free — and it survives a
          colourless list, a custom theme and a greyscale screenshot, none of
          which "a coloured dot versus nothing" does. */}
      <span className="today-kind-mark" data-kind={entry.kind} role="img"
        aria-label={tr(KIND_LABEL[entry.kind] ?? 'today.kind.entry')}>
        {/* The kind goes in a DATA ATTRIBUTE, not in the class list, and that is
            a scar rather than a preference: the first cut wrote
            `today-kind-mark ${entry.kind}`, which put a bare `task` class on
            every task row — and `.task` is the Tasks pane's ROW rule, three
            hundred lines up this same global stylesheet. It brought
            `display: flex`, `align-items: flex-start` and `padding: var(--row-y)
            var(--gutter)` with it, so the 7px square painted as a 52×19 slab.
            The classes here are one global namespace; `[data-kind]` cannot
            collide with one.

            The SHAPE is a child rather than this element, so the column and the
            mark can be sized independently: the outer span is the 13px column
            that holds the left edge, the inner box is the 7px square that says
            which kind it is. A glyph kind (a habit) puts its character in the
            same centred box, and a kind this build has never heard of paints an
            empty column — no mark, but the edge holds, which is the half that
            must not depend on knowing every kind. */}
        {isHabit ? '↻' : (isTask || entry.kind === 'note') ? (
          <span className="today-kind-box"
            // The list's colour, when it has one, exactly as `.list-dot` took
            // it. The CSS default underneath is --fg rather than --fg-faint: a
            // task on a colourless list was previously a faint dot against a
            // faint rule, which is the case this whole change is about.
            style={isTask && color ? { background: color } : undefined} />
        ) : null}
      </span>
      <span className="today-title" dir={textDir(title)}>{title}</span>
      {/* Omitted ENTIRELY below two occurrences — see MIN_WEEK_COUNT. Rendered
          in --fg-faint whatever the ratio says, and never in --warn: "1 of 5
          this week" is a record, and colouring it as a failure turns the one
          surface the owner opens every morning into something that tells them
          off.

          The WORDS move with the day, because the figure does not describe the
          same week on both screens. `habitWeek` counts from the Monday of the
          week the day ON SCREEN falls in, up to and including that day — so on
          a look-back "this week" names the wrong week the moment the reviewed
          day sits in a previous one, and a bare "that week" would overclaim in
          the other direction, since the count stops at the reviewed day and
          says nothing about the days after it. The number is kept rather than
          hidden because how the spine held up is a fair thing to ask of a
          finished day, and this is the same figure the habit showed on the day
          itself. */}
      {count && count.total >= MIN_WEEK_COUNT && (
        <span className="today-habit-count mono">
          {readOnly
            ? tr('today.weekCountThat', { done: count.done, total: count.total })
            : tr('today.weekCountThis', { done: count.done, total: count.total })}
        </span>
      )}
      {/* Before the due date, because they answer different questions and the
          nearer one to the title is the one the ritual is about: how long this
          will take, versus when it is wanted by. */}
      <EstimateCell minutes={entry.estimate_minutes} readOnly={readOnly}
        label={title || tr('today.thisEntry')}
        onChange={(next) => void onEstimate(entry, next)} />
      {/* Always painted when asked for, empty when nothing was measured — the
          same lesson as the due cell: a column that appears only sometimes
          makes every cell before it move. Minutes, like the estimate beside
          it, and never a ratio of the two. */}
      {worked && (
        <span className="today-worked mono"
          title={entry.worked_seconds
            ? tr('today.worked', { amount: fmtDuration(Math.round(entry.worked_seconds / 60)) })
            : undefined}>
          {entry.worked_seconds ? fmtDuration(Math.round(entry.worked_seconds / 60)) : ''}
        </span>
      )}
      {/* ALWAYS rendered, empty when the row has no due date — the same lesson
          as the kind column on the left. A cell that appears only sometimes
          makes every cell BEFORE it move: with this conditional, an estimate on
          a row with a due date sat fifty pixels left of one without, so the
          column a person scans during the ritual zigzagged down the list. The
          empty span costs a fixed strip of space and buys one right edge. */}
      <span className="today-due mono">
        {/* WHERE IT WENT, in place of when it was wanted by. A moved row only
            ever paints in a look-back, and on that screen its destination is the
            whole reason it is still on the list — the due date it kept is the
            less interesting of the two facts, and the target day's own row
            carries it anyway. */}
        {entry.rolled_to
          ? tr('today.movedTo', { day: fmtDue(entry.rolled_to, true, tf, locale) })
          : task?.due ? fmtDue(task.due, task.due_is_date, tf, locale) : ''}
      </span>
      {/* Absent, not disabled, on a finished day. Dropping is the one write the
          backend DOES still allow on a past day — `update_day_entry` permits it
          because saying "this did not happen" subtracts from the record rather
          than manufacturing one — but permitted is not the same as offered: a
          look-back that lets you quietly tidy last Tuesday until it looks
          better is a look-back nobody should trust, and the connector is the
          right place for a deliberate correction. */}
      {!readOnly && (
        <button type="button" className="today-drop"
          aria-label={tr('today.removeFromToday', { entry: title || tr('today.entry') })}
          onClick={() => void onDrop(entry)}>✕</button>
      )}
    </li>
  )
}

// ── the habits sheet ─────────────────────────────────────────────────────────

/**
 * The days a habit's `days` names, as a set of `HABIT_DAYS` tokens.
 *
 * '' is every day, and the chips show that as ALL SEVEN LIT rather than as none
 * of them. A row of chips is read as "these are the days it comes up", so seven
 * dark chips beside the words "every day" would say the opposite of what they
 * mean.
 */
const daysOn = (days: string): Set<string> =>
  new Set<string>(days ? days.split(',') : HABIT_DAYS)

/**
 * A habit as the PATCH body it was given would leave it, for the paint between
 * the click and the reply.
 *
 * THE ONE PLACE the wire's shape and the row's are converted between, and the
 * conversion is not the identity: pausing is a BOOLEAN on the body and a STAMP
 * on the row. The stand-in stamp is local, exactly as `toggleEntry`'s `done_at`
 * is, and the server's own is what the row settles on a moment later — nothing
 * reads the value, only whether it is there (`paused` is `!!paused_at`).
 *
 * An omitted field is left alone, which is what the endpoint does with it too.
 * `undefined` is the only test that can tell "not asked about" from "set to
 * false", because `paused: false` is a real value — resuming. See
 * `PatchHabitBody`.
 */
const applyPatch = (h: Habit, body: PatchHabitBody): Habit => ({
  ...h,
  ...(body.title !== undefined ? { title: body.title } : {}),
  ...(body.days !== undefined ? { days: body.days } : {}),
  ...(body.position !== undefined ? { position: body.position } : {}),
  ...(body.paused !== undefined
    ? { paused_at: body.paused ? h.paused_at ?? new Date().toISOString() : null }
    : {}),
})

/**
 * Where habits are made, renamed, rescheduled, paused and deleted.
 *
 * It edits RULES, not a day, so it holds none of the day's state and writes
 * none of it. What it changes reaches the screen behind it the way every other
 * write in this app does: the server publishes `day_updated`, `rev` bumps, and
 * the view re-opens the day — which is also what mints today's occurrence of a
 * habit created this morning, since opening a day tops up the rows its rules are
 * owed. Re-fetching the day from in here as well would be a second path for one
 * signal, and the two would drift.
 *
 * The dialog conventions are the ones every other overlay in this app keeps —
 * `.overlay` + `.modal`, `aria-modal`, a ✕, a scrim that closes on a press AND
 * release that both land on it, and `useEscape` — rather than a set invented for
 * this one screen. The scrim's two-event dance is not fussiness: a bare onClick
 * fires whenever the release lands on the scrim, so a text drag-select that
 * began inside the sheet and finished outside it would discard the whole thing.
 */
function HabitsSheet({ rev, guard, onClose }: {
  rev: number
  guard: ReturnType<typeof makeGuard>
  onClose: () => void
}) {
  const tr = useT()
  // Seeded from the disk mirror, like the day behind it. The sheet is opened
  // on demand rather than mounted with the tab, so its fetch starts on the
  // click — which made the one screen where the rules are edited paint an empty
  // dialog for a round trip every single time it was opened.
  const [habits, setHabits] = useState<Habit[] | null>(() => readCachedHabits())
  const [title, setTitle] = useState('')
  // Habits still in flight, by the provisional id their row is painted under.
  // A row that does not exist server-side yet cannot be renamed, paused or
  // deleted — those calls name an id the server has never heard of — so it
  // paints with its controls disabled for the instant between the press and
  // the reply. Empty is the ordinary case, and no row is ever in it twice.
  const [pending, setPending] = useState<string[]>([])
  // The same stamp discipline the day plan uses: a fetch commits only while it
  // is still the newest, and every write bumps it. Without it the list refetch
  // an SSE bump provokes would land on top of the row a write has just settled
  // and undo it for a frame.
  const token = useRef(0)
  // The list as it stands, for the writers below — the `planRef` of this sheet,
  // and there for the same reason: a rollback needs the value it is rolling
  // back to without its writer naming `habits` as a dependency.
  const habitsRef = useRef(habits)
  habitsRef.current = habits

  useEffect(() => {
    const mine = ++token.current
    void guard(async () => {
      const hs = await api.habits()
      if (mine !== token.current) return
      // A 200 carrying junk is not something `guard` protects against — it
      // shields us from a rejection — and this array is mapped over on render.
      if (Array.isArray(hs)) setHabits(hs)
    })
  }, [rev, guard])

  // Mirrored back on the trailing edge, exactly as the day is. An empty list is
  // written as empty and reads back as a miss (see `read` in cache.ts), which
  // is the right answer for it: an account with no habits has nothing to paint
  // quickly, and the sheet's own "No habits yet." waits on the fetch as before.
  useEffect(() => {
    // Never while a create is in flight. A pending row wears a provisional id
    // that only this browser has ever heard of, and `pending` is session state
    // — so a mirror written mid-flight would paint that row back on the next
    // open with its controls ENABLED, and every one of them would name an id
    // the server can only 404. The settle a beat later re-runs this with the
    // real row in place.
    if (!habits || pending.length) return
    const t = setTimeout(() => cacheHabits(habits), CACHE_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [habits, pending])

  useEscape(onClose)

  /** Replace one habit in the list in hand, or take it out (`next` null). */
  const put = useCallback((id: string, next: Habit | null) => {
    setHabits((hs) => (hs
      ? (next ? hs.map((h) => (h.id === id ? next : h)) : hs.filter((h) => h.id !== id))
      : hs))
  }, [])

  /**
   * Define a habit. Optimistic, like every other write in this app.
   *
   * A provisional id, because there is nothing to derive the real one from: a
   * task create sends a client_id the server turns into the uid (`uidFor`),
   * and `POST /api/habits` mints its own uuid. So the row is painted under an
   * id only this browser knows, `pending` disables its controls until the DTO
   * arrives, and the reply is swapped in by that id. Appended, because the
   * server appends too (position = max + 1), so the row does not move when the
   * list is next fetched.
   *
   * The box clears on the paint and the line goes back on failure, exactly as
   * the day's own add box does — but only if the field is still empty, so a
   * rejected habit never overwrites the next one already being typed.
   */
  const add = async () => {
    const t = title.trim()
    if (!t) return
    token.current += 1
    const localId = clientId()
    setTitle('')
    setPending((s) => [...s, localId])
    setHabits((hs) => [...(hs ?? []), {
      id: localId, title: t,
      // '' is EVERY DAY — the schedule `create_habit` gives a habit created
      // with no `days`, so this is the value the server is about to store and
      // not a placeholder for one.
      days: '', paused_at: null,
      // The server appends (position = max + 1) and `orderEntries`' analogue
      // here is the fetch order, so a null position simply keeps the row where
      // it was painted: last.
      position: null, estimate_minutes: null,
      created_at: new Date().toISOString(),
    }])
    const h = await guard(() => api.createHabit({ title: t }))
    setPending((s) => s.filter((x) => x !== localId))
    if (!h) {
      // `guard` has already raised the toast. The row comes off — there is no
      // rule behind it — and the line goes back where it was typed.
      setHabits((hs) => hs?.filter((x) => x.id !== localId) ?? hs)
      setTitle((cur) => cur || t)
      return
    }
    setHabits((hs) => hs?.map((x) => (x.id === localId ? h : x)) ?? hs)
  }

  const patch = useCallback(async (h: Habit, body: PatchHabitBody) => {
    const mine = ++token.current
    // Painted BEFORE the round trip, the way this app's other writes are, and
    // here it is load-bearing rather than cosmetic: the day chips derive the
    // `days` they send from the row on screen, so with the row only replaced on
    // the reply, two clicks in quick succession would BOTH start from the
    // pre-patch schedule and the second would send the first one's change back
    // off — last write wins, and the owner watches Monday come back on.
    put(h.id, applyPatch(h, body))
    const next = await guard(() => api.patchHabit(h.id, body))
    // Only while this is still the newest write on this sheet — the same stamp
    // discipline the fetch above keeps, and needed for the same reason once the
    // paint is optimistic. A reply to the FIRST of two quick clicks carries a
    // row that knows nothing of the second, so settling it here would undo that
    // second click for as long as its own reply took: the same flicker, coming
    // from the other end. What stands in the meantime is the optimistic row,
    // which is what was asked for and (`days` is canonicalised on both sides,
    // and a rename is trimmed before it is sent) what the server has; every
    // write here publishes, so the refetch that follows reconciles it anyway.
    if (mine !== token.current) return
    // The server's row on success; on failure the row exactly as it stood when
    // this write began, which is what makes a rejected rename read as "that did
    // not take" rather than as a change that is on the screen and nowhere else.
    put(h.id, next ?? h)
  }, [guard, put])

  const remove = useCallback(async (h: Habit) => {
    token.current += 1
    // Taken off the list BEFORE the round trip, like every other write here.
    // Where it sat is read first, so a refusal puts it back in its own place
    // rather than at the end — the list renders in the order the server gave
    // it, and a restored row that had moved would read as a second change the
    // owner did not make.
    const at = habitsRef.current?.findIndex((x) => x.id === h.id) ?? -1
    put(h.id, null)
    // A 204, so `guard` answers `null` on success and `undefined` on failure. A
    // sentinel rather than telling those two apart by value: `null` vs
    // `undefined` is one refactor away from being lost, and losing it here means
    // a failed delete silently taking the habit off the screen.
    let ok = false
    await guard(async () => { await api.deleteHabit(h.id); ok = true })
    if (ok) return
    setHabits((hs) => {
      if (!hs || hs.some((x) => x.id === h.id)) return hs
      const next = hs.slice()
      next.splice(at < 0 ? next.length : Math.min(at, next.length), 0, h)
      return next
    })
  }, [guard, put])

  /** Whether the press that started this click landed on the scrim itself. */
  const scrimPress = useRef(false)

  return (
    <div className="overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal habit-sheet" role="dialog" aria-modal="true"
        aria-label={tr('today.habits')}
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{tr('today.habits')}</span>
          <button className="icon-btn" onClick={onClose}
            aria-label={tr('common.close')}>✕</button>
        </div>
        <p className="habit-blurb">{tr('habit.sheet.blurb')}</p>
        {habits !== null && habits.length === 0 && (
          <p className="empty habit-empty">{tr('habit.none')}</p>
        )}
        {habits !== null && habits.length > 0 && (
          <ul className="habit-list">
            {habits.map((h) => (
              <HabitEditRow key={h.id} habit={h} pending={pending.includes(h.id)}
                onPatch={(body) => void patch(h, body)} onDelete={() => void remove(h)} />
            ))}
          </ul>
        )}
        <form className="habit-add" onSubmit={(e) => { e.preventDefault(); void add() }}>
          <input className="input" aria-label={tr('habit.newAria')} value={title}
            placeholder={tr('habit.addPlaceholder')}
            onChange={(e) => setTitle(e.target.value)} />
          {/* No in-flight gate any more. The row appears on the press and the
              box is empty behind it, so a second habit can be typed straight
              away — which is what a disabled Add button used to prevent for the
              length of a round trip, on a form whose whole job is entering
              several things in a row. */}
          <button className="btn" type="submit" disabled={!title.trim()}>{tr('common.add')}</button>
        </form>
      </div>
    </div>
  )
}

/** One habit's rule: its name, the days it comes up on, and the two things that
 *  can be done to it that a past day must survive. */
function HabitEditRow({ habit, pending = false, onPatch, onDelete }: {
  habit: Habit
  /** This row is a habit whose create is still in flight, painted under an id
   *  only this browser knows. Every control here names that id on the wire, so
   *  they are all refused until the server's own id arrives — an instant, and
   *  disabled is the honest way to spend it. */
  pending?: boolean
  onPatch: (body: PatchHabitBody) => void
  onDelete: () => void
}) {
  const [name, setName] = useState(habit.title)
  const [confirming, setConfirming] = useState(false)
  const { locale, t: tr } = useI18n()
  // The draft follows the habit when it changes UNDERNEATH — a rejected rename
  // leaves the old title in place, and an SSE bump refetches the whole list — so
  // a stale draft cannot be committed over a newer value on the next blur.
  useEffect(() => { setName(habit.title) }, [habit.title])

  const paused = !!habit.paused_at
  const on = daysOn(habit.days)

  const rename = () => {
    const t = name.trim()
    // An empty title is a 422 server-side. Snapping back beats raising an error
    // toast at someone who has merely cleared the field to retype it.
    if (!t) { setName(habit.title); return }
    if (t !== habit.title) onPatch({ title: t })
  }

  const toggleDay = (d: string) => {
    const next = new Set(on)
    if (next.has(d)) next.delete(d)
    else next.add(d)
    // The vocabulary has no way to say "no days", and does not need one: the
    // chips are a RESTRICTION, so clearing the last of them clears the
    // restriction. All seven lit is the same schedule as none named, and '' is
    // that schedule's only spelling server-side — sending the seven names would
    // come back normalised to '' and the row would appear to change under the
    // owner. Ordered through HABIT_DAYS for the same reason: mon..sun is what
    // the server canonicalises to, so what we send is what comes back.
    onPatch({
      days: next.size === 0 || next.size === HABIT_DAYS.length
        ? ''
        : HABIT_DAYS.filter((x) => next.has(x)).join(','),
    })
  }

  return (
    <li className={`habit-edit ${paused ? 'paused' : ''} ${pending ? 'pending' : ''}`}>
      <div className="habit-edit-top">
        <input className="input habit-name" value={name} disabled={pending}
          aria-label={tr('habit.rename', { habit: habit.title })}
          onChange={(e) => setName(e.target.value)}
          onBlur={rename}
          // Enter commits without leaving the field. There is deliberately no
          // Escape-to-revert here: Escape closes the sheet, as it closes every
          // other dialog in this app, and one control quietly meaning something
          // else is worse than not offering the shortcut at all.
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); rename() } }} />
        <button type="button" className="btn ghost" aria-pressed={paused}
          disabled={pending}
          aria-label={paused
            ? tr('habit.resumeAria', { habit: habit.title })
            : tr('habit.pauseAria', { habit: habit.title })}
          onClick={() => onPatch({ paused: !paused })}>
          {paused ? tr('habit.resume') : tr('habit.pause')}
        </button>
        {/* Two presses, like every other delete in this app. The accessible name
            moves with the state as well as the label does — otherwise a screen
            reader announces the same "Delete Read" twice and the confirm step is
            invisible to exactly the people it protects most. */}
        <button type="button" className={`btn ghost ${confirming ? 'danger' : ''}`}
          disabled={pending}
          aria-label={confirming
            ? tr('habit.confirmDelete', { habit: habit.title })
            : tr('habit.delete', { habit: habit.title })}
          onClick={() => (confirming ? onDelete() : setConfirming(true))}>
          {confirming ? tr('side.reallyDelete') : tr('common.delete')}
        </button>
      </div>
      <div className="habit-days">
        {HABIT_DAYS.map((d) => (
          <button key={d} type="button" className={`chip habit-day ${on.has(d) ? 'on' : ''}`}
            disabled={pending}
            aria-pressed={on.has(d)}
            aria-label={tr('habit.dayFor',
              { day: habitDayLabel(d, locale), habit: habit.title })}
            onClick={() => toggleDay(d)}>{habitDayLabel(d, locale)}</button>
        ))}
        {/* Said in words as well as in chips, because "all seven lit" and "every
            day" are the same schedule and only one of them is legible at a
            glance. Gated on the wire value, not on the set: it is true exactly
            when the habit carries no restriction. */}
        {!habit.days && <span className="label habit-every">{tr('habit.everyDay')}</span>}
        {paused && <span className="label habit-paused">{tr('habit.paused')}</span>}
      </div>
      {confirming && (
        <p className="habit-warn" role="status">
          {tr('habit.deleteWarn')}
        </p>
      )}
    </li>
  )
}
