import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Sidebar } from './Sidebar'
import type { List } from '../api'

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
