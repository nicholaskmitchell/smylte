import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeView } from './HomeView'
import { DataProvider } from '../data'
import { setCacheUser } from '../cache'
import { api, type Share } from '../api'
import { DEFAULT_LAYOUT, type DashboardModule } from '../dashboard'

// Home under Field notes, the design that names things and does not explain
// them. The preset behaviour is HomeView.test.tsx's, and is not repeated here.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

const task = (o: Partial<import('../api').Task> = {}): import('../api').Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  original_due: null, original_due_is_date: false, original_due_moved: false,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = { id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 1, task_count: 1, event_count: 0, total: 1, color: '#D9480F' }

const share = (o: Partial<Share> = {}): Share => ({
  id: 'a'.repeat(32), name: 'Mum', token: 'tok-secret-mum', url: 'https://x.example/s/tok-secret-mum',
  lists: [], calendars: [], show_focus: false, horizon_days: 7,
  enabled: true, switched_off_by_password: false, last_seen_at: null,
  created_at: '2026-10-01T09:00:00Z', updated_at: '2026-10-01T09:00:00Z', ...o,
})

const link = (token: string, title: string, enabled: boolean) => ({
  token, title, description: null, calendar: 'c1', calendar_name: 'Work',
  calendar_missing: false, duration_minutes: 30, timezone: 'UTC',
  availability: {}, show_busy: true, buffer_minutes: 0, min_notice_hours: 0,
  horizon_days: 14, enabled, booking_count: 0,
  created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
})

function setup(layout: DashboardModule[] | null = DEFAULT_LAYOUT) {
  return render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <HomeView rev={0} onExpire={vi.fn()} layout={layout} onLayoutChange={vi.fn()} />
    </DataProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.shares.mockResolvedValue([])
})

afterEach(() => {
  document.documentElement.removeAttribute('data-surface')
})

describe('<HomeView> under Field notes', () => {
  it('arranges without a tooltip, a hint or a blurb', async () => {
    const { container } = setup()
    await screen.findByText('Today')
    await userEvent.click(screen.getByRole('button', { name: 'Arrange' }))

    expect(screen.getByRole('button', { name: /remove today/i })).toBeInTheDocument()
    expect(container.querySelector('.content-sub')).toHaveTextContent('5 modules')
    expect(container.querySelectorAll('[title]')).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: 'Add module' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(document.querySelectorAll('.dash-pick').length).toBeGreaterThan(0)
    expect(document.querySelector('.dash-pick-blurb')).toBeNull()
  })

  it('draws a strike under a completed task', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Done already', completed: true, status: 'COMPLETED' }),
    ])
    const { container } = setup([{ id: 'x', kind: 'completed', x: 0, y: 0, w: 6, h: 6 }])
    const title = await screen.findByText('Done already')
    expect(title.closest('.dash-task-title')!.querySelector('.strike-ink.on')).not.toBeNull()
    expect(container.querySelectorAll('.dash-task-title .strike-ink.on')).toHaveLength(1)
  })

  it('draws a strike under a disabled link and none under an enabled one', async () => {
    m.schedulingLinks.mockResolvedValue([
      link('t1', 'Paused link', false), link('t2', 'Live link', true)] as never)
    setup([{ id: 'l', kind: 'booking_links', x: 0, y: 0, w: 6, h: 6 }])
    const paused = (await screen.findByText('Paused link')).closest('.dash-task-title')!
    const live = screen.getByText('Live link').closest('.dash-task-title')!
    expect(paused.querySelector('.strike-ink.on')).not.toBeNull()
    expect(live.querySelector('.strike-ink.on')).toBeNull()
  })

  it('draws a strike under a share that is off, and keeps saying why', async () => {
    m.shares.mockResolvedValue([
      share({ id: 'a1', name: 'Mum' }),
      share({ id: 'e5', name: 'Aunt', enabled: false, switched_off_by_password: true }),
    ] as never)
    setup([{ id: 'h', kind: 'shares', x: 0, y: 0, w: 4, h: 4 }])
    await screen.findByText('Mum')
    const rowOf = (name: string) =>
      screen.getByText(name).closest('.dash-share-row') as HTMLElement
    expect(rowOf('Aunt').querySelector('.dash-task-title .strike-ink.on')).not.toBeNull()
    expect(rowOf('Mum').querySelector('.dash-task-title .strike-ink.on')).toBeNull()
    expect(within(rowOf('Aunt')).getByText('Off since your sign-in changed')).toBeInTheDocument()
  })
})
