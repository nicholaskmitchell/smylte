// The month grid's shape, measured, at the widths a phone actually is.
//
// Written while chasing a report of the Calendar tab rendering as one
// full-width cell carrying only today's date — no weekday header row, no
// agenda. Nothing here reproduces it: the grid comes out right in both engines
// at every size below. That is the point of committing it rather than deleting
// it. The report is real, the shape it describes is unmistakable, and until now
// nothing in the suite would have noticed if a change made the grid come out
// that way — `CalendarView.test.tsx` runs under jsdom, where every box is 0x0
// and `grid-template-columns` is not evaluated at all.
//
// So this is a tripwire on the exact failure described: seven columns of equal
// width, seven headers above them, forty-two cells. It measures the real
// component through the real stylesheets, and it runs in Chromium AND WebKit —
// the second being the engine the report came from and, for an app used mostly
// on a phone, the one that matters more.
//
// Production-shaped mount (`createRoot` + `StrictMode`, as main.tsx does)
// rather than the raw-markup harness the rest of the layout tier uses: the
// column count is decided by the component's own render, so markup written
// here by hand would be a second source of truth about what the app draws and
// would pass whatever the component did.
import { StrictMode, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { CalendarView } from './components/CalendarView'
import { DataProvider } from './data'
import { I18nProvider } from './i18n'
import { api, type CalEvent, type List } from './api'
import { box, viewport } from './test/browser-measure'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

const cal: List = {
  id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#B8860B',
}

// Today, so the cell under test is the one the report describes: `.today`, and
// on a phone `.focus` as well.
const today = new Date()
const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const ev: CalEvent = {
  uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: `${ymd(today)}T09:00:00`, start_is_date: false,
  end: `${ymd(today)}T09:30:00`, end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, notify_minutes_before: null,
  tags: [], has_rrule: false, href: '/c1/u1.ics', etag: '"1"',
}

let root: Root | null = null
let host: HTMLElement | null = null

beforeEach(() => {
  vi.clearAllMocks()
  m.calendars.mockResolvedValue([cal])
  m.events.mockResolvedValue([ev])
  m.tasks.mockResolvedValue([])
})
afterEach(() => { root?.unmount(); host?.remove(); root = null; host = null })

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function Harness() {
  const now = new Date()
  const [cursor, setCursor] = useState(() => new Date(now.getFullYear(), now.getMonth(), 1))
  return (
    // `I18nProvider` explicitly, not the context default: that default is built
    // at MODULE LOAD, so it captures whatever `navigator.languages` said before
    // this file ran. Under the provider the locale is resolved at render.
    <I18nProvider value="en"><DataProvider rev={0} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={[]} onCalTaskListsChange={vi.fn()}
        calShowDone={false} onCalShowDoneChange={vi.fn()}
        fit="dynamic" />
    </DataProvider></I18nProvider>
  )
}

async function mountAt(w: number, h: number) {
  await viewport(w, h)
  host = document.createElement('div')
  host.className = 'shell'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(<StrictMode><Harness /></StrictMode>)
  for (let i = 0; i < 200 && !document.querySelector('.cal-cell'); i++) await sleep(10)
  await document.fonts.ready
  // SETTLE on a stable geometry before measuring. The first cell exists before
  // the events fetch resolves, and the re-render it causes replaces the cells;
  // measuring across that commit reads a node the document no longer lays out
  // and returns an all-zero rect. Seen once, on today's cell, before this loop
  // existed — and a layout assertion that is right 24 runs out of 25 is worth
  // less than no assertion, because the failure teaches people to re-run.
  let last = ''
  for (let i = 0; i < 30; i++) {
    await new Promise(requestAnimationFrame)
    const now = [...document.querySelectorAll('.cal-cell')]
      .map((c) => `${Math.round(c.getBoundingClientRect().top)}`).join(',')
    if (now === last && !now.includes('NaN')) return
    last = now
  }
}

// An iPhone 15 Pro, an iPhone 14, a Pro Max, and the narrowest phone the
// stylesheet has a breakpoint for.
const PHONES: Array<[number, number]> = [[393, 852], [390, 844], [430, 932], [320, 568]]

describe('the month grid on a phone', () => {
  it.each(PHONES)('is seven equal columns of six rows at %ix%i', async (w, h) => {
    await mountAt(w, h)

    const cells = [...document.querySelectorAll('.cal-cell')]
    const dows = [...document.querySelectorAll('.cal-dow')]
    // `monthGrid` is `Array.from({ length: 42 })` — unconditional, no branch on
    // data — so anything other than 42 means the render, not the arithmetic.
    expect(cells, 'the month did not render 42 day cells').toHaveLength(42)
    expect(dows, 'the weekday header row is missing').toHaveLength(7)

    // THE assertion, and the one the report would have tripped: the first row
    // is seven cells side by side, not one cell the width of the pane. Compared
    // as a set of widths rather than against a number, because the two engines
    // round a seventh of 393px differently and neither is wrong.
    const firstRow = cells.slice(0, 7).map((c) => box(c))
    for (const b of firstRow) {
      expect(b.w, 'a day cell is as wide as the pane — the grid is one column')
        .toBeLessThan(w / 2)
      expect(b.w, 'a day cell has no width').toBeGreaterThan(w / 14)
    }
    // All seven on one line, so they are columns and not stacked rows.
    const top = firstRow[0].top
    for (const b of firstRow) expect(b.top).toBeCloseTo(top, 0)

    // And six rows below the header, each one lower than the last.
    // Every cell is laid out. A cell with no box is not a cosmetic problem: it
    // is a day of the month that is on the page and cannot be seen or tapped.
    for (const c of cells) {
      expect(box(c).w, `${c.getAttribute('data-day')} has no box`).toBeGreaterThan(0)
    }

    // Six rows under the header. Grouped with a tolerance rather than by exact
    // top, because a row's cells can differ by a sub-pixel and two engines
    // round that differently — 42 cells over 7 columns is 6 rows in both.
    // NO CELL IS TAKEN OUT OF THE GRID'S FLOW. This is the assertion the bug
    // that prompted this file would have failed: the focused day carried the
    // bare class `focus`, which app.css:2494 gives `position: fixed; inset: 0`
    // and an opaque background, so today's cell became a viewport-sized panel
    // over the whole app. Measured before the fix, at 393x852: the cell for
    // today reported `position: fixed` and a box of 393x852 at (0, 0), while
    // the other 41 laid out normally.
    for (const c of cells) {
      expect(getComputedStyle(c).position, `${c.getAttribute('data-day')} is out of the grid's flow`)
        .toBe('static')
      expect(box(c).h, `${c.getAttribute('data-day')} is taller than the pane`).toBeLessThan(h / 2)
    }

    // Six rows under the header. Grouped with a tolerance rather than by exact
    // top, because a row's cells can differ by a sub-pixel and two engines
    // round that differently — 42 cells over 7 columns is 6 rows in both.
    const tops = cells.map((c) => box(c).top).sort((a, b) => a - b)
    const rows = tops.filter((t, i) => i === 0 || t - tops[i - 1] > 2)
    expect(rows, 'the grid is not six rows of seven').toHaveLength(6)
  })

  it('marks today, and gives it dots rather than the desktop chips', async () => {
    // The mobile branch: `.ev-dots` instead of `.cal-ev`. Pinned because the
    // report showed a today cell with a dot in it, so this is the branch the
    // screenshot was taken from — a regression that swapped it would change
    // what the report even means.
    await mountAt(393, 852)
    const todayCell = document.querySelector('.cal-cell.today')
    expect(todayCell, 'no cell is marked today').not.toBeNull()
    expect(todayCell!.querySelector('.ev-dots'), 'the mobile dots are missing').not.toBeNull()
    expect(document.querySelector('.cal-ev'), 'desktop chips rendered on a phone').toBeNull()
    // A dot is a mark, not a row: the `.task` collision that once made one
    // render as a 28x23 slab is what this number is here for.
    const dot = todayCell!.querySelector('.ev-dot')!
    expect(box(dot).h, 'a dot is rendering as a row, not a mark').toBeLessThan(12)
  })
})
