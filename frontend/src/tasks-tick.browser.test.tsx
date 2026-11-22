// A tick in the Tasks pane, in a real engine with the real stylesheets: the
// tick and the strike draw on the row, and only then does it fold away.
//
// What jsdom cannot say: that the marks actually animate (a row unmounted in
// the tick's own render shows neither, and TasksView.fieldnotes.test.tsx can
// only see classes), that the hold read from the real tokens covers the strike,
// and that the fold runs from the row's height to nothing. Production-shaped
// mount (`createRoot` + `StrictMode` under a `.shell`, as main.tsx does), in
// Chromium AND WebKit.
import { StrictMode, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cdp, server } from 'vitest/browser'
import { TasksView } from './components/TasksView'
import { DataProvider } from './data'
import { I18nProvider } from './i18n'
import { api, type List, type Task } from './api'
import { viewport } from './test/browser-measure'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)
const chromium = server.browser === 'chromium'
const devtools = () => cdp() as unknown as { send(method: string, params?: object): Promise<unknown> }

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  original_due: null, original_due_is_date: false, original_due_moved: false,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})
const list: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 2, task_count: 2, event_count: 0, total: 2, color: null,
}
const alpha = task({ uid: 'a1', summary: 'Water the seedlings' })
const bravo = task({ uid: 'b1', summary: 'Call the bank' })

let root: Root | null = null
let host: HTMLElement | null = null
beforeEach(() => {
  vi.clearAllMocks()
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([alpha, bravo])
  m.complete.mockImplementation(async (_l: string, uid: string, done?: boolean) => ({
    ...[alpha, bravo].find((t) => t.uid === uid)!, completed: done ?? true,
    status: (done ?? true) ? 'COMPLETED' : 'NEEDS-ACTION',
  }))
})
afterEach(async () => {
  root?.unmount(); host?.remove(); root = null; host = null
  if (chromium) await devtools().send('Emulation.setEmulatedMedia', { features: [] })
})

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const frame = () => new Promise(requestAnimationFrame)

function Harness() {
  const [collapsed, setCollapsed] = useState<string[]>([])
  return (
    <I18nProvider value="en"><DataProvider rev={0} onExpire={vi.fn()}>
      <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenLists={[]} onHiddenListsChange={vi.fn()}
        groups={[]} onGroupsChange={vi.fn()}
        collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
        collapsedTasks={collapsed} onCollapsedTasksChange={setCollapsed}
        showCompleted={false} />
    </DataProvider></I18nProvider>
  )
}

/** The row titled `title`, once it is on the page and the fonts are in. */
async function mountList(title: string) {
  await viewport(390)
  host = document.createElement('div')
  host.className = 'shell'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(<StrictMode><Harness /></StrictMode>)
  const find = () => [...document.querySelectorAll<HTMLElement>('.content .task')]
    .find((r) => r.querySelector('.task-title')?.textContent?.includes(title))
  for (let i = 0; i < 200 && !find(); i++) await sleep(10)
  await document.fonts.ready
  await frame()
  return find()!
}

type Sample = { ms: number; connected: boolean; tick: number; strike: number; leaving: boolean; h: number; opacity: number }

/** Click the row's check, then sample it every frame for `ms`. */
async function tickAndWatch(row: HTMLElement, ms: number): Promise<Sample[]> {
  const group = row.parentElement as HTMLElement
  const out: Sample[] = []
  const t0 = performance.now()
  row.querySelector<HTMLButtonElement>('.check')!.click()
  while (performance.now() - t0 < ms) {
    await frame()
    const tick = row.querySelector('.check-tick')!
    const path = row.querySelector('.strike-ink path')
    out.push({
      ms: performance.now() - t0, connected: row.isConnected,
      tick: parseFloat(getComputedStyle(tick).strokeDashoffset),
      strike: path ? parseFloat(getComputedStyle(path).strokeDashoffset) : NaN,
      leaving: group.classList.contains('leaving'),
      h: group.getBoundingClientRect().height,
      opacity: parseFloat(getComputedStyle(group).opacity),
    })
  }
  return out
}

describe('a tick in the Tasks pane under Field notes', () => {
  it('draws the tick and the strike on the row, then folds it away', async () => {
    const row = await mountList('Water the seedlings')
    const h0 = row.parentElement!.getBoundingClientRect().height
    expect(h0).toBeGreaterThan(20)
    const s = await tickAndWatch(row, 1800)
    const live = s.filter((x) => x.connected)
    // The tick animates: caught part-drawn, then finished.
    expect(live.some((x) => x.tick > 0 && x.tick < 1), 'the tick never seen mid-draw').toBe(true)
    expect(live.find((x) => x.ms > 500)?.tick).toBe(0)
    // So does the strike, and it has finished before the row starts to go.
    expect(live.some((x) => x.strike > 0 && x.strike < 1), 'the strike never seen mid-draw').toBe(true)
    const firstLeaving = live.find((x) => x.leaving)!
    expect(firstLeaving, 'the row never started to leave').toBeDefined()
    const before = live.filter((x) => x.ms < firstLeaving.ms)
    expect(before[before.length - 1].strike).toBe(0)
    // Not before the hold at the shipped tokens (ink = 980ms) is up; the upper
    // bound is loose, for a loaded machine's late timer.
    expect(firstLeaving.ms).toBeGreaterThan(900)
    expect(firstLeaving.ms).toBeLessThan(1400)
    // The fold: seen part-way between its own height and nothing, fading.
    expect(live.some((x) => x.leaving && x.h > 1 && x.h < h0 - 1 && x.opacity < 1)).toBe(true)
    // And gone by the end of the watch: ink + leave is 1430ms.
    expect(s[s.length - 1].connected).toBe(false)
    expect(document.body.textContent).toContain('Call the bank')
  })

  it.skipIf(!chromium)('goes at once under reduced motion', async () => {
    await devtools().send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] })
    const row = await mountList('Water the seedlings')
    const s = await tickAndWatch(row, 100)
    expect(s[0].connected).toBe(false)
  })

  it('leaves a preset as it was: the row goes at once', async () => {
    delete document.documentElement.dataset.surface
    document.documentElement.dataset.preset = 'workspace'
    const row = await mountList('Water the seedlings')
    const s = await tickAndWatch(row, 100)
    expect(s[0].connected).toBe(false)
  })
})
