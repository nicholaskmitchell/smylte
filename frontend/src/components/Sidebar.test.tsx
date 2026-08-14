import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ALL_SWATCH_STYLE, Sidebar, SWATCHES } from './Sidebar'
import type { List, TaskGroup } from '../api'

// A bare list; only the fields the sidebar reads matter here.
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

// Both the Tasks and Calendar sidebars use the same visibility-toggle config:
// every collection is shown, and the whole row is a checkbox that hides/shows it.
const toggleSidebar = (props: {
  hidden?: Set<string>
  onHiddenChange?: (next: string[]) => void
}) => (
  <Sidebar title="Lists" placeholder="List"
    items={[list('work', 'Work'), list('home', 'Home')]}
    countOf={(l) => l.open_count} onItems={() => {}} api={noopApi}
    hiddenIds={props.hidden ?? new Set()} onHiddenChange={props.onHiddenChange ?? (() => {})} />
)

describe('<Sidebar> per-collection visibility toggles', () => {
  it('shows every collection as a checkbox row — no separate "All" row', () => {
    render(toggleSidebar({}))
    const rows = screen.getAllByRole('checkbox')
    expect(rows).toHaveLength(2)              // Work + Home, and nothing else
    expect(screen.queryByText('All lists')).not.toBeInTheDocument()
    // Every list is on by default.
    rows.forEach((r) => expect(r).toHaveAttribute('aria-checked', 'true'))
  })

  it('hides a single list when its row is clicked anywhere', async () => {
    const onHiddenChange = vi.fn()
    render(toggleSidebar({ onHiddenChange }))
    // Click the list's *name* (not a tiny box) — the whole row is the toggle.
    await userEvent.click(screen.getByText('Work'))
    expect(onHiddenChange).toHaveBeenCalledWith(['work'])
  })

  it('reflects a hidden list and toggles it back on', async () => {
    const onHiddenChange = vi.fn()
    render(toggleSidebar({ hidden: new Set(['work']), onHiddenChange }))
    const workRow = screen.getByRole('checkbox', { name: /Work/ })
    expect(workRow).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(workRow)
    expect(onHiddenChange).toHaveBeenCalledWith([])   // 'work' removed from hidden
  })

  it('toggles from the keyboard (Space)', async () => {
    const onHiddenChange = vi.fn()
    render(toggleSidebar({ onHiddenChange }))
    const homeRow = screen.getByRole('checkbox', { name: /Home/ })
    homeRow.focus()
    await userEvent.keyboard(' ')
    expect(onHiddenChange).toHaveBeenCalledWith(['home'])
  })
})

describe('<Sidebar> "View completed" footer button', () => {
  const withCompleted = (props: { active?: boolean; onToggle?: () => void }) => (
    <Sidebar title="Lists" placeholder="List" items={[list('work', 'Work')]}
      countOf={(l) => l.open_count} onItems={() => {}} api={noopApi}
      hiddenIds={new Set()} onHiddenChange={() => {}}
      completedActive={props.active} onToggleCompleted={props.onToggle ?? (() => {})} />
  )

  it('renders only when onToggleCompleted is provided', () => {
    const { rerender } = render(
      <Sidebar title="Lists" placeholder="List" items={[list('work', 'Work')]}
        countOf={(l) => l.open_count} onItems={() => {}} api={noopApi}
        hiddenIds={new Set()} onHiddenChange={() => {}} />,
    )
    expect(screen.queryByText(/View completed/)).not.toBeInTheDocument()
    rerender(withCompleted({}))
    expect(screen.getByText(/View completed/)).toBeInTheDocument()
  })

  it('calls onToggleCompleted when clicked, and flips its label when active', async () => {
    const onToggle = vi.fn()
    const { rerender } = render(withCompleted({ onToggle }))
    await userEvent.click(screen.getByText(/View completed/))
    expect(onToggle).toHaveBeenCalledTimes(1)
    rerender(withCompleted({ onToggle, active: true }))
    expect(screen.getByText(/Back to tasks/)).toBeInTheDocument()
  })
})

// On phones the sidebar collapses to a trigger bar that opens a bottom-sheet
// drawer. The drawer is where rename / recolor / delete / group all live —
// none of which the old horizontal chip strip could reach on touch.
describe('<Sidebar> mobile management drawer', () => {
  const stubMatchMedia = (matches: boolean) => {
    window.matchMedia = ((query: string) => ({
      matches, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia
  }
  beforeEach(() => stubMatchMedia(true))   // force the mobile breakpoint
  afterEach(() => stubMatchMedia(false))   // restore the desktop stub for other suites

  const groupApi = () => ({
    create: vi.fn(async () => undefined),
    update: vi.fn(async () => list('work', 'Work')),
    remove: vi.fn(async () => undefined),
    reorder: vi.fn(async () => undefined),
  })

  const mobileSidebar = (over: Partial<{
    api: ReturnType<typeof groupApi>
    onHiddenChange: (next: string[]) => void
    groups: TaskGroup[]
    onGroupsChange: (next: TaskGroup[]) => void
  }> = {}) => (
    <Sidebar title="Lists" placeholder="List"
      items={[list('work', 'Work'), list('home', 'Home')]}
      countOf={(l) => l.open_count} onItems={() => {}}
      api={over.api ?? noopApi}
      hiddenIds={new Set()} onHiddenChange={over.onHiddenChange ?? (() => {})}
      groups={over.groups} onGroupsChange={over.onGroupsChange}
      collapsedGroups={[]} onCollapsedGroupsChange={() => {}} />
  )

  const openDrawer = async () => {
    // The trigger carries the title text ("Lists") plus a "shown" summary.
    await userEvent.click(screen.getByRole('button', { name: /Lists/ }))
  }

  it('hides the lists behind a trigger bar until the drawer is opened', async () => {
    render(mobileSidebar())
    // No list rows on the resting bar (the old strip showed them all inline).
    expect(screen.queryByText('Work')).not.toBeInTheDocument()
    await openDrawer()
    expect(screen.getByText('Work')).toBeInTheDocument()
    expect(screen.getByText('Home')).toBeInTheDocument()
  })

  it('exposes a per-list edit affordance and renames from it', async () => {
    const api = groupApi()
    render(mobileSidebar({ api }))
    await openDrawer()
    // Every list has a reachable ⋯ edit button — the bug was that mobile had none.
    await userEvent.click(screen.getByRole('button', { name: 'Edit Work' }))
    const nameField = screen.getByDisplayValue('Work')
    await userEvent.clear(nameField)
    await userEvent.type(nameField, 'Workflow')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    // Only the field the user changed — the color is not resent.
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Workflow' })
  })

  it('deletes a list from the drawer (two-tap confirm)', async () => {
    const api = groupApi()
    render(mobileSidebar({ api }))
    await openDrawer()
    await userEvent.click(screen.getByRole('button', { name: 'Edit Home' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: /Really delete/ }))
    expect(api.remove).toHaveBeenCalledWith('home')
  })

  it('toggles list visibility by tapping a row in the drawer', async () => {
    const onHiddenChange = vi.fn()
    render(mobileSidebar({ onHiddenChange }))
    await openDrawer()
    await userEvent.click(screen.getByText('Work'))
    expect(onHiddenChange).toHaveBeenCalledWith(['work'])
  })

  it('creates and deletes groups from the drawer', async () => {
    const onGroupsChange = vi.fn()
    const { rerender } = render(mobileSidebar({ groups: [], onGroupsChange }))
    await openDrawer()
    // Create a group.
    await userEvent.click(screen.getByRole('button', { name: 'New group' }))
    await userEvent.type(screen.getByPlaceholderText('Group name'), 'Focus{Enter}')
    expect(onGroupsChange).toHaveBeenCalledWith([
      expect.objectContaining({ name: 'Focus', lists: [] }),
    ])
    // With a group present, its header offers rename + delete on touch.
    rerender(mobileSidebar({ groups: [{ id: 'g1', name: 'Focus', lists: [] }], onGroupsChange }))
    expect(screen.getByText('Focus')).toBeInTheDocument()
    await userEvent.click(screen.getByTitle('Delete group'))
    await userEvent.click(screen.getByRole('button', { name: /delete\?/ }))
    expect(onGroupsChange).toHaveBeenLastCalledWith([])
  })
})

// Groups are visually separated by a hairline rule (CSS on `.side-group +
// .side-group` / `.side-group + .ungrouped`). The one bit of state the
// stylesheet cannot work out on its own is whether the trailing ungrouped
// block actually holds any rows — an empty one must not draw a dangling rule.
describe('<Sidebar> group dividers', () => {
  const grouped = (groups: TaskGroup[]) => (
    <Sidebar title="Lists" placeholder="List"
      items={[list('work', 'Work'), list('home', 'Home')]}
      countOf={(l) => l.open_count} onItems={() => {}} api={noopApi}
      hiddenIds={new Set()} onHiddenChange={() => {}}
      groups={groups} onGroupsChange={() => {}}
      collapsedGroups={[]} onCollapsedGroupsChange={() => {}} />
  )

  it('marks the ungrouped block empty only when nothing is left ungrouped', () => {
    const { container, rerender } = render(grouped([{ id: 'g1', name: 'Focus', lists: ['work'] }]))
    // 'Home' is still ungrouped, so the block draws its divider.
    expect(container.querySelector('.ungrouped')).not.toHaveClass('is-empty')
    rerender(grouped([{ id: 'g1', name: 'Focus', lists: ['work', 'home'] }]))
    expect(container.querySelector('.ungrouped')).toHaveClass('is-empty')
  })

  it('renders one .side-group per group, so adjacent groups get a rule between them', () => {
    const { container } = render(grouped([
      { id: 'g1', name: 'Focus', lists: ['work'] },
      { id: 'g2', name: 'Later', lists: ['home'] },
    ]))
    expect(container.querySelectorAll('.side-group')).toHaveLength(2)
  })
})

describe('the "All" swatch ring', () => {
  it('reproduces the gradient it replaced in app.css exactly', () => {
    // The ring used to be a second, hand-written copy of the palette in CSS.
    // It is now built from SWATCHES so there is one definition — this pins the
    // rendered result to the string that shipped, byte for byte.
    expect(ALL_SWATCH_STYLE.background).toBe(
      'conic-gradient(#D9480F, #B8860B, #2E7D32, #00838F, #1565C0, #6A1B9A, #D9480F)')
  })

  it('draws the ring from the same palette the color picker offers', () => {
    for (const color of ['#D9480F', '#B8860B', '#2E7D32']) {
      expect(SWATCHES).toContain(color)
      expect(ALL_SWATCH_STYLE.background).toContain(color)
    }
  })
})

// ── a wire color may carry an alpha byte, and must survive an edit ──────────
// Apple Calendar and DAVx5 write calendar-color as #RRGGBBAA. The modal
// truncated it to the RGB prefix for the swatch comparison and then saved THAT,
// so opening the modal to rename a list PROPPATCHed the shortened color back and
// dropped the alpha for every other client.

describe('<Sidebar> edit modal colors', () => {
  const editApi = () => ({
    create: vi.fn(async () => undefined),
    update: vi.fn(async () => list('work', 'Work')),
    remove: vi.fn(async () => undefined),
    reorder: vi.fn(async () => undefined),
  })

  const withColor = (color: string | null, api: ReturnType<typeof editApi>) => (
    <Sidebar title="Lists" placeholder="List" items={[list('work', 'Work', color)]}
      countOf={(l) => l.open_count} onItems={() => {}} api={api}
      hiddenIds={new Set()} onHiddenChange={() => {}} />
  )

  const openEdit = async () =>
    userEvent.click(screen.getByRole('button', { name: 'Edit Work' }))

  it('does not resend a color the user never touched', async () => {
    const api = editApi()
    render(withColor('#FF9500FF', api))
    await openEdit()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Work' })
  })

  it('keeps the alpha byte when only the name changes', async () => {
    const api = editApi()
    render(withColor('#FF9500FF', api))
    await openEdit()
    const nameField = screen.getByDisplayValue('Work')
    await userEvent.clear(nameField)
    await userEvent.type(nameField, 'Workflow')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Workflow' })
  })

  it('still marks the matching swatch active despite the alpha byte', async () => {
    render(withColor('#D9480FFF', editApi()))
    await openEdit()
    expect(document.querySelector('.color-dot.on')).toHaveAttribute('title', '#D9480F')
  })

  it('sends the new color when the user actually picks one', async () => {
    const api = editApi()
    render(withColor('#FF9500FF', api))
    await openEdit()
    await userEvent.click(screen.getByTitle('#1565C0'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Work', color: '#1565C0' })
  })

  it('sends null when the user clears the color', async () => {
    const api = editApi()
    render(withColor('#FF9500FF', api))
    await openEdit()
    await userEvent.click(screen.getByTitle('No color'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Work', color: null })
  })
})

describe('<Sidebar> extra section', () => {
  // The calendar tab's Tasks section rides in this slot. It is passed as a node
  // rather than described, because those rows are a different kind of
  // collection borrowed for visibility only — none of this sidebar's
  // rename/recolor/delete/reorder applies to them.
  const withExtra = () => (
    <Sidebar title="Calendars" placeholder="Calendar"
      items={[list('work', 'Work')]}
      countOf={(l) => l.open_count} onItems={() => {}} api={noopApi}
      hiddenIds={new Set()} onHiddenChange={() => {}}
      extra={<div data-testid="extra">Tasks</div>} />
  )

  it('renders under the collections in the desktop panel', () => {
    render(withExtra())
    const slot = screen.getByTestId('extra')
    expect(slot).toBeInTheDocument()
    // Inside the same scroller as the collections, after them.
    const body = slot.closest('.side-list')!
    expect(body).toBeTruthy()
    expect(body.querySelector('.side-item')!.compareDocumentPosition(slot))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  it('renders in the mobile drawer too, not only on desktop', async () => {
    // One slot for both layouts — a section only the desktop panel showed would
    // be unreachable on a phone.
    const realMatchMedia = window.matchMedia
    window.matchMedia = ((q: string) => ({
      matches: true, media: q, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia
    try {
      await mobileDrawerShowsExtra()
    } finally {
      window.matchMedia = realMatchMedia
    }
  })

  const mobileDrawerShowsExtra = async () => {
    render(withExtra())
    expect(screen.queryByTestId('extra')).not.toBeInTheDocument()   // drawer shut
    await userEvent.click(screen.getByRole('button', { name: /Calendars/ }))
    expect(screen.getByTestId('extra')).toBeInTheDocument()
  }

  it('is absent when nothing is passed', () => {
    render(toggleSidebar({}))
    expect(screen.queryByTestId('extra')).not.toBeInTheDocument()
  })
})
