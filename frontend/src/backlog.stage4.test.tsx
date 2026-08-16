/**
 * Stage 4 of the audit backlog: user-visible correctness and rendering.
 *
 * HOW THESE TESTS WORK. Each one asserts the CORRECT behaviour and is written
 * with vitest's `it.fails`, the frontend counterpart of the backend's
 * `xfail(strict=True)`:
 *
 *   - while the bug is open  -> the body throws -> `it.fails` passes -> CI green;
 *   - the moment it is fixed -> the body passes -> `it.fails` FAILS the build,
 *     so a finding cannot be quietly fixed without being ticked off in
 *     docs/AUDIT.md and its marker removed.
 *
 * TWO STRENGTHS OF PIN, and the difference matters when reading a green run:
 *
 *   BEHAVIOURAL — drives the real code and asserts the real result. Strong.
 *   STRUCTURAL  — reads the component source and asserts the shape that causes
 *                 the defect (an `onClick` scrim, a `key` derived from a
 *                 non-unique id, a missing Escape handler). Weaker: it pins the
 *                 CAUSE rather than the SYMPTOM, and a fix shaped differently
 *                 from the one anticipated will XPASS and need reclassifying —
 *                 which is the harness working, not a false alarm.
 *
 * The structural ones are here because the drag-and-drop and data-provider
 * harness they would need does not exist yet; building it is tracked as its own
 * Stage 4 entry in docs/STAGES.md. They are deterministic and they run in CI
 * today, which beats an unpinned finding.
 *
 * See docs/STAGES.md for the staging and backend/tests/test_backlog_stage1.py
 * for the same harness on the Python side.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { isValidValue } from './appearance'

const read = (rel: string) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')

const tasksView = read('./components/TasksView.tsx')
const calendarView = read('./components/CalendarView.tsx')
const taskModal = read('./components/TaskModal.tsx')
const scheduling = read('./components/SchedulingView.tsx')
const data = read('./data.tsx')

// ── behavioural ────────────────────────────────────────────────────────────

describe('stage 4 — appearance (behavioural)', () => {
  // AUDIT open: appearance.ts:289
  it.fails('rejects a word that is not a real CSS color', () => {
    // `isColor` accepts /^[a-z]{3,20}$/i wholesale so that `transparent`,
    // `currentColor` and the named colors pass. A typo or an invented name is
    // therefore stored as an override and written into the CSSOM, where the
    // browser discards it — silently blanking that token, with nothing in the
    // editor to say why.
    expect(isValidValue('color', 'notacolour')).toBe(false)
    expect(isValidValue('color', 'bluu')).toBe(false)
    expect(isValidValue('color', 'reddish')).toBe(false)
  })

  it('still accepts the keywords the loose rule exists for', () => {
    // The control: whatever replaces the pattern must keep these working, or
    // the "fix" is a regression.
    for (const ok of ['transparent', 'currentColor', 'red', 'rebeccapurple']) {
      expect(isValidValue('color', ok)).toBe(true)
    }
  })
})

// ── structural ─────────────────────────────────────────────────────────────

describe('stage 4 — calendar rendering (structural)', () => {
  // AUDIT open: CalendarView.tsx:470
  it.fails('keys calendar chips by collection as well as uid', () => {
    // `id` is documented in api.ts as "unique per rendered instance (uid, or
    // `uid::recurrence_id`)" — unique per SERIES, not per collection. A UID is
    // only unique within one collection, and copying an event between
    // calendars (or subscribing to a shared one) puts the same UID in two. Both
    // chips then render with the same React key: React drops one and can bind
    // the wrong click target to the other.
    const chipKey = /<div key=\{([^}]+)\} className=\{`cal-ev/.exec(calendarView)
    expect(chipKey, 'the cal-ev chip key expression').not.toBeNull()
    expect(chipKey![1]).toMatch(/calendar|cal\b|href/)
  })
})

describe('stage 4 — modal contract (structural)', () => {
  // AUDIT open: TaskModal.tsx:118
  it.fails('does not close the task modal on a stray scrim click', () => {
    // `<div className="overlay" onClick={onClose}>` fires on any click whose
    // mouseUP lands on the scrim — including a text drag-select that started
    // inside the modal and finished outside it. The whole half-typed task is
    // discarded. A press/release pair that begins inside must not close it.
    const overlay = /<div className="overlay"([^>]*)>/.exec(taskModal)
    expect(overlay, 'the TaskModal overlay element').not.toBeNull()
    expect(overlay![1]).toMatch(/onMouseDown|onPointerDown/)
  })

  // AUDIT open: SchedulingView.tsx:235
  it.fails('gives the booking-link editor the modal contract', () => {
    // Every other modal here is a labelled dialog that Escape closes (see
    // TabsModal's `onKey`). The booking-link editor — the longest form in the
    // app — has no role, no aria-modal and no Escape handler, over a scrim that
    // discards it on any click. Screen readers announce it as a plain div.
    const modal = /<div className="modal sched-modal"([^>]*)>/.exec(scheduling)
    expect(modal, 'the sched-modal element').not.toBeNull()
    expect(modal![1], 'role/aria-modal on the booking-link editor').toMatch(/role="dialog"/)
    expect(scheduling, 'an Escape handler').toMatch(/Escape/)
  })

  // AUDIT open: SchedulingView.tsx:348
  it.fails('guards the create-link button against a double submit', () => {
    // `disabled={!valid}` bounds validity, not flight. A double-click, or Enter
    // pressed twice, calls `save()` twice and publishes two live booking links
    // with two public URLs — one of which nobody knows is out there.
    const button = /<button className="btn" disabled=\{([^}]*)\} onClick=\{save\}/
      .exec(scheduling)
    expect(button, 'the Create link / Save button').not.toBeNull()
    expect(button![1], 'the disabled expression').toMatch(/saving|busy|pending|inFlight/i)
  })
})

describe('stage 4 — task list interaction (structural)', () => {
  // AUDIT open: TasksView.tsx:518
  it.fails('draws the drop indicator on the side the row will land', () => {
    // The row gets a single `drag-over` class regardless of direction, and the
    // stylesheet draws it above the target — but a downward drag inserts BELOW.
    // Every downward drag lands one row from where it was shown to land.
    expect(tasksView).toMatch(/drag-over-(above|below)|dropBelow|insertAfter/)
  })

  // AUDIT open: TasksView.tsx:521
  it.fails('does not start a row drag from inside the add-subtask field', () => {
    // `draggable` sits on the row wrapper, so a press inside the nested inline
    // input starts a drag of the PARENT task. Selecting text in that field
    // silently reorders the list. The handler has to ignore a drag whose target
    // is an interactive descendant.
    const onDragStart = /onDragStart=\{drag && \(\(e\) => \{([\s\S]{0,400}?)\}\)\}/
      .exec(tasksView)
    expect(onDragStart, 'the row onDragStart handler').not.toBeNull()
    expect(onDragStart![1]).toMatch(/target|closest|INPUT|TEXTAREA/i)
  })

  // AUDIT open: TasksView.tsx:91
  it.fails('does not prune list settings against a failed lists fetch', () => {
    // `listsLoaded` is set whether the fetch SUCCEEDED or failed, and the prune
    // then runs against whatever the stale disk cache held. Lists missing from
    // that snapshot are pruned out of hiddenLists and the groups — and the
    // pruned blob is written back to the server, so a transient 500 during
    // startup permanently loses the user's grouping.
    const guard = /if \(!listsLoaded \|\| !lists\.length\) return/.exec(tasksView)
    expect(guard, 'the prune guard').not.toBeNull()
    expect(tasksView).toMatch(/listsFetchOk|listsError|loadedFromServer|fetchSucceeded/)
  })
})

describe('stage 4 — task data provider (structural)', () => {
  // AUDIT open: data.tsx:457
  it.fails('assigns manual positions only to the tasks that need them', () => {
    // A drag renumbers `placed` 1..N across EVERY task on the account, so every
    // task afterwards has a sort_order and every newly created one (which has
    // none) sorts to the very bottom of every view, forever. The renumber has
    // to be bounded to the moved span.
    const renumber = /const next = placed\.map\(\(t, i\) => \(\{ \.\.\.t, sort_order: i \+ 1 \}\)\)/
    expect(data, 'the whole-array renumber').not.toMatch(renumber)
  })

  // AUDIT open: data.tsx:465
  it.fails('rolls back only the reordered rows, not the whole array', () => {
    // `const rollback = tasks` snapshots the entire array before the request.
    // Any write that lands while the reorder is in flight — an SSE update, a
    // completed task, an edit from another tab — is inside that snapshot and is
    // silently reverted when the reorder fails.
    expect(data, 'the whole-array rollback snapshot').not.toMatch(/const rollback = tasks\b/)
  })

  // AUDIT open: data.tsx:533
  it.fails('records a window as fetched only when its result was kept', () => {
    // `fetchWindow` drops a superseded result with `if (gen.current !== mine)
    // return`, but `asked` has already recorded the window as requested. Coming
    // back to that month never refetches, so the grid stays empty — until
    // something unrelated bumps `rev`.
    const stale = /if \(gen\.current !== mine\) return/.exec(data)
    expect(stale, 'the staleness guard').not.toBeNull()
    // A per-window guard compares the key, not just one global generation.
    expect(data).toMatch(/latest\.current === key|asked\.current\.delete\(key\)/)
  })
})
