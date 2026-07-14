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

describe('<Sidebar> per-collection visibility toggles', () => {
  // Tasks: the combined "All lists" view shows every list with its own checkbox.
  it('toggles a single list off from the combined Tasks view without changing focus', async () => {
    const onHiddenChange = vi.fn()
    const onSelect = vi.fn()
    render(
      <Sidebar title="Lists" placeholder="List" allLabel="All lists"
        items={[list('work', 'Work'), list('home', 'Home')]} sel="*"
        countOf={(l) => l.open_count} onSelect={onSelect} onItems={() => {}}
        api={noopApi} hiddenIds={new Set()} onHiddenChange={onHiddenChange} />,
    )
    // Every list gets a labelled checkbox — the calendar-style toggle.
    const boxes = screen.getAllByRole('button', { name: 'Hide from All lists' })
    expect(boxes).toHaveLength(2)
    expect(boxes[0]).toHaveAttribute('aria-pressed', 'true')

    // Clicking a list's checkbox hides just that list — and does NOT focus it.
    await userEvent.click(boxes[0])
    expect(onHiddenChange).toHaveBeenCalledWith(['work'])
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('focuses a single list when its name is clicked (toggle stays independent)', async () => {
    const onHiddenChange = vi.fn()
    const onSelect = vi.fn()
    render(
      <Sidebar title="Lists" placeholder="List" allLabel="All lists"
        items={[list('work', 'Work'), list('home', 'Home')]} sel="*"
        countOf={(l) => l.open_count} onSelect={onSelect} onItems={() => {}}
        api={noopApi} hiddenIds={new Set()} onHiddenChange={onHiddenChange} />,
    )
    await userEvent.click(screen.getByText('Home'))
    expect(onSelect).toHaveBeenCalledWith('home')
    expect(onHiddenChange).not.toHaveBeenCalled()
  })

  it('a hidden list offers to be shown again', () => {
    render(
      <Sidebar title="Lists" placeholder="List" allLabel="All lists"
        items={[list('work', 'Work'), list('home', 'Home')]} sel="*"
        countOf={(l) => l.open_count} onSelect={() => {}} onItems={() => {}}
        api={noopApi} hiddenIds={new Set(['work'])} onHiddenChange={() => {}} />,
    )
    const shown = screen.getByRole('button', { name: 'Show in All lists' })
    expect(shown).toHaveAttribute('aria-pressed', 'false')
  })

  // Calendar: no per-calendar focus, so the whole row is the checkbox.
  it('toggles a calendar by clicking its row (whole row is the checkbox)', async () => {
    const onHiddenChange = vi.fn()
    render(
      <Sidebar title="Calendars" placeholder="Calendar"
        items={[list('cal-a', 'Personal'), list('cal-b', 'Team')]}
        countOf={(l) => l.event_count} onItems={() => {}}
        api={noopApi} hiddenIds={new Set()} onHiddenChange={onHiddenChange} />,
    )
    const rows = screen.getAllByRole('checkbox')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(rows[1])
    expect(onHiddenChange).toHaveBeenCalledWith(['cal-b'])
  })
})
