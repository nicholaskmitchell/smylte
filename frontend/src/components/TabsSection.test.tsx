import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TabsSection } from './TabsSection'
import { DEFAULT_TAB_ORDER, type Tab, type TabStart } from '../tabs'

function show(order: Tab[] = DEFAULT_TAB_ORDER, start: TabStart = 'home') {
  const onOrderChange = vi.fn()
  const onStartChange = vi.fn()
  render(<TabsSection order={order} start={start} onOrderChange={onOrderChange}
    onStartChange={onStartChange} />)
  return { onOrderChange, onStartChange }
}

describe('<TabsSection>', () => {
  it('lists the tabs in their current order', () => {
    show(['calendar', 'home', 'tasks', 'scheduling'])
    const names = [...document.querySelectorAll('.tab-order-row .name')].map((n) => n.textContent)
    expect(names).toEqual(['Calendar', 'Home', 'Tasks', 'Scheduling'])
  })

  it('moves a tab along the strip', async () => {
    const { onOrderChange } = show()
    await userEvent.click(screen.getByRole('button', { name: 'Move Tasks left' }))
    expect(onOrderChange).toHaveBeenCalledWith(['tasks', 'home', 'calendar', 'scheduling'])

    await userEvent.click(screen.getByRole('button', { name: 'Move Tasks right' }))
    expect(onOrderChange).toHaveBeenLastCalledWith(['home', 'calendar', 'tasks', 'scheduling'])
  })

  it('cannot move the ends off the strip', () => {
    show()
    expect(screen.getByRole('button', { name: 'Move Home left' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move Scheduling right' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move Home right' })).toBeEnabled()
  })

  it('picks the tab the app opens on', async () => {
    const { onStartChange } = show()
    await userEvent.selectOptions(screen.getByLabelText('Opens on'), 'calendar')
    expect(onStartChange).toHaveBeenCalledWith('calendar')
  })

  it('offers remembering the last used tab', async () => {
    const { onStartChange } = show()
    await userEvent.selectOptions(screen.getByLabelText('Opens on'), 'last')
    expect(onStartChange).toHaveBeenCalledWith('last')
  })

  it('shows the current choice', () => {
    show(DEFAULT_TAB_ORDER, 'last')
    expect(screen.getByLabelText('Opens on')).toHaveValue('last')
  })

  // Dismissal is no longer this component's business: it is a section body
  // inside the settings panel, and the panel owns Escape and the way out.

  it('keeps focus on the arrow that was pressed, so a tab can be moved twice', async () => {
    // The rows swap places on a move; without the refocus a keyboard reorder
    // would drop focus to the body after the first press.
    const { rerender } = renderControlled()
    await userEvent.click(screen.getByRole('button', { name: 'Move Scheduling left' }))
    rerender()
    expect(screen.getByRole('button', { name: 'Move Scheduling left' })).toHaveFocus()
  })
})

/** A section that actually applies its own reorder, for the focus assertion. */
function renderControlled() {
  let order: Tab[] = [...DEFAULT_TAB_ORDER]
  const view = render(<TabsSection order={order} start="home"
    onOrderChange={(next) => { order = next }} onStartChange={vi.fn()} />)
  return {
    rerender: () => view.rerender(<TabsSection order={order} start="home"
      onOrderChange={(next) => { order = next }} onStartChange={vi.fn()} />),
  }
}
