import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest'
import {
  CACHE_PREFIX, CACHE_VERSION, MAX_BYTES, MAX_ROWS,
  cacheCalendars, cacheDayPlan, cacheDayRange, cacheEvents, cacheHabits,
  cacheLists, cacheTasks, clearCache,
  readCachedCalendars, readCachedDayPlan, readCachedDayRange, readCachedEvents,
  readCachedHabits, readCachedLists, readCachedTasks,
  sanitizeDayEntry, sanitizeDayPlan, sanitizeEvent, sanitizeHabit, sanitizeList,
  sanitizeTask, setCacheUser, sweepOldVersions,
} from './cache'
import type { CalEvent, DayEntry, DayPlan, Habit, List, Task } from './api'

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  // Present on every DTO the server sends; see api.ts's Task.
  completed_at: null, kanban_column: null, estimated_minutes: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = (o: Partial<List> = {}): List => ({
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F', ...o,
})

const event = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'e1', id: 'e1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Lunch', description: null, location: null, start: '2026-07-15',
  start_is_date: true, end: '2026-07-16', end_is_date: true, duration: null, all_day: true,
  status: null, tags: [], has_rrule: false, href: '/c1/e1.ics', etag: '"1"', ...o,
})

const dayEntry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'e1', day: '2026-08-21', kind: 'note', list: null, uid: null,
  title: 'Water the plants', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, rolled_to: null,
  estimate_minutes: null, created_at: '2026-08-21T08:00:00.000Z', ...o,
})

const dayPlan = (o: Partial<DayPlan> = {}): DayPlan => ({
  day: '2026-08-21', planned: true, capacity_minutes: null, capacity: null,
  committed_at: null, shutdown_at: null, reflection: null, entries: [], ...o,
})

const habit = (o: Partial<Habit> = {}): Habit => ({
  id: 'hb1', title: 'Read', days: '', paused_at: null, position: 1,
  estimate_minutes: null, created_at: '2026-08-01T08:00:00.000Z', ...o,
})

const keyOf = (kind: string, user = 'nick') =>
  `${CACHE_PREFIX}:${CACHE_VERSION}:${user}:${kind}`

beforeEach(() => {
  localStorage.clear()
  setCacheUser('nick')
})

afterEach(() => vi.restoreAllMocks())

describe('cache round trip', () => {
  it('returns what it stored', () => {
    cacheTasks([task({ uid: 'a' }), task({ uid: 'b', summary: null })])
    const back = readCachedTasks()
    expect(back).toHaveLength(2)
    expect(back![0].uid).toBe('a')
    expect(back![1].summary).toBeNull()

    cacheLists([list()])
    expect(readCachedLists()![0].name).toBe('Work')
    cacheCalendars([list({ id: 'c1', href: '/c1/', is_calendar: true })])
    expect(readCachedCalendars()![0].id).toBe('c1')
  })

  it('misses with no user set, so one account never reads another\'s', () => {
    cacheTasks([task()])
    setCacheUser('')
    expect(readCachedTasks()).toBeNull()
    setCacheUser('someone-else')
    expect(readCachedTasks()).toBeNull()
    setCacheUser('nick')
    expect(readCachedTasks()).toHaveLength(1)
  })
})

describe('cache reads defensively', () => {
  it('treats an unparseable blob as a miss', () => {
    localStorage.setItem(keyOf('tasks'), '{not json')
    expect(readCachedTasks()).toBeNull()
  })

  it('drops rows that are not tasks, keeping the ones that are', () => {
    localStorage.setItem(keyOf('tasks'), JSON.stringify({
      at: Date.now(),
      rows: [task({ uid: 'good' }), null, 42, 'nope', { uid: 'no-list' }, []],
    }))
    const back = readCachedTasks()
    expect(back).toHaveLength(1)
    expect(back![0].uid).toBe('good')
  })

  it('rebuilds every field to its own type rather than trusting it', () => {
    // The blob is writable by anything with script on this origin, and these
    // values reach `t.due.includes('T')` and `t.tags.map(...)` unguarded.
    const t = sanitizeTask({
      uid: 'u', list: 'l', tags: ['ok', 7, null], due: 12345, completed: 'yes',
      child_count: 'lots', children: 'nope', priority: NaN,
    })
    expect(t).not.toBeNull()
    expect(t!.tags).toEqual(['ok'])
    expect(t!.due).toBeNull()
    expect(t!.completed).toBe(false)   // only a real `true` counts
    expect(t!.child_count).toBe(0)
    expect(t!.children).toEqual([])
    expect(t!.priority).toBeNull()     // NaN is not a usable number
  })

  it('carries the manual position through the disk cache', () => {
    // sanitizeTask rebuilds field by field, so anything not listed there is
    // silently dropped. sort_order going missing would make manual order work
    // on a fresh load and vanish on a cached one — the hardest kind of bug to
    // see, because a reload fixes it.
    expect(sanitizeTask({ uid: 'u', list: 'l', sort_order: 3 })!.sort_order).toBe(3)
    expect(sanitizeTask({ uid: 'u', list: 'l' })!.sort_order).toBeNull()
    expect(sanitizeTask({ uid: 'u', list: 'l', sort_order: 'third' })!.sort_order).toBeNull()
    expect(sanitizeTask({ uid: 'u', list: 'l', start_is_date: true })!.start_is_date).toBe(true)

    cacheTasks([task({ sort_order: 7, start_is_date: false })])
    const back = readCachedTasks()!
    expect(back[0].sort_order).toBe(7)
    expect(back[0].start_is_date).toBe(false)
  })

  it('refuses a row missing the fields everything keys on', () => {
    expect(sanitizeTask({ list: 'l1' })).toBeNull()          // no uid
    expect(sanitizeTask({ uid: 'u1' })).toBeNull()           // no list
    expect(sanitizeTask({ uid: '', list: 'l1' })).toBeNull() // empty is not an id
    expect(sanitizeList({ id: 'l1' })).toBeNull()            // no href
    expect(sanitizeEvent({ uid: 'e1', id: 'e1' })).toBeNull()  // no calendar
    expect(sanitizeTask('nope')).toBeNull()
    expect(sanitizeTask(null)).toBeNull()
  })

  it('reports a blob that sanitizes to nothing as a miss, not an empty account', () => {
    // Otherwise a corrupt entry paints "Nothing to do here." with confidence.
    localStorage.setItem(keyOf('tasks'), JSON.stringify({ at: Date.now(), rows: ['junk'] }))
    expect(readCachedTasks()).toBeNull()
    localStorage.setItem(keyOf('tasks'), JSON.stringify({ at: Date.now(), rows: [] }))
    expect(readCachedTasks()).toBeNull()
  })

  it('expires an entry left by a session nobody came back to', () => {
    const old = Date.now() - 15 * 24 * 60 * 60 * 1000
    localStorage.setItem(keyOf('tasks'), JSON.stringify({ at: old, rows: [task()] }))
    expect(readCachedTasks()).toBeNull()
    expect(localStorage.getItem(keyOf('tasks'))).toBeNull()   // and reclaimed
  })

  it('ignores an entry with no timestamp at all', () => {
    localStorage.setItem(keyOf('tasks'), JSON.stringify({ rows: [task()] }))
    expect(readCachedTasks()).toBeNull()
  })
})

describe('cache writes stay bounded', () => {
  it('leaves the byte ceiling something to do', () => {
    // THE TWO BOUNDS ARE MEANT TO BE INDEPENDENT: the row cap is the ordinary
    // one and the byte ceiling catches the outliers above it. That only holds
    // while a full row-capped payload of ORDINARY rows fits under the ceiling
    // with room to spare — and it had silently stopped holding. 2000 plain
    // tasks came to ~1.02 MB against a 1 MiB ceiling, three per cent under, so
    // adding ONE nullable field to `Task` pushed every row-capped write over it
    // and disabled the task cache outright. Silently, because an over-ceiling
    // payload is refused whole: the symptom is a mirror that stops painting.
    //
    // Asserted as a RATIO against the real constants rather than as a byte
    // count, so this keeps testing the relationship the design depends on
    // rather than a number that ages out the moment either cap moves.
    const full = JSON.stringify({
      at: Date.now(),
      rows: Array.from({ length: MAX_ROWS }, (_, i) => task({ uid: `u${i}` })),
    })
    expect(full.length).toBeLessThan(MAX_BYTES * 0.75)
  })

  it('caps the row count', () => {
    cacheTasks(Array.from({ length: 2500 }, (_, i) => task({ uid: `u${i}` })))
    expect(readCachedTasks()).toHaveLength(2000)
  })

  it('skips an oversized payload and drops the entry it could not replace', () => {
    // Half-written JSON is not a document, so bytes cannot be truncated the way
    // rows can; the entry has to go rather than outlive the data it lost to.
    cacheTasks([task({ uid: 'small' })])
    expect(readCachedTasks()).toHaveLength(1)
    // Sized FROM the ceiling, not tuned to whatever it happened to be. This
    // line used to read `1100 * 1024`, chosen against a 1 MiB cap — so raising
    // the cap turned a test about refusing oversized payloads into a test that
    // wrote one successfully and asserted the opposite.
    cacheTasks([task({ uid: 'huge', notes: 'x'.repeat(MAX_BYTES + 1024) })])
    expect(localStorage.getItem(keyOf('tasks'))).toBeNull()
    expect(readCachedTasks()).toBeNull()
  })

  it('survives a storage that refuses to write', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => cacheTasks([task()])).not.toThrow()
    spy.mockRestore()
  })

  it('survives a storage that refuses to be read', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    expect(readCachedTasks()).toBeNull()
    spy.mockRestore()
  })
})

describe('the event window', () => {
  it('only answers for the window it was written for', () => {
    cacheEvents('2026-06-28', '2026-08-09', [event()])
    expect(readCachedEvents('2026-06-28', '2026-08-09')).toHaveLength(1)
    // A different month must not paint six weeks of the wrong events.
    expect(readCachedEvents('2026-07-26', '2026-09-06')).toBeNull()
  })

  it('keeps one window — the latest write wins', () => {
    cacheEvents('2026-06-28', '2026-08-09', [event({ uid: 'june' })])
    cacheEvents('2026-07-26', '2026-09-06', [event({ uid: 'july' })])
    expect(readCachedEvents('2026-06-28', '2026-08-09')).toBeNull()
    expect(readCachedEvents('2026-07-26', '2026-09-06')![0].uid).toBe('july')
  })
})

describe('cache lifecycle', () => {
  it('clears everything on logout, including other users', () => {
    cacheTasks([task()])
    setCacheUser('someone-else')
    cacheTasks([task()])
    clearCache()
    expect(readCachedTasks()).toBeNull()
    setCacheUser('nick')
    expect(readCachedTasks()).toBeNull()
  })

  it('clears one user without touching another', () => {
    cacheTasks([task({ uid: 'nicks' })])
    setCacheUser('other')
    cacheTasks([task({ uid: 'theirs' })])
    clearCache('other')
    expect(readCachedTasks()).toBeNull()
    setCacheUser('nick')
    expect(readCachedTasks()![0].uid).toBe('nicks')
  })

  it('sweeps entries written by an older shape, keeping the current one', () => {
    cacheTasks([task()])
    localStorage.setItem(`${CACHE_PREFIX}:0:nick:tasks`, JSON.stringify({ at: Date.now(), rows: [] }))
    localStorage.setItem('tasks-theme', 'dark')     // not ours; must survive
    sweepOldVersions()
    expect(localStorage.getItem(`${CACHE_PREFIX}:0:nick:tasks`)).toBeNull()
    expect(readCachedTasks()).toHaveLength(1)
    expect(localStorage.getItem('tasks-theme')).toBe('dark')
  })
})

describe('the day plan', () => {
  it('returns the day it stored, entries and all', () => {
    cacheDayPlan(dayPlan({
      entries: [dayEntry({ entry_id: 'a' }), dayEntry({ entry_id: 'b', kind: 'habit' })],
      capacity: 300, capacity_minutes: 300, reflection: 'Slow start.',
    }))
    const back = readCachedDayPlan('2026-08-21')
    expect(back?.entries.map((e) => e.entry_id)).toEqual(['a', 'b'])
    expect(back?.capacity).toBe(300)
    expect(back?.reflection).toBe('Slow start.')
  })

  it('only answers for the day it was written for', () => {
    cacheDayPlan(dayPlan())
    expect(readCachedDayPlan('2026-08-21')).not.toBeNull()
    // The rows on screen and the day every write carries have to be the same
    // day, so a blob for another one is a miss rather than a head start.
    expect(readCachedDayPlan('2026-08-22')).toBeNull()
  })

  it('keeps an EMPTY day, which is a real answer and not a corrupt entry', () => {
    // The one place this differs from the row caches above: an opened day the
    // owner emptied is a day with nothing on it, and reporting that as a miss
    // would blank the tab for exactly the account whose last look at it was
    // blank.
    cacheDayPlan(dayPlan({ entries: [] }))
    expect(readCachedDayPlan('2026-08-21')?.entries).toEqual([])
  })

  it('refuses a blob whose envelope and body name different days', () => {
    localStorage.setItem(keyOf('day'), JSON.stringify({
      at: Date.now(), day: '2026-08-21', plan: dayPlan({ day: '2026-08-20' }),
    }))
    expect(readCachedDayPlan('2026-08-21')).toBeNull()
  })

  it('drops rows that are not entries, keeping the ones that are', () => {
    localStorage.setItem(keyOf('day'), JSON.stringify({
      at: Date.now(),
      day: '2026-08-21',
      plan: {
        day: '2026-08-21',
        entries: [dayEntry({ entry_id: 'good' }), null, 7, 'nope',
          { entry_id: 'no-kind', day: '2026-08-21', source: 'user' }],
      },
    }))
    expect(readCachedDayPlan('2026-08-21')?.entries.map((e) => e.entry_id))
      .toEqual(['good'])
  })

  it('treats an unparseable blob as a miss', () => {
    localStorage.setItem(keyOf('day'), '{not json')
    expect(readCachedDayPlan('2026-08-21')).toBeNull()
  })

  it('keeps a kind it has never heard of rather than rewriting it', () => {
    // `DayEntryKind` widens silently and TodayView reads it through fallback
    // maps for that reason. An allowlist here would rewrite an unfamiliar kind
    // into a familiar one on the way through the disk cache ONLY, so a row
    // would read one way live and another way cached.
    const back = sanitizeDayEntry({ ...dayEntry(), kind: 'ritual' })
    expect(back?.kind).toBe('ritual')
    // …but a row that does not say what it is, or which day it is on, is not a
    // row: both are load-bearing everywhere they are read.
    expect(sanitizeDayEntry({ ...dayEntry(), kind: '' })).toBeNull()
    expect(sanitizeDayEntry({ ...dayEntry(), day: null })).toBeNull()
    expect(sanitizeDayEntry({ ...dayEntry(), source: undefined })).toBeNull()
  })

  it('rebuilds every field to its own type', () => {
    const back = sanitizeDayPlan({
      day: '2026-08-21', planned: 'yes', capacity: 'lots', capacity_minutes: {},
      committed_at: 5, shutdown_at: [], reflection: false,
      entries: [{ ...dayEntry(), position: 'top', estimate_minutes: 'ages',
        created_at: 42, done_at: 1 }],
    })
    expect(back).toMatchObject({
      planned: false, capacity: null, capacity_minutes: null,
      committed_at: null, shutdown_at: null, reflection: null,
    })
    expect(back?.entries[0]).toMatchObject({
      position: null, estimate_minutes: null, created_at: '', done_at: null,
    })
  })

  it('misses with no user set, so one account never reads another\'s', () => {
    cacheDayPlan(dayPlan())
    setCacheUser('someone-else')
    expect(readCachedDayPlan('2026-08-21')).toBeNull()
    setCacheUser('nick')
    expect(readCachedDayPlan('2026-08-21')).not.toBeNull()
  })

  it('goes with the rest on logout', () => {
    cacheDayPlan(dayPlan())
    cacheDayRange('2026-08-07', '2026-08-22', [dayPlan()])
    cacheHabits([habit()])
    clearCache()
    expect(readCachedDayPlan('2026-08-21')).toBeNull()
    expect(readCachedDayRange('2026-08-07', '2026-08-22')).toBeNull()
    expect(readCachedHabits()).toBeNull()
  })
})

describe('the fortnight window', () => {
  it('only answers for the window it was written for', () => {
    cacheDayRange('2026-08-07', '2026-08-22', [dayPlan()])
    expect(readCachedDayRange('2026-08-07', '2026-08-22')).toHaveLength(1)
    // Both ends move at a rollover and at every step of the picker, and a
    // window that does not match answers a different fortnight.
    expect(readCachedDayRange('2026-08-06', '2026-08-21')).toBeNull()
  })

  it('keeps one window — the latest write wins', () => {
    cacheDayRange('2026-08-07', '2026-08-22', [dayPlan({ day: '2026-08-21' })])
    cacheDayRange('2026-08-08', '2026-08-23', [dayPlan({ day: '2026-08-22' })])
    expect(readCachedDayRange('2026-08-07', '2026-08-22')).toBeNull()
    expect(readCachedDayRange('2026-08-08', '2026-08-23')![0].day).toBe('2026-08-22')
  })

  it('treats an empty window as a miss, unlike a single day', () => {
    // "No plans in there" and "nothing cached" are indistinguishable to every
    // reader of this — `recentPlans` answers [] either way — so there is
    // nothing to preserve and the ordinary corrupt-blob rule applies.
    cacheDayRange('2026-08-07', '2026-08-22', [])
    expect(readCachedDayRange('2026-08-07', '2026-08-22')).toBeNull()
  })
})

describe('the habit rules', () => {
  it('returns what it stored', () => {
    cacheHabits([habit(), habit({ id: 'hb2', title: 'Stretch', days: 'mon,wed' })])
    expect(readCachedHabits()!.map((h) => h.title)).toEqual(['Read', 'Stretch'])
    expect(readCachedHabits()![1].days).toBe('mon,wed')
  })

  it('rebuilds every field to its own type, and reads a missing schedule as every day', () => {
    // '' is EVERY DAY, spelled as the absence of a restriction — so the default
    // is not a stand-in for a missing value, it IS the value a habit with no
    // restriction carries.
    expect(sanitizeHabit({ id: 'hb1', days: null, position: 'first' }))
      .toEqual({
        id: 'hb1', title: '', days: '', paused_at: null, position: null,
        estimate_minutes: null, created_at: '',
      })
    expect(sanitizeHabit({ title: 'no id' })).toBeNull()
  })
})
