// The Calendar's header at the narrowest phone, under Field notes.
//
// The month arrows are icon squares at every width, and at 320px two 40px
// squares and Today left "September 2026" cut off with an ellipsis. Under 721px
// they are 32px squares (fieldnotes.css) with a centred 44px `::after` for the
// finger, as Today's row controls have. So this holds both halves: the title
// fits, and the tap boxes that bought it back do not overlap the Today button
// between them.
//
// The real component through the real stylesheets, with the fixture of
// calendar.browser.test.tsx; the cursor is September 2026, one of the longest
// month titles in English, rather than whatever month it is today.
import { StrictMode, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { CalendarView } from './components/CalendarView'
import { DataProvider } from './data'
import { I18nProvider } from './i18n'
import { api, type List } from './api'
import { box, viewport } from './test/browser-measure'

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

let root: Root | null = null
let host: HTMLElement | null = null

beforeEach(() => {
  vi.clearAllMocks()
  m.calendars.mockResolvedValue([cal])
  m.events.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
})
afterEach(() => { root?.unmount(); host?.remove(); root = null; host = null })

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function Harness() {
  const [cursor, setCursor] = useState(() => new Date(2026, 8, 1))
  return (
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
  for (let i = 0; i < 200 && !document.querySelector('.cal-head'); i++) await sleep(10)
  await document.fonts.ready
  for (let i = 0; i < 5; i++) await new Promise(requestAnimationFrame)
}

describe('the Calendar header at 320px', () => {
  it('shows the whole month title', async () => {
    await mountAt(320, 568)
    const title = document.querySelector<HTMLElement>('.cal-title')!
    expect(title.textContent).toBe('September 2026')
    expect(title.scrollWidth, 'the title is cut off').toBeLessThanOrEqual(title.clientWidth)
  })

  it('has 32px arrows whose tap boxes stay clear of Today\'s', async () => {
    await mountAt(320, 568)
    const [prev, today, next] = [...document.querySelectorAll<HTMLElement>('.cal-head > button')]
    expect(today.textContent).toBe('Today')
    for (const a of [prev, next]) {
      expect(box(a).w).toBe(32)
      expect(box(a).h).toBe(32)
      expect(getComputedStyle(a, '::after').width).toBe('44px')
    }
    const t = box(today)
    const mid = t.top + t.h / 2
    const hit = (x: number, y: number) => document.elementFromPoint(x, y)?.closest('button')
    // Each arrow's tap box reaches 6px past its square, and is its own there...
    const p = box(prev)
    const n = box(next)
    expect(hit(p.right + 5, mid)).toBe(prev)
    expect(hit(n.left - 5, mid)).toBe(next)
    // ...and stops short of Today's: its edges belong to Today.
    expect(hit(t.left + 1, mid)).toBe(today)
    expect(hit(t.right - 1, mid)).toBe(today)
    expect(p.right + 6, 'the previous arrow\'s box meets Today\'s').toBeLessThanOrEqual(t.left)
    expect(t.right + 6, 'the next arrow\'s box meets Today\'s').toBeLessThanOrEqual(n.left)
  })
})
