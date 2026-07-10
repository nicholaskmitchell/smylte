# Recurrence findings — GATED (spec §6)

**Status: not started, intentionally.** Per §6 and §7 (Phase 4), recurrence must
not be implemented until the investigation below is done against **real** clients
and the design is approved.

The investigation needs actual device captures, which we do not have yet:

1. Scratch Radicale with a test user — **available** (`~/tasks/scratch`, :5233).
2. Connect **Tasks.org via DAVx⁵** and **Thunderbird** — pending real devices.
3. Capture exact PUT bodies for: create `RRULE:FREQ=WEEKLY`; complete one
   occurrence; complete a second; edit an unrelated field on a task carrying an
   unknown `X-` property.
4. Record here: does each client mutate `DTSTART` on the master, write a
   `RECURRENCE-ID` override, or something else? Does it preserve `X-` props?
5. Propose a design. **Stop and wait for approval.**

Groundwork already in place (unused until approval): the `completions` table
exists in the schema, and `TaskFields.has_rrule` is extracted. The straw-man in
§6 ("one master VTODO, no RECURRENCE-ID overrides, app owns advancement") is the
starting hypothesis to argue against once we have the captures.
