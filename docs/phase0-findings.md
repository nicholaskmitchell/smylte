# Phase 0 — findings & spec-vs-reality notes

Everything below was measured against a **scratch** Radicale **3.7.4** (vobject
0.9.9), the same versions production runs. Reproduce with the probes under
`backend/dev/` and the suites under `backend/tests/`.

## Empirical findings

1. **Radicale re-serializes every PUT (via vobject 0.9.9).** It reorders
   properties/components, forces CRLF, and rewrites the body — the stored bytes
   are never what you PUT (`dev/radicale_normalization.py`: 615→641 bytes, etc.).
   It does **not** drop real data; the only semantic change observed is stripping
   the *redundant default* `VALUE=DURATION` from `TRIGGER` (DURATION is TRIGGER's
   default value type, so this is lossless).

2. **`icalendar` beats `vobject` for fidelity: 4/4 vs 3/4** on the corpus
   (`dev/ical_fidelity.py`). `vobject` drops `TRIGGER;VALUE=DURATION`; `icalendar`
   keeps it. Both preserve all X-properties, VALARM/VTIMEZONE subcomponents,
   quoted params, GEO, ATTACH, RELATED-TO, etc. → **read and write both use
   `icalendar`.**

3. **412 on a stale `If-Match` is returned** even though the server logs
   `strict preconditions check: False`. The 412 merge path (invariant #5) is
   viable.

4. **An invalid/pruned sync token → `403` with a `DAV:valid-sync-token`
   precondition** in the body. Deleting the on-disk `.Radicale.cache` invalidates
   live tokens — verified end-to-end (invariant #6).

5. **Radicale percent-encodes hrefs** (`@` → `%40`) and hands them back that way.
   We key items on **UID, never href** (invariant #4); created resources use a
   URL-safe hex slug so our cached href already matches Radicale's canonical form.

6. **`supported-calendar-component-set` is NOT enforced on PUT** — a VEVENT PUT
   into a VTODO-only collection returns `201` (`scratch/probe-soren-interaction.sh`).
   "VTODO-only" is advisory: honored by DAVx⁵/Tasks.org, not the server. (This is
   why Søren's calendar tools were hardened to filter task lists client-side.)

## Spec-vs-reality deviations (per §10 — "reality wins, tell me")

- **Invariant #3, "byte-for-byte where the serializer allows":** the serializer
  (Radicale) allows **no** byte-fidelity — it re-serializes every write. We
  therefore guarantee **semantic** fidelity only, enforced by the golden-file
  suite. A surgical text-level writer was considered and rejected as pointless.

- **§4 full resync, "PROPFIND Depth:1 + calendar-multiget":** we enumerate with an
  **empty-token `sync-collection` REPORT** instead, because it returns the member
  list *and* a fresh sync token atomically — closing a race where a PROPFIND
  snapshot and a separately-fetched token can disagree. A PROPFIND-based
  `list_etags()` is implemented too, for GC/reconciliation.

- **Invariant #1 vs the sidecar (a real tension in the spec):** the *cache* tables
  (collections, items, categories, items_fts, sync_state) are fully derivable —
  wipe them, resync, get identical state. The *sidecar* tables (kanban column,
  manual sort, pins, per-list settings) are app-only and exist **nowhere on the
  wire**, so a resync **cannot** rebuild them. They are the one thing in SQLite
  that is *not* disposable. **Consequence for §9 backups:** backing up only the
  `.ics` directory loses kanban/sort/pin state on a SQLite wipe. Either also back
  up the sidecar tables, or accept that those are best-effort. Flagging for a
  decision when we reach deployment.

## What Phase 0 delivers

- `tasksd.dav` — hand-rolled CalDAV client (PROPFIND, sync-collection,
  calendar-multiget, GET/PUT/DELETE with If-Match, MKCALENDAR VTODO-only).
- `tasksd.ical` — icalendar read/extract + invariant-#2 edit path + an independent
  canonicalizer that judges fidelity.
- `tasksd.db` — SQLite (WAL, FTS5) cache + decoupled sidecar, raw sqlite3.
- `tasksd.sync` — incremental + full-resync + invalid-token fallback + orphan GC,
  and the write path with 412 merge.
- 24 tests green, including a concurrent-writer fuzz that never loses a property.

Not started (correctly): any UI, the FastAPI server/SSE, deployment (§9), and
**recurrence (§6 — gated, needs real-device captures).**
