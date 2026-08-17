import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
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

// ── a failed delete has to put back everything it took ──────────────────────

describe('<Sidebar> a delete that fails', () => {
  const withGroups = (over: {
    api?: { create: unknown; update: unknown; remove: unknown; reorder: unknown }
    onItems?: (next: List[]) => void
    onGroupsChange?: (next: TaskGroup[]) => void
    groups?: TaskGroup[]
  }) => (
    <Sidebar title="Lists" placeholder="List"
      items={[list('work', 'Work'), list('home', 'Home')]}
      countOf={(l) => l.open_count} onItems={over.onItems ?? (() => {})}
      api={(over.api ?? noopApi) as typeof noopApi}
      hiddenIds={new Set()} onHiddenChange={() => {}}
      groups={over.groups ?? [{ id: 'g1', name: 'Focus', lists: ['work', 'home'] }]}
      onGroupsChange={over.onGroupsChange ?? (() => {})}
      collapsedGroups={[]} onCollapsedGroupsChange={() => {}} />
  )

  const deleteHome = async () => {
    await userEvent.click(screen.getByRole('button', { name: 'Edit Home' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: /Really delete/ }))
  }

  it('restores the group membership, not just the list', async () => {
    // `remove` strips the list out of every group and calls onGroupsChange —
    // which App writes straight through to the server — BEFORE awaiting the
    // DELETE. Only `items` was rolled back, so a failed delete brought the list
    // back UNGROUPED, with the loss already persisted server-side and nothing
    // left to undo it from.
    const groups: TaskGroup[] = [{ id: 'g1', name: 'Focus', lists: ['work', 'home'] }]
    const api = { ...noopApi, remove: vi.fn(async () => undefined) }
    const onItems = vi.fn()
    const onGroupsChange = vi.fn()
    render(withGroups({ api, onItems, onGroupsChange, groups }))

    await deleteHome()

    expect(api.remove).toHaveBeenCalledWith('home')
    // Optimistic strip, then the rollback — both halves.
    expect(onGroupsChange.mock.calls.map((c) => c[0])).toEqual([
      [{ id: 'g1', name: 'Focus', lists: ['work'] }],
      groups,
    ])
    expect(onItems).toHaveBeenLastCalledWith([list('work', 'Work'), list('home', 'Home')])
  })

  it('leaves the groups alone when the delete succeeds', async () => {
    const api = { ...noopApi, remove: vi.fn(async () => null) }
    const onGroupsChange = vi.fn()
    render(withGroups({ api, onGroupsChange }))

    await deleteHome()

    expect(onGroupsChange).toHaveBeenCalledTimes(1)
    expect(onGroupsChange.mock.calls[0][0]).toEqual([{ id: 'g1', name: 'Focus', lists: ['work'] }])
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

describe('<Sidebar> a hostile wire color', () => {
  // `color` is served verbatim from another client's `ical:calendar-color`. The
  // swatch writes it into a `background`, and the hidden variant interpolates
  // it into a `boxShadow` SHORTHAND — which lets it escape the property
  // boundary more freely still. A `url(...)` there is a fetch on every render.
  const hostile = 'url(https://evil.example/beacon.png)'

  const withWireColor = (hiddenIds: Set<string>) => (
    <Sidebar title="Lists" placeholder="List"
      items={[{ ...list('work', 'Work'), color: hostile }]}
      countOf={(l) => l.open_count} onItems={() => {}} api={noopApi}
      hiddenIds={hiddenIds} onHiddenChange={() => {}}
      collapsedGroups={[]} onCollapsedGroupsChange={() => {}} />
  )

  it('renders no inline background for it', () => {
    const { container } = render(withWireColor(new Set()))
    const swatch = container.querySelector('.side-item .swatch') as HTMLElement
    expect(swatch).not.toBeNull()
    expect(swatch.getAttribute('style') ?? '').not.toContain('url(')
    expect(swatch.style.background).toBe('')
  })

  it('does not smuggle it through the hidden-state boxShadow either', () => {
    const { container } = render(withWireColor(new Set(['work'])))
    const swatch = container.querySelector('.side-item .swatch') as HTMLElement
    expect(swatch.getAttribute('style') ?? '').not.toContain('evil.example')
    expect(swatch.style.boxShadow).toContain('var(--fg-faint)')
  })
})

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

  // A native colour input cannot be driven by a click — there is no picker to
  // open in jsdom — so set the value the way the UA would and fire the change.
  const custom = () => screen.getByLabelText('Custom color') as HTMLInputElement
  // The input is invisible on top of the label; the label is the square that
  // shows the colour and wears .on, so selection asserts against the wrapper.
  const customDot = () => custom().closest('.color-dot') as HTMLElement
  const pickCustom = (hex: string) => fireEvent.change(custom(), { target: { value: hex } })

  it('sends a color picked past the presets, without the old alpha byte', async () => {
    const api = editApi()
    render(withColor('#FF9500FF', api))
    await openEdit()
    pickCustom('#123456')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Work', color: '#123456' })
  })

  it('marks the custom square active for a color no preset covers', async () => {
    render(withColor('#FF9500FF', editApi()))
    await openEdit()
    expect(customDot()).toHaveClass('on')
    // ...and it is the only thing selected — no preset claims it too.
    expect(document.querySelectorAll('.color-dot.on')).toHaveLength(1)
    // It paints the colour itself, rather than leaving the spectrum showing.
    expect(customDot()).toHaveStyle({ background: '#ff9500' })
  })

  it('leaves the custom square inactive when a preset is the color', async () => {
    render(withColor('#D9480FFF', editApi()))
    await openEdit()
    expect(customDot()).not.toHaveClass('on')
  })

  it('seeds the custom square from the current color, alpha trimmed', async () => {
    render(withColor('#FF9500FF', editApi()))
    await openEdit()
    expect(custom().value).toBe('#ff9500')
  })

  it('does not resend a color the user only saw in the custom square', async () => {
    const api = editApi()
    render(withColor('#FF9500FF', api))
    await openEdit()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Work' })
  })

  it('hands the square back to a preset once one is clicked', async () => {
    render(withColor('#FF9500FF', editApi()))
    await openEdit()
    await userEvent.click(screen.getByTitle('#1565C0'))
    expect(customDot()).not.toHaveClass('on')
    expect(document.querySelectorAll('.color-dot.on')).toHaveLength(1)
  })

  it('leaves the square inactive, on a neutral seed, when there is no color', async () => {
    render(withColor(null, editApi()))
    await openEdit()
    expect(customDot()).not.toHaveClass('on')
    expect(custom().value).toBe('#808080')
  })

  // The same wire value the hostile-color suite guards on the sidebar swatch
  // reaches this square's background too — it is the one dot whose fill is not
  // a constant from SWATCHES.
  it('never paints a hostile wire color into the custom square', async () => {
    render(withColor('url(https://evil.example/beacon.png)', editApi()))
    await openEdit()
    expect(customDot().getAttribute('style') ?? '').not.toContain('evil.example')
    expect(customDot().style.background).toBe('')
    expect(custom().value).toBe('#808080')
    // Nothing in the row claims it: junk is not a color any square represents.
    expect(document.querySelectorAll('.color-dot.on')).toHaveLength(0)
  })

  it('does not rewrite a color the user picked away from and back to', async () => {
    const api = editApi()
    render(withColor('#FF9500', api))
    await openEdit()
    // The picker only ever reports lower-case, so landing back on the colour the
    // list already had returns `#ff9500` against a stored `#FF9500`. A bare !==
    // would PROPPATCH that case flip out to every other client as a recolour.
    // (Two events on purpose: React fires no change for a value already in the
    // input, and the seed is the lowered current colour — so a single
    // same-value change would assert nothing.)
    pickCustom('#123456')
    pickCustom('#ff9500')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.update).toHaveBeenCalledWith('work', { name: 'Work' })
  })
})

describe('<Sidebar> color on a new collection', () => {
  const addApi = () => ({
    create: vi.fn(async (name: string) => list('new', name)),
    update: vi.fn(async () => undefined),
    remove: vi.fn(async () => undefined),
    reorder: vi.fn(async () => undefined),
  })

  const withApi = (api: ReturnType<typeof addApi>) => (
    <Sidebar title="Calendars" placeholder="Calendar" items={[]}
      countOf={(l) => l.open_count} onItems={() => {}} api={api}
      hiddenIds={new Set()} onHiddenChange={() => {}} />
  )

  const openAdd = async () => userEvent.click(screen.getByTitle('New calendar'))
  const nameField = () => screen.getByPlaceholderText('Calendar')

  it('creates with the color picked before the name was committed', async () => {
    const api = addApi()
    render(withApi(api))
    await openAdd()
    await userEvent.click(screen.getByTitle('#1565C0'))
    await userEvent.type(nameField(), 'Travel{Enter}')
    expect(api.create).toHaveBeenCalledWith('Travel', '#1565C0')
  })

  it('creates with a color from past the presets', async () => {
    const api = addApi()
    render(withApi(api))
    await openAdd()
    fireEvent.change(screen.getByLabelText('Custom color'), { target: { value: '#123456' } })
    await userEvent.type(nameField(), 'Travel{Enter}')
    expect(api.create).toHaveBeenCalledWith('Travel', '#123456')
  })

  it('creates with no color when none is picked', async () => {
    const api = addApi()
    render(withApi(api))
    await openAdd()
    await userEvent.type(nameField(), 'Travel{Enter}')
    expect(api.create).toHaveBeenCalledWith('Travel', null)
  })

  // The row is part of the form, so choosing from it must not dismiss the form
  // the way clicking away from an empty name field still does.
  it('stays open while picking a color with the name still empty', async () => {
    render(withApi(addApi()))
    await openAdd()
    await userEvent.click(screen.getByTitle('#1565C0'))
    expect(nameField()).toBeInTheDocument()
    expect(screen.getByTitle('#1565C0')).toHaveClass('on')
  })

  it('still closes an empty form when focus leaves it entirely', async () => {
    render(
      <>
        <button>elsewhere</button>
        <Sidebar title="Calendars" placeholder="Calendar" items={[]}
          countOf={(l) => l.open_count} onItems={() => {}} api={addApi()}
          hiddenIds={new Set()} onHiddenChange={() => {}} />
      </>,
    )
    await openAdd()
    await userEvent.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(screen.queryByPlaceholderText('Calendar')).not.toBeInTheDocument()
  })

  // The mobile drawer renders its own copy of the add form inside the bottom
  // sheet, reached by a different button. Same component, different container —
  // and on a phone the drawer is the *only* way to add a collection at all.
  it('creates with a color from the mobile drawer too', async () => {
    const stub = (matches: boolean) => {
      window.matchMedia = ((query: string) => ({
        matches, media: query, onchange: null,
        addEventListener: () => {}, removeEventListener: () => {},
        addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
      })) as unknown as typeof window.matchMedia
    }
    stub(true)
    try {
      const api = addApi()
      render(withApi(api))
      await userEvent.click(screen.getByRole('button', { name: 'New calendar' }))
      await userEvent.click(screen.getByTitle('#6A1B9A'))
      await userEvent.type(nameField(), 'Travel{Enter}')
      expect(api.create).toHaveBeenCalledWith('Travel', '#6A1B9A')
    } finally {
      stub(false)
    }
  })

  it('keeps a half-typed name when focus leaves', async () => {
    render(
      <>
        <button>elsewhere</button>
        <Sidebar title="Calendars" placeholder="Calendar" items={[]}
          countOf={(l) => l.open_count} onItems={() => {}} api={addApi()}
          hiddenIds={new Set()} onHiddenChange={() => {}} />
      </>,
    )
    await openAdd()
    await userEvent.type(screen.getByPlaceholderText('Calendar'), 'Trav')
    await userEvent.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(screen.getByPlaceholderText('Calendar')).toHaveValue('Trav')
  })
})

// This suite runs with `css: false` (vite.config.ts), so nothing above ever
// sees a painted pixel — the component contract is asserted there, and the
// rules that turn it into a square are asserted here, read off disk the way
// appearance.test.ts pins tokens.css. Not a substitute for looking at it: this
// catches the rules being dropped or renamed, not them being ugly.
describe('the custom square’s stylesheet', () => {
  // From process.cwd() (the frontend dir) rather than import.meta.url, which
  // is not a file: URL under this environment — the same way util.test.ts
  // reaches the backend's COLOR_PATTERN. Comments are stripped first: the
  // rules below are *explained* in prose that names the very selectors and
  // properties being asserted, so matching raw text would read the commentary
  // rather than the CSS.
  const appCss = readFileSync(resolve(process.cwd(), 'src/styles/app.css'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')

  /** The body of one CSS rule, or null if the selector is not in the file. */
  const rule = (selector: string): string | null => {
    const at = appCss.indexOf(selector + ' {')
    return at < 0 ? null : appCss.slice(at + selector.length + 2, appCss.indexOf('}', at))
  }

  it('paints a spectrum, so an unpicked square is not a ninth color', () => {
    // Without this the label is transparent and the square reads as empty —
    // and the inline fill only ever covers the *picked* state.
    expect(rule('.color-dot.custom')).toContain('conic-gradient')
  })

  it('clips the fill to the dot', () => {
    // The input inside is a rectangle; without overflow the gradient and the
    // picked color spill past the radius on the rounded preset.
    expect(rule('.color-dot.custom')).toContain('overflow: hidden')
  })

  it('stretches the input over the whole square and hides it', () => {
    const input = rule('.color-dot.custom > input')
    expect(input).not.toBeNull()
    // opacity, not display/visibility: the input must stay hit-testable and in
    // the tab order, since it is the only thing that opens the picker.
    expect(input).toContain('opacity: 0')
    expect(input).toMatch(/width:\s*100%/)
    expect(input).toMatch(/height:\s*100%/)
  })

  it('draws a focus ring without :has()', () => {
    // The input carries focus but cannot show it. :has() is used nowhere else
    // in these sheets, and a browser that cannot parse it drops the whole rule
    // — which would leave the keyboard user no focus indicator at all.
    expect(rule('.color-dot.custom:focus-within')).toContain('outline')
    expect(appCss).not.toContain(':has(')
  })

  it('stacks the add form, and only the add form', () => {
    // .side-add is shared with add-group, rename-group and quick-add, which are
    // all one control on one line and must stay that way.
    expect(rule('.side-add.with-color')).toContain('flex-direction: column')
    expect(rule('.side-add')).not.toContain('flex-direction')
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
