import { describe, expect, it } from 'vitest'
import { compareTasks, sortByCompletion, sortTasks } from './order'
import type { Task } from './api'

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  // Present on every DTO the server sends; see api.ts's Task.
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
 
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const uids = (ts: Task[]) => sortTasks(ts).map((t) => t.uid)

describe('the key chain', () => {
  it('puts a manual position ahead of everything else', () => {
    // Dragging is the user saying it outright, so it outranks the due date.
    const a = task({ uid: 'a', sort_order: 2, due: '2026-01-01' })
    const b = task({ uid: 'b', sort_order: 1, due: '2026-12-31' })
    expect(uids([a, b])).toEqual(['b', 'a'])
  })

  it('places an unplaced task among the placed ones, by when it is due', () => {
    // CHANGED, deliberately. This used to assert the opposite — that an unplaced
    // task sorts after every placed one. That was defensible while most tasks
    // were unplaced, but a drag renumbers the WHOLE account (the server's
    // ReorderTasks model: "nothing left null once a drag lands"), so afterwards a
    // null position means "created since the last drag" and sinking those to the
    // bottom of every view buried every new task.
    const placed = task({ uid: 'placed', sort_order: 5, due: '2026-12-31' })
    const loose = task({ uid: 'loose', due: '2026-01-01' })
    expect(uids([loose, placed])).toEqual(['loose', 'placed'])
  })

  it('still sends an unplaced task to the end when it is later than everything', () => {
    // The other half: placing by due date is not "always first". An unplaced task
    // later than every placed one lands where it always did.
    const placed = task({ uid: 'placed', sort_order: 5, due: '2026-01-01' })
    const loose = task({ uid: 'loose', due: '2026-12-31' })
    expect(uids([loose, placed])).toEqual(['placed', 'loose'])
  })

  it('keeps the manual order of placed tasks intact', () => {
    // The guarantee dragging depends on: an unplaced task threading between them
    // must never reshuffle the ones the user put in order by hand.
    const a = task({ uid: 'a', sort_order: 1, due: '2026-12-01' })
    const b = task({ uid: 'b', sort_order: 2, due: '2026-02-01' })
    const c = task({ uid: 'c', sort_order: 3, due: '2026-06-01' })
    const loose = task({ uid: 'loose', due: '2026-03-01' })
    const out = uids([c, loose, a, b])
    expect(out.filter((u) => u !== 'loose')).toEqual(['a', 'b', 'c'])
  })

  it('is a total order — any shuffle of the same set sorts identically', () => {
    // The property the module exists for, now that sortTasks assigns an
    // effective position rather than comparing pairwise. A non-transitive
    // comparator would make Array.sort implementation-defined, and this is what
    // would catch it.
    const set = [
      task({ uid: 'p1', sort_order: 1, due: '2026-12-01' }),
      task({ uid: 'p2', sort_order: 2, due: '2026-01-15' }),
      task({ uid: 'u1', due: '2026-06-01' }),
      task({ uid: 'u2', due: null }),
      task({ uid: 'u3', due: '2026-01-01' }),
    ]
    const expected = uids(set)
    for (const shuffle of [[4, 0, 3, 1, 2], [2, 3, 4, 1, 0], [1, 4, 0, 2, 3]]) {
      expect(uids(shuffle.map((i) => set[i]))).toEqual(expected)
    }
  })

  it('falls through to due date when nothing is placed', () => {
    const a = task({ uid: 'a', due: '2026-07-11' })
    const b = task({ uid: 'b', due: '2026-07-09' })
    const c = task({ uid: 'c', due: '2026-07-10' })
    expect(uids([a, b, c])).toEqual(['b', 'c', 'a'])
  })

  it('puts undated tasks last, not first', () => {
    // TasksView used to put them first and HomeView last, so the same task sat
    // at opposite ends of the two tabs.
    const dated = task({ uid: 'dated', due: '2026-07-11' })
    const undated = task({ uid: 'undated' })
    expect(uids([undated, dated])).toEqual(['dated', 'undated'])
  })

  it('puts an all-day due ahead of a timed one on the same day', () => {
    const allDay = task({ uid: 'allday', due: '2026-07-11', due_is_date: true })
    const timed = task({ uid: 'timed', due: '2026-07-11T09:00', due_is_date: false })
    expect(uids([timed, allDay])).toEqual(['allday', 'timed'])
  })

  it('orders a zone-anchored due by the instant it names, not its spelling', () => {
    // A due another CalDAV client wrote carries an offset, and raw strings sort
    // those wrong: "2026-07-11T23:00:00-07:00" is 06:00 UTC on the 12th — five
    // hours *after* "2026-07-12T01:00:00Z" — yet it compares first as text.
    const earlier = task({ uid: 'earlier', due: '2026-07-12T01:00:00Z', due_is_date: false })
    const later = task({ uid: 'later', due: '2026-07-11T23:00:00-07:00', due_is_date: false })
    expect(uids([later, earlier])).toEqual(['earlier', 'later'])
    // And the text order really is the other way round, so this is a live trap
    // rather than a hypothetical one.
    expect(later.due! < earlier.due!).toBe(true)
  })

  it('breaks a due-date tie on priority, unset last', () => {
    // iCal PRIORITY: 1 is the highest, 9 the lowest, 0/absent is unset.
    const high = task({ uid: 'high', due: '2026-07-11', priority: 1 })
    const low = task({ uid: 'low', due: '2026-07-11', priority: 9 })
    const none = task({ uid: 'none', due: '2026-07-11', priority: null })
    const zero = task({ uid: 'zero', due: '2026-07-11', priority: 0 })
    // 0 means unset too, so it lands with `none` and the two settle on uid.
    expect(uids([none, low, zero, high])).toEqual(['high', 'low', 'none', 'zero'])
  })

  it('breaks a priority tie on title, untitled last', () => {
    const b = task({ uid: 'b', due: '2026-07-11', summary: 'Beta' })
    const a = task({ uid: 'a', due: '2026-07-11', summary: 'Alpha' })
    const blank = task({ uid: 'blank', due: '2026-07-11', summary: '' })
    const none = task({ uid: 'none', due: '2026-07-11', summary: null })
    expect(uids([none, b, blank, a])).toEqual(['a', 'b', 'blank', 'none'])
  })
})

describe('totality — the property the list view depends on', () => {
  // The reported bug was a task painting in one place and jumping to another
  // once the server caught up. That is only possible while two distinct tasks
  // can compare equal and keep whatever order the array gave them.

  const sample = (): Task[] => [
    task({ uid: 'a', due: '2026-07-11', summary: 'Same', priority: 5 }),
    task({ uid: 'b', due: '2026-07-11', summary: 'Same', priority: 5 }),
    task({ uid: 'c', due: '2026-07-11', summary: 'Same', priority: 5 }),
    task({ uid: 'd', due: null, summary: null }),
    task({ uid: 'e', sort_order: 3 }),
    task({ uid: 'f', sort_order: 1 }),
    task({ uid: 'g', due: '2026-01-01T08:30', due_is_date: false }),
  ]

  it('never calls two distinct tasks equal', () => {
    const ts = sample()
    for (const x of ts) {
      for (const y of ts) {
        if (x.uid === y.uid) expect(compareTasks(x, y)).toBe(0)
        else expect(compareTasks(x, y)).not.toBe(0)
      }
    }
  })

  it('gives the same sequence whatever order the array arrived in', () => {
    const want = uids(sample())
    // Every rotation and the reverse — enough to catch an order that leans on
    // Array#sort's stability rather than on the comparator.
    const ts = sample()
    for (let i = 0; i < ts.length; i++) {
      expect(uids([...ts.slice(i), ...ts.slice(0, i)])).toEqual(want)
    }
    expect(uids([...ts].reverse())).toEqual(want)
  })

  it('is antisymmetric', () => {
    const ts = sample()
    for (const x of ts) {
      for (const y of ts) {
        // Summed rather than negated and compared: Math.sign(0) is +0 and
        // -Math.sign(0) is -0, which toBe separates but nothing else does.
        expect(Math.sign(compareTasks(x, y)) + Math.sign(compareTasks(y, x))).toBe(0)
      }
    }
  })
})

describe('sortTasks', () => {
  it('returns a new array and leaves the input alone', () => {
    // Callers pass arrays straight out of state; sorting in place would mutate
    // React's own copy.
    const ts = [task({ uid: 'b', due: '2026-07-11' }), task({ uid: 'a', due: '2026-01-01' })]
    const out = sortTasks(ts)
    expect(out).not.toBe(ts)
    expect(ts.map((t) => t.uid)).toEqual(['b', 'a'])
    expect(out.map((t) => t.uid)).toEqual(['a', 'b'])
  })
})

describe('sortByCompletion', () => {
  const done = (o: Partial<Task> = {}) =>
    task({ completed: true, status: 'COMPLETED', ...o })

  it('puts the most recently completed first', () => {
    const ts = [
      done({ uid: 'old', completed_at: '2026-08-01T09:00:00Z' }),
      done({ uid: 'new', completed_at: '2026-08-20T09:00:00Z' }),
      done({ uid: 'mid', completed_at: '2026-08-10T09:00:00Z' }),
    ]
    expect(sortByCompletion(ts).map((t) => t.uid)).toEqual(['new', 'mid', 'old'])
  })

  it('ranks a stamped task above an unstamped one, whatever its due date', () => {
    // The two groups measure different quantities — a completion instant and a
    // deadline — so they are never interleaved. A task finished in January still
    // outranks one that merely fell due in December but recorded no stamp.
    const stamped = done({ uid: 'stamped', completed_at: '2026-01-01T09:00:00Z',
      due: '2026-01-01' })
    const bare = done({ uid: 'bare', completed_at: null, due: '2026-12-31' })
    expect(sortByCompletion([bare, stamped]).map((t) => t.uid)).toEqual(['stamped', 'bare'])
  })

  it('falls back to due-descending for unstamped tasks, undated last', () => {
    // The behaviour this ordering had everywhere before COMPLETED was exposed;
    // it still has to hold, because a CANCELLED task never gets a stamp and a
    // foreign client may write STATUS:COMPLETED without one.
    const ts = [
      done({ uid: 'undated', completed_at: null, due: null }),
      done({ uid: 'early', completed_at: null, due: '2026-01-01' }),
      done({ uid: 'late', completed_at: null, due: '2026-12-31' }),
    ]
    expect(sortByCompletion(ts).map((t) => t.uid)).toEqual(['late', 'early', 'undated'])
  })

  it('treats a cancelled task as unstamped', () => {
    // Cancelling is not completing, so `ical/edit.py` writes no COMPLETED for it.
    const cancelled = task({ uid: 'cancelled', cancelled: true, status: 'CANCELLED',
      completed_at: null, due: '2026-12-31' })
    const finished = done({ uid: 'finished', completed_at: '2026-01-01T09:00:00Z' })
    expect(sortByCompletion([cancelled, finished]).map((t) => t.uid))
      .toEqual(['finished', 'cancelled'])
  })

  it('is a total order when two tasks share an instant', () => {
    // Same guarantee `compareTasks` exists for: two rows completed in the same
    // second must not swap places between renders, whatever order they arrive in.
    const at = '2026-08-20T09:00:00Z'
    const a = done({ uid: 'a', summary: 'Alpha', completed_at: at })
    const b = done({ uid: 'b', summary: 'Bravo', completed_at: at })
    expect(sortByCompletion([a, b]).map((t) => t.uid))
      .toEqual(sortByCompletion([b, a]).map((t) => t.uid))
  })

  it('ignores an unparseable stamp rather than sorting it to the top', () => {
    // NaN compares false against everything, so an unusable value has to drop to
    // the fallback group instead of poisoning the comparator.
    const bad = done({ uid: 'bad', completed_at: 'not a date', due: '2026-01-01' })
    const good = done({ uid: 'good', completed_at: '2026-01-01T09:00:00Z' })
    expect(sortByCompletion([bad, good]).map((t) => t.uid)).toEqual(['good', 'bad'])
  })

  it('returns a new array and leaves the input alone', () => {
    const ts = [
      done({ uid: 'a', completed_at: '2026-01-01T09:00:00Z' }),
      done({ uid: 'b', completed_at: '2026-08-01T09:00:00Z' }),
    ]
    const out = sortByCompletion(ts)
    expect(out).not.toBe(ts)
    expect(ts.map((t) => t.uid)).toEqual(['a', 'b'])
    expect(out.map((t) => t.uid)).toEqual(['b', 'a'])
  })
})
