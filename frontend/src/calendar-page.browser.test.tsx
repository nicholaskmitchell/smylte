// The Calendar's month as a ruled page under Field notes, measured in a real
// browser: the grid's hand-ruled lines lie on the cells' edges (and again after
// the window changes), today is circled in coral instead of filled, the days
// gone are crossed off, and on a phone the chosen day is boxed in pen. jsdom
// computes no layout, so none of this can be seen there.
//
// The real component through the real stylesheets, mounted as main.tsx does and
// with the fixture of calendar.browser.test.tsx.
import { StrictMode, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { CalendarView, measureCells } from './components/CalendarView'
import type { CalendarFit } from './calendar'
import { DataProvider } from './data'
import { I18nProvider } from './i18n'
import { applyDesign } from './appearance'
import { api, type CalEvent, type List, type Task } from './api'
import { box, mount, viewport } from './test/browser-measure'
import fixture from './test/drawing-fixture.json'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

const cal: List = {
  id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#B8860B',
}

const taskList: List = {
  id: 'tl1', href: '/tl1/', name: 'Errands', is_task_list: true, is_calendar: false,
  open_count: 2, task_count: 2, event_count: 0, total: 2, color: '#1565C0',
}

let root: Root | null = null
let host: HTMLElement | null = null

beforeEach(() => {
  vi.clearAllMocks()
  m.calendars.mockResolvedValue([cal])
  m.lists.mockResolvedValue([taskList])
  m.events.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.drawing.mockResolvedValue(undefined)
})
afterEach(() => {
  root?.unmount(); host?.remove(); root = null; host = null
  applyDesign(document.documentElement, null)
})

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const frames = async (n: number) => { for (let i = 0; i < n; i++) await new Promise(requestAnimationFrame) }

function Harness({ fit = 'dynamic', month }: { fit?: CalendarFit; month?: Date }) {
  const now = new Date()
  const [cursor, setCursor] = useState(() => month ?? new Date(now.getFullYear(), now.getMonth(), 1))
  return (
    <I18nProvider value="en"><DataProvider rev={0} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={['tl1']} onCalTaskListsChange={vi.fn()}
        calShowDone={false} onCalShowDoneChange={vi.fn()}
        fit={fit} />
    </DataProvider></I18nProvider>
  )
}

async function mountAt(w: number, h: number, props?: { fit?: CalendarFit; month?: Date }) {
  await viewport(w, h)
  host = document.createElement('div')
  host.className = 'shell'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(<StrictMode><Harness {...props} /></StrictMode>)
  for (let i = 0; i < 200 && !document.querySelector('.cal-cell'); i++) await sleep(10)
  await document.fonts.ready
  // Settle on a stable geometry before measuring (see calendar.browser.test.tsx).
  let last = ''
  for (let i = 0; i < 30; i++) {
    await new Promise(requestAnimationFrame)
    const now = [...document.querySelectorAll('.cal-cell')]
      .map((c) => `${Math.round(c.getBoundingClientRect().top)}`).join(',')
    if (now === last && !now.includes('NaN')) return
    last = now
  }
}

const centre = (p: SVGGraphicsElement, svg: DOMRect) => {
  const b = p.getBBox()
  return { x: svg.left + b.x + b.width / 2, y: svg.top + b.y + b.height / 2 }
}
function expectRuledOnTheCells() {
  const grid = document.querySelector('.cal-grid') as HTMLElement
  const svg = grid.querySelector(':scope > svg.grid-ink') as SVGSVGElement
  expect(svg, 'no ruled grid').not.toBeNull()
  const sb = svg.getBoundingClientRect()
  const cells = [...grid.querySelectorAll(':scope > .cal-cell')].map((c) => c.getBoundingClientRect())
  const v = [...svg.querySelectorAll('path.rule.v')] as SVGPathElement[]
  const h = [...svg.querySelectorAll('path.rule.h')] as SVGPathElement[]
  expect(v).toHaveLength(6)
  expect(h).toHaveLength(8)
  expect(svg.querySelectorAll('path.rule.h.edge')).toHaveLength(2)
  v.forEach((p, c) => expect(Math.abs(centre(p, sb).x - (cells[c].right - 0.5)), `column line ${c}`).toBeLessThan(2))
  const g = grid.getBoundingClientRect()
  const rows = [g.top + grid.clientTop - 0.5, cells[0].top - 0.5, ...[0, 7, 14, 21, 28, 35].map((i) => cells[i].bottom - 0.5)]
  h.forEach((p, i) => expect(Math.abs(centre(p, sb).y - rows[i]), `row line ${i}`).toBeLessThan(2))
}

describe('the ruled page under Field notes', () => {
  it('rules the grid on the cells\' edges, and again after the window changes', async () => {
    await mountAt(1440, 900)
    expectRuledOnTheCells()
    await viewport(1100, 900)
    await frames(10)
    expectRuledOnTheCells()
    for (const c of document.querySelectorAll('.cal-cell')) {
      expect(getComputedStyle(c).position, `${c.getAttribute('data-day')} is out of the grid's flow`).toBe('static')
    }
  })

  it('circles today in coral instead of filling it', async () => {
    await mountAt(1440, 900)
    const num = document.querySelector('.cal-cell.today .daynum')!
    expect(getComputedStyle(num).backgroundColor).toBe('rgba(0, 0, 0, 0)')
    const probe = document.createElement('i')
    probe.style.color = 'var(--accent)'
    document.body.appendChild(probe)
    const coral = getComputedStyle(probe).color
    probe.remove()
    expect(getComputedStyle(num.querySelector('.today-ink path')!).stroke).toBe(coral)
    expect(document.querySelectorAll('.cross-ink').length).toBe(new Date().getDate() - 1)
  })

  it('boxes the chosen day in pen on a phone', async () => {
    await mountAt(390, 844)
    const svg = document.querySelector('.cal-grid > svg.grid-ink') as SVGSVGElement
    const box1 = svg.querySelector('path.focus') as SVGGraphicsElement | null
    expect(box1, 'no box on the chosen day').not.toBeNull()
    const c = centre(box1!, svg.getBoundingClientRect())
    const t = box(document.querySelector('.cal-cell.today')!)
    expect(c.x).toBeGreaterThan(t.left)
    expect(c.x).toBeLessThan(t.right)
    expect(c.y).toBeGreaterThan(t.top)
    expect(c.y).toBeLessThan(t.bottom)
    const focused = document.querySelector('.cal-cell[data-focus]')!
    expect(getComputedStyle(focused).boxShadow).toBe('none')
  })

  it('leaves the presets their grid', async () => {
    applyDesign(document.documentElement, 'refined')
    await mountAt(1440, 900)
    expect(document.querySelector('.grid-ink')).toBeNull()
    const num = document.querySelector('.cal-cell.today .daynum')!
    expect(getComputedStyle(num).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')
  })
})

describe('events in pen and marker', () => {
  // Relative to today: the Sunday that starts today's week is always in the
  // grid. Offsite runs Sun to Tue, a Hebrew title (so its chip is dir="rtl")
  // Wed to Fri, and a timed Standup and a task sit on the Thursday.
  const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const today = new Date()
  const day = (n: number) => ymd(new Date(today.getFullYear(), today.getMonth(), today.getDate() - today.getDay() + n))
  const ev = (o: Partial<CalEvent>): CalEvent => ({
    uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
    summary: 'Standup', description: null, location: null,
    start: `${day(4)}T10:00:00`, start_is_date: false,
    end: `${day(4)}T11:00:00`, end_is_date: false, duration: null,
    all_day: false, status: null, busy: true, notify_minutes_before: null,
    tags: [], has_rrule: false, href: '/c1/u1.ics', etag: '"1"', ...o,
  })
  const allDay = (uid: string, summary: string, from: number, to: number) => ev({
    uid, id: uid, summary, all_day: true, start: day(from), end: day(to), start_is_date: true, end_is_date: true,
    href: `/c1/${uid}.ics`,
  })
  const events = [allDay('a', 'Offsite', 0, 3), allDay('b', 'שלום עולם', 3, 6), ev({})]
  const task: Task = {
    uid: 't1', list: 'tl1', summary: 'Renew passport', notes: null, status: 'NEEDS-ACTION',
    completed: false, cancelled: false, parked: false, parked_at: null,
    original_due: null, original_due_is_date: false, original_due_moved: false,
    priority: null, priority_label: 'none',
    percent_complete: null, due: day(4), due_is_date: true,
    start: null, start_is_date: true, tags: [], parent: null, children: [],
    child_count: 0, completed_child_count: 0, derived_percent: null,
    pinned: false, sort_order: null,
    completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
    created: null, last_modified: null,
    href: '/tl1/t1.ics', etag: '"1"',
  }
  const chip = (d: number, title: string) => {
    const found = [...document.querySelectorAll(`.cal-cell[data-day="${day(d)}"] .cal-ev`)]
      .find((e) => e.querySelector('bdi')?.textContent === title)
    expect(found, `${title} on ${day(d)}`).toBeDefined()
    return found as HTMLElement
  }

  beforeEach(() => {
    m.events.mockResolvedValue(events)
    m.tasks.mockResolvedValue([task])
  })

  it('writes chips at the 13px floor, all one height', async () => {
    await mountAt(1440, 900)
    const chips = [...document.querySelectorAll('.cal-ev, .cal-task')]
    expect(chips.length, 'no chips rendered').toBeGreaterThan(0)
    for (const c of chips) expect(getComputedStyle(c).fontSize, c.textContent!).toBe('13px')
    const heights = ['.cal-ev:not(.allday)', '.cal-ev.allday', '.cal-task']
      .map((s) => document.querySelector(s)!.getBoundingClientRect().height)
    expect(Math.max(...heights) - Math.min(...heights), `chip heights ${heights.join(', ')}`).toBeLessThanOrEqual(0.5)
  })

  it('draws one swipe across a run, left to right whatever the title\'s direction', async () => {
    await mountAt(1440, 900)
    for (const [title, from] of [['Offsite', 0], ['שלום עולם', 3]] as const) {
      const [start, mid, end] = [0, 1, 2].map((n) => chip(from + n, title))
      if (from === 3) expect(mid).toHaveAttribute('dir', 'rtl')
      const [s, mi, e] = [start, mid, end].map((c) => c.getBoundingClientRect())
      expect(Math.abs(mi.left - s.right), `${title}: start to mid`).toBeLessThanOrEqual(1.5)
      expect(Math.abs(e.left - mi.right), `${title}: mid to end`).toBeLessThanOrEqual(1.5)
      expect(getComputedStyle(mid.querySelector('bdi')!).color).toBe('rgba(0, 0, 0, 0)')
      expect(getComputedStyle(mid).textOverflow).toBe('clip')
    }
  })

  it('draws a band across a run on a phone', async () => {
    await mountAt(390, 844)
    const bands = [0, 1, 2].map((n) => document.querySelector(`.cal-cell[data-day="${day(n)}"] .ev-band`) as HTMLElement)
    for (const b of bands) expect(b, 'no band').not.toBeNull()
    expect(bands.map((b) => b.getAttribute('data-span'))).toEqual(['start', 'mid', 'end'])
    const [s, mi] = bands.map((b) => b.getBoundingClientRect())
    expect(Math.abs(mi.left - s.right)).toBeLessThanOrEqual(1.5)
  })

  it('counts the date\'s margin when it fits chips in a cell', async () => {
    const probe = await mount('<div class="probe"><div class="cal-cell" style="display:flex;flex-direction:column;min-height:0;height:100px;padding:0;gap:0;border:0"><span class="daynum" style="display:block;height:20px;margin:0 0 10px;padding:0">1</span><div class="cal-ev" style="height:20px;padding:0">x</div></div></div>')
    try {
      expect(measureCells(probe.querySelector('.probe'))).toBe(3)
    } finally {
      probe.remove()
    }
  })

  it('clips nothing in the fixed window', async () => {
    const calls = [1, 2, 3, 4, 5].map((n) => ev({
      uid: `call${n}`, id: `call${n}`, summary: `Call ${n}`, href: `/c1/call${n}.ics`,
      start: `${ymd(today)}T${String(12 + n).padStart(2, '0')}:00:00`,
      end: `${ymd(today)}T${String(12 + n).padStart(2, '0')}:30:00`,
    }))
    m.events.mockResolvedValue([...events, ...calls])
    await mountAt(1440, 900, { fit: 'fixed' })
    for (const c of document.querySelectorAll<HTMLElement>('.cal-cell')) {
      expect(c.scrollHeight, `${c.getAttribute('data-day')} clips what it holds`).toBeLessThanOrEqual(c.clientHeight + 1)
    }
    expect(document.querySelector('.cal-cell.today .cal-more'), 'no "+N more" on today').not.toBeNull()
  })
})

describe('the page\'s top', () => {
  const rect = (e: Element) => e.getBoundingClientRect()
  // The month's drawing, still, named by the month's first day as the server
  // names it.
  const monthDrawing = (day: string) => ({
    ...fixture, view: 'month', day, subject: 'month-test', viewBox: [0, 0, 200, 110], ambient: null,
    marks: (fixture.marks as { reward: number | null; when: unknown[]; frames: string[] }[])
      .filter((mk) => mk.reward === null && mk.when.length === 0)
      .map((mk) => ({ ...mk, frames: mk.frames.slice(0, 1) })),
  })
  beforeEach(() => {
    const now = new Date()
    m.drawing.mockResolvedValue(monthDrawing(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`))
  })
  /** Wait, for at most a second, until the month's drawing is drawn. */
  async function drawn() {
    for (let i = 0; i < 100 && !document.querySelector('.cal-drawing svg.day-drawing'); i++) await sleep(10)
    expect(document.querySelector('.cal-drawing svg.day-drawing'), 'the month\'s drawing is not drawn').not.toBeNull()
    await frames(2)
  }

  it('writes the month at 52px in Newsreader italic, underlined in coral', async () => {
    await mountAt(1440, 900)
    const month = document.querySelector('.cal-month')!
    const style = getComputedStyle(month)
    expect(style.fontSize).toBe('52px')
    expect(style.fontStyle).toBe('italic')
    expect(style.fontFamily).toMatch(/Newsreader/)
    const probe = document.createElement('i')
    probe.style.color = 'var(--accent)'
    document.body.appendChild(probe)
    const coral = getComputedStyle(probe).color
    probe.remove()
    expect(getComputedStyle(month.querySelector('.month-ink path')!).stroke).toBe(coral)
  })

  it.each([[1440, 210, 115.5], [1024, 160, 88]])('holds the month\'s drawing at %ipx in a %s x %spx box', async (w, width, height) => {
    await mountAt(w, 900)
    await drawn()
    const b = rect(document.querySelector('.cal-drawing')!)
    expect(b.width).toBeCloseTo(width, 0)
    expect(b.height).toBeCloseTo(height, 0)
  })

  it.each([1440, 1024, 800, 721])('lays the month and the controls apart at %ipx', async (w) => {
    await mountAt(w, 900)
    await drawn()
    const head = document.querySelector('.cal-head')!
    const parts = [...head.children].filter((c) => !c.classList.contains('spacer'))
    const rects = parts.map(rect)
    for (let a = 0; a < rects.length; a++) {
      for (let b = a + 1; b < rects.length; b++) {
        const overlap = rects[a].left < rects[b].right - 0.5 && rects[b].left < rects[a].right - 0.5
          && rects[a].top < rects[b].bottom - 0.5 && rects[b].top < rects[a].bottom - 0.5
        expect(overlap, `${parts[a].className} runs over ${parts[b].className}`).toBe(false)
      }
    }
    const title = head.querySelector('.cal-title')!
    expect(rect(head.querySelector('.cal-month')!).right).toBeLessThanOrEqual(rect(title).right + 0.5)
    if (w <= 800) {
      const tops = [...head.querySelectorAll(':scope > button')].map((b) => rect(b).top)
      expect(Math.max(...tops) - Math.min(...tops), `the controls' tops ${tops.join(', ')}`).toBeLessThanOrEqual(1)
    }
  })

  it.each([[320, 568, 22, 13, 4], [359, 780, 22, 13, 4], [360, 780, 26, 14, 6], [390, 844, 26, 14, 6]])(
    'fits September, underline and all, on a %ix%i phone (the month at %ipx, its year at %ipx, %ipx apart)',
    async (w, h, size, yearSize, gap) => {
      await mountAt(w, h, { month: new Date(2026, 8, 1) })
      const title = document.querySelector<HTMLElement>('.cal-title')!
      const month = document.querySelector<HTMLElement>('.cal-month')!
      const year = document.querySelector<HTMLElement>('.cal-year')!
      expect(title.scrollWidth, 'the title is cut off').toBeLessThanOrEqual(title.clientWidth)
      expect(rect(document.querySelector('.month-ink')!).bottom, 'the underline is clipped').toBeLessThanOrEqual(rect(title).bottom + 0.5)
      expect(getComputedStyle(month).fontSize).toBe(`${size}px`)
      expect(getComputedStyle(year).fontSize).toBe(`${yearSize}px`)
      expect(getComputedStyle(title).columnGap).toBe(`${gap}px`)
      expect(rect(month).left, 'the month\'s first letter is clipped').toBeGreaterThanOrEqual(rect(title).left - 0.5)
    })

  it('never clips the month\'s first letter at a large text scale on a 320px phone', async () => {
    document.documentElement.style.setProperty('--fs-scale', '1.3')
    try {
      await mountAt(320, 568, { month: new Date(2026, 8, 1) })
      const title = document.querySelector<HTMLElement>('.cal-title')!
      const month = document.querySelector<HTMLElement>('.cal-month')!
      expect(rect(month).left, 'the month\'s first letter is clipped').toBeGreaterThanOrEqual(rect(title).left - 0.5)
    } finally {
      document.documentElement.style.removeProperty('--fs-scale')
    }
  })
})
