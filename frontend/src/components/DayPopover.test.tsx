import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DayPopover } from './DayPopover'
import type { DayEv } from '../calendar'

const ev = (o: Partial<DayEv> = {}): DayEv => ({
  uid: 'e', id: 'e', recurrence_id: null, is_recurring: false, calendar: '/c/',
  summary: 'Standup', description: null, location: null,
  start: '2026-08-03T09:00:00', start_is_date: false, end: '2026-08-03T09:30:00',
  end_is_date: false, duration: null, all_day: false, status: null, busy: true, tags: [], has_rrule: false,
  href: '/c/e.ics', etag: '"1"', ...o,
})

function show(events: DayEv[], props: Partial<Parameters<typeof DayPopover>[0]> = {}) {
  const onClose = vi.fn()
  render(<DayPopover day="2026-08-03" x={40} y={40} events={events}
    styleOf={() => ({ '--ev-c': '#1565C0' } as React.CSSProperties)}
    onClose={onClose} {...props} />)
  return { onClose }
}

describe('<DayPopover>', () => {
  it('lists one row per event under the day heading', () => {
    show([ev({ id: 'a', summary: 'Standup' }), ev({ id: 'b', summary: 'Retro' })])
    const pop = screen.getByRole('dialog')
    expect(within(pop).getByText('Standup')).toBeInTheDocument()
    expect(within(pop).getByText('Retro')).toBeInTheDocument()
    expect(within(pop).getByText(/Mon, Aug 3/)).toBeInTheDocument()
  })

  it('is read-only when no onOpen is given', () => {
    show([ev()])
    // The whole read-only contract: nothing inside is actionable, so the Home
    // dashboard never becomes an event editor.
    expect(within(screen.getByRole('dialog')).queryByRole('button')).toBeNull()
  })

  it('opens an event when onOpen is given', async () => {
    const onOpen = vi.fn()
    show([ev()], { onOpen })
    await userEvent.click(screen.getByRole('button', { name: /Standup/ }))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 'e' }))
  })

  it('closes on Escape and on a backdrop click', async () => {
    const { onClose } = show([ev()])
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
    await userEvent.click(document.querySelector('.pop-backdrop')!)
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('does not close when the popover itself is clicked', async () => {
    const { onClose } = show([ev()])
    await userEvent.click(screen.getByRole('dialog'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('labels all-day, continuation and timed events differently', () => {
    show([
      ev({ id: 'a', summary: 'Holiday', all_day: true }),
      ev({ id: 'b', summary: 'Conference', cont: true, end: '2026-08-05T17:00:00' }),
      ev({ id: 'c', summary: 'Trip', cont: true, end: '2026-08-03T11:00:00' }),
    ])
    const pop = screen.getByRole('dialog')
    // "Holiday" is all day; "Conference" runs past today, so it reads all day
    // too; "Trip" finishes today, so it shows the end time instead.
    expect(within(pop).getAllByText('all day')).toHaveLength(2)
    expect(within(pop).getByText(/^–/)).toBeInTheDocument()
  })

  it('applies the per-calendar tint to each row', () => {
    show([ev()])
    expect(document.querySelector('.agenda-ev')!.getAttribute('style'))
      .toContain('--ev-c: #1565C0')
  })

  it('clamps to the viewport so an edge cell cannot push it off-screen', () => {
    show([ev()], { x: 99999, y: 99999 })
    const pop = screen.getByRole('dialog') as HTMLElement
    expect(parseInt(pop.style.left)).toBeLessThan(window.innerWidth)
    expect(parseInt(pop.style.top)).toBeLessThan(window.innerHeight)
  })
})
