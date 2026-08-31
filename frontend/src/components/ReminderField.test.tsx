// The "Remind me" picker — one control, two editors, one sidecar column.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NO_REMINDER, REMINDER_CHOICES, ReminderField, reminderLabel } from './ReminderField'

function show(over: Partial<Parameters<typeof ReminderField>[0]> = {}) {
  const onChange = vi.fn()
  render(<ReminderField value={null} onChange={onChange} {...over} />)
  return { onChange, field: () => document.getElementById('reminder') as HTMLSelectElement }
}

describe('the choices', () => {
  it('opens on "no reminder" when nothing is set', () => {
    const { field } = show()
    expect(field().value).toBe('')
    expect(screen.getByText("Don't notify")).toBeInTheDocument()
  })

  it('offers every standard lead plus the off option', () => {
    const { field } = show()
    expect(field().options.length).toBe(REMINDER_CHOICES.length + 1)
  })

  it('keeps a stored value the list does not offer', () => {
    // Rewriting someone's 45 minutes to 30 because this control has no row for
    // it would be the picker editing data it was only asked to display. A value
    // set through the API or the MCP connector has to survive being looked at.
    const { field } = show({ value: 45 })
    expect(field().value).toBe('45')
    expect(screen.getByText('45 minutes before')).toBeInTheDocument()
  })

  it('does not duplicate a value the list already has', () => {
    const { field } = show({ value: 30 })
    expect(field().options.length).toBe(REMINDER_CHOICES.length + 1)
  })
})

describe('changing it', () => {
  it('reports minutes when a lead is picked', () => {
    const { onChange, field } = show()
    fireEvent.change(field(), { target: { value: '15' } })
    expect(onChange).toHaveBeenCalledWith(15)
  })

  it('reports null for "no reminder"', () => {
    const { onChange, field } = show({ value: 15 })
    fireEvent.change(field(), { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('treats zero as a real lead, not as off', () => {
    // 0 means "tell me at the moment itself", which is why the clear sentinel is
    // -1 and cannot borrow falsiness.
    const { onChange, field } = show()
    fireEvent.change(field(), { target: { value: '0' } })
    expect(onChange).toHaveBeenCalledWith(0)
    expect(NO_REMINDER).toBe(-1)
  })
})

describe('reminderLabel', () => {
  const tr = (k: string, v?: Record<string, string | number>) =>
    ({ 'reminder.atTime': 'At the time',
       'reminder.minutes': `${v?.n} minutes before`,
       'reminder.hours': `${v?.n} hours before`,
       'reminder.days': `${v?.n} days before` } as Record<string, string>)[k] ?? k

  it('reads in the largest whole unit that fits', () => {
    expect(reminderLabel(0, tr)).toBe('At the time')
    expect(reminderLabel(5, tr)).toBe('5 minutes before')
    expect(reminderLabel(90, tr)).toBe('90 minutes before')
    expect(reminderLabel(60, tr)).toBe('1 hours before')
    expect(reminderLabel(1440, tr)).toBe('1 days before')
    expect(reminderLabel(2880, tr)).toBe('2 days before')
  })
})
