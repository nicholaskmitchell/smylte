// The sidebar and the Suggested pane under Field notes: no tooltip anywhere, no
// line explaining the drawer, and every control that lost its tooltip still has
// a name. Presets keep their titles; Sidebar.test.tsx and SuggestionsPane.test.tsx
// pin those by title.
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Sidebar, SWATCHES } from './Sidebar'
import { SuggestionsPane } from './SuggestionsPane'
import { api, type List, type MailSuggestion, type TaskGroup } from '../api'
import { setBreakpoint } from '../test/setup'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})

const m = vi.mocked(api)

const list = (id: string, name: string, color: string | null = null): List => ({
  id, href: `/dav/${id}/`, name, is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color,
})

const noopApi = {
  create: vi.fn(async () => undefined),
  update: vi.fn(async () => undefined),
  remove: vi.fn(async () => undefined),
  reorder: vi.fn(async () => undefined),
}

const groups: TaskGroup[] = [
  { id: 'g1', name: 'Focus', lists: ['work'] },
  { id: 'g2', name: 'Later', lists: [] },
]

const sidebar = (over: Partial<Parameters<typeof Sidebar>[0]> = {}) => (
  <Sidebar kind="list"
    items={[list('work', 'Work', SWATCHES[0]), list('home', 'Home')]}
    countOf={(l) => l.open_count} onItems={() => {}} api={noopApi}
    sel="work" onSelect={() => {}} allLabel="All lists" onToggle={() => {}}
    hiddenIds={new Set()} onHiddenChange={() => {}}
    onToggleCompleted={() => {}} onToggleParked={() => {}}
    onToggleSuggested={() => {}} suggestedCount={2}
    onArchive={() => {}}
    groups={groups} onGroupsChange={() => {}}
    collapsedGroups={[]} onCollapsedGroupsChange={() => {}}
    {...over} />
)

const titled = () => document.querySelectorAll('[title]')

beforeEach(() => {
  vi.clearAllMocks()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
  m.calendars.mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  document.documentElement.removeAttribute('data-surface')
})

describe('<Sidebar> under Field notes', () => {
  it('has no title on the desktop panel, and keeps its names', () => {
    render(sidebar())
    expect(titled()).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'New list' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rename group Focus' }))
      .toBeInTheDocument()
  })

  it('has no title on the collapsed rail, and its dots are reachable by name', () => {
    render(sidebar({ collapsed: true }))
    expect(titled()).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'All lists' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Work' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Home' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('has no title in the edit modal, and its swatches are reachable by name', async () => {
    render(sidebar())
    await userEvent.click(screen.getByRole('button', { name: 'Edit Work' }))
    const dialog = screen.getByRole('dialog')
    expect(dialog.querySelectorAll('[title]')).toHaveLength(0)
    expect(titled()).toHaveLength(0)
    for (const c of SWATCHES) {
      expect(screen.getByRole('button', { name: c })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'No color' })).toBeInTheDocument()
    expect(screen.getByLabelText('Custom color')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Archive' })).not.toHaveAttribute('title')
  })

  it('has no title on the add form\'s colour row', async () => {
    render(sidebar())
    await userEvent.click(screen.getByRole('button', { name: 'New list' }))
    expect(screen.getByRole('button', { name: SWATCHES[1] })).toBeInTheDocument()
    expect(titled()).toHaveLength(0)
  })

  it('renders an empty group as an empty drop zone, with no words', () => {
    render(sidebar())
    const zones = document.querySelectorAll('.group-empty')
    expect(zones).toHaveLength(1)           // Later has no lists; Focus has one
    expect(zones[0]).toBeEmptyDOMElement()
    expect(screen.queryByText(/Drag a list here/)).not.toBeInTheDocument()
  })

  describe('on a phone', () => {
    beforeEach(() => act(() => setBreakpoint(true)))

    it('has no title on the bar, and none in the drawer, and no hint', async () => {
      render(sidebar())
      expect(titled()).toHaveLength(0)
      expect(screen.getByRole('button', { name: 'View completed' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Suggested from email' })).toBeInTheDocument()

      await userEvent.click(screen.getByRole('button', { name: /Lists/ }))
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(titled()).toHaveLength(0)
      expect(document.querySelector('.drawer-hint')).toBeNull()
      expect(screen.queryByText(/Tap a list to show or hide it/)).not.toBeInTheDocument()
      const zone = document.querySelector('.group-empty')!
      expect(zone).toBeEmptyDOMElement()
      expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
    })
  })
})

describe('<SuggestionsPane> under Field notes', () => {
  it('has no title on the confidence and still shows it', () => {
    const s: MailSuggestion = {
      id: 'abc', kind: 'task', status: 'pending', title: 'Return the permission slip',
      notes: '', due: null, confidence: 0.87, event: null, target: null,
      source: {
        sender: 'office@school.example', sender_name: 'Ms Smith',
        subject: 'Trip on Friday', sent_at: '2026-10-05T08:00:00Z',
        message_id: 'm1@school.example', thread_id: 'mid:m1@school.example', folder: 'INBOX',
      },
      updates: [], created_at: '2026-10-05T08:01:00Z', decided_at: null, result: null,
    }
    render(<SuggestionsPane onExpire={vi.fn()} lists={[list('l1', 'Home')]}
      items={[s]} loaded error={null}
      onApprove={vi.fn()} onReject={vi.fn()} />)
    expect(screen.getByText('87%')).toBeInTheDocument()
    expect(screen.queryByTitle('How sure the model was')).not.toBeInTheDocument()
    expect(titled()).toHaveLength(0)
  })
})
