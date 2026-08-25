# Recurrence — VEVENT implemented; VTODO still gated (spec §6)

**Status: calendar-event (VEVENT) recurrence is implemented. Task (VTODO)
recurrence and its completion-advancement semantics remain gated.**

## What ships now (VEVENT)

Recurring events created in any CalDAV client (Apple Calendar, Thunderbird,
DAVx⁵ …) already reach Radicale correctly — the gap was that this app never
expanded them, so a series vanished from every month except the one holding its
first occurrence. That is fixed, end to end:

- **Display / expand.** `ical/recur.py::expand_occurrences` fans a resource's
  cached `raw_ics` out into the occurrences in a `[start, end)` window, honouring
  RRULE, RDATE, EXDATE, RECURRENCE-ID overrides (moved/edited/cancelled), all-day
  vs timed, and timezones/DST. Built on `recurring-ical-events` (on top of the
  `icalendar` objects we already parse). `store.get_events_in_range` now admits a
  recurring master on the window's upper bound alone (a past DTSTART no longer
  excludes it); `service.events_in_range` emits one DTO per occurrence with a
  stable per-instance `id` (`uid::recurrence_id`).
- **Author.** The New-Event modal has a Repeat control (daily/weekly/monthly/
  yearly + optional "until"); `ical.rrule_from_spec` → `RRULE` on the master.
- **Per-occurrence editing** ("this event" / "this & following" / "all events"):
  `apply_occurrence_override` (RECURRENCE-ID override), `exclude_occurrence`
  (EXDATE), and `split_series` (UNTIL-bounded head + new-UID tail). All are pure
  `(raw, …) -> bytes`, so the engine's 412-merge path (invariant #5) still holds,
  and foreign props survive (invariant #2).

Verified by `tests/test_recur.py` (pure) and the recurring cases in
`tests/test_api.py` (round-tripped through real Radicale).

### Known limitations (VEVENT)
- The edit modal doesn't surface a recurring event's exact current FREQ, so
  editing it shows "Keep current schedule" (leaving the rule untouched) rather
  than pre-selecting the frequency.

Two entries that used to sit here no longer describe the code:

- **COUNT across a split.** A COUNT-bounded series now keeps its overall length
  through "this & following": the tail's COUNT is the original minus what the
  head consumed (`edit.py::split_series`), and RDATE/EXDATE entries are
  partitioned by the anchor. Pinned by
  `test_split_count_series_tail_is_bounded`.
- **Pathological rules.** Nothing is truncated to a bounded prefix. A resource is
  **refused up front** and the caller degrades to the master row — the calendar
  draws one row, and the booking page's busy set treats the series as covering
  the whole window, which withholds availability rather than handing it out. The
  test is `test_subdaily_rule_is_refused_not_expanded`. The judgement is on the
  rule's shape, not its FREQ name, and there are four guards, not one: more than
  24 instances a day (so `FREQ=SECONDLY`/`MINUTELY`, but equally any FREQ
  expanded past that by BYHOUR/BYMINUTE/BYSECOND); `INTERVAL < 1`, which Radicale
  accepts and which never terminates; a walk from DTSTART to the window over
  200k instances; and a dateutil search running past 5000 periods without
  yielding an occurrence. An RDATE list too long to fit the window's occurrence
  cap is refused on the same terms.

## Still GATED — VTODO (task) recurrence

Task recurrence (completion advancement, the `completions` ledger, per-task
RECURRENCE-ID semantics) is **not** implemented and must not be until the
device-capture investigation below is done and the design approved. The straw-man
in §6 ("one master VTODO, no RECURRENCE-ID overrides, app owns advancement") is
the starting hypothesis to argue against once we have captures:

1. Scratch Radicale with a test user — available (`~/tasks/scratch`, :5233).
2. Connect **Tasks.org via DAVx⁵** and **Thunderbird** — pending real devices.
3. Capture exact PUT bodies for: create `RRULE:FREQ=WEEKLY`; complete one
   occurrence; complete a second; edit an unrelated field on a task carrying an
   unknown `X-` property.
4. Record whether each client mutates `DTSTART` on the master, writes a
   `RECURRENCE-ID` override, or something else, and whether `X-` props survive.
5. Propose a design. **Stop and wait for approval.**

The `completions` table and `TaskFields.has_rrule` remain the groundwork.
