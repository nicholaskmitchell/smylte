import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest'
import {
  CACHE_PREFIX, CACHE_VERSION,
  cacheCalendars, cacheEvents, cacheLists, cacheTasks, clearCache,
  readCachedCalendars, readCachedEvents, readCachedLists, readCachedTasks,
  sanitizeEvent, sanitizeList, sanitizeTask, setCacheUser, sweepOldVersions,
} from './cache'
import type { CalEvent, List, Task } from './api'

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = (o: Partial<List> = {}): List => ({
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F', ...o,
})

const event = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'e1', id: 'e1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Lunch', description: null, location: null, start: '2026-07-15',
  start_is_date: true, end: '2026-07-16', end_is_date: true, all_day: true,
  status: null, tags: [], has_rrule: false, href: '/c1/e1.ics', etag: '"1"', ...o,
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
  it('caps the row count', () => {
    cacheTasks(Array.from({ length: 2500 }, (_, i) => task({ uid: `u${i}` })))
    expect(readCachedTasks()).toHaveLength(2000)
  })

  it('skips an oversized payload and drops the entry it could not replace', () => {
    // Half-written JSON is not a document, so bytes cannot be truncated the way
    // rows can; the entry has to go rather than outlive the data it lost to.
    cacheTasks([task({ uid: 'small' })])
    expect(readCachedTasks()).toHaveLength(1)
    cacheTasks([task({ uid: 'huge', notes: 'x'.repeat(1100 * 1024) })])
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
