// The notifications settings section: toggling a rule, the digest time field's
// commit-on-blur, and the one hint that is a warning.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { NotificationsSection } from './NotificationsSection'
import { TRIGGERS } from '../notifications'

function show(over: Partial<Parameters<typeof NotificationsSection>[0]> = {}) {
  const onTriggersChange = vi.fn()
  const onDigestTimeChange = vi.fn()
  const onEventLeadChange = vi.fn()
  render(<NotificationsSection
    triggers={{}} onTriggersChange={onTriggersChange}
    digestTime="07:30" onDigestTimeChange={onDigestTimeChange}
    eventLead={10} onEventLeadChange={onEventLeadChange}
    homeTz="America/New_York"
    {...over} />)
  return { onTriggersChange, onDigestTimeChange, onEventLeadChange }
}

describe('the rule rows', () => {
  it('renders one row per rule, all on by default', () => {
    show()
    const toggles = TRIGGERS.map((t) => document.getElementById(`notif-${t}`)!)
    expect(toggles).toHaveLength(TRIGGERS.length)
    for (const el of toggles) expect(el).toHaveAttribute('aria-pressed', 'true')
  })

  it('writes a sparse override when a rule is turned off', () => {
    const { onTriggersChange } = show()
    const el = document.getElementById('notif-daily_digest')!
    el.click()
    expect(onTriggersChange).toHaveBeenCalledWith({ daily_digest: false })
  })

  it('keeps the other overrides when one rule changes', () => {
    const { onTriggersChange } = show({ triggers: { sync_stalled: false } })
    document.getElementById('notif-event_starting')!.click()
    expect(onTriggersChange).toHaveBeenCalledWith({
      sync_stalled: false, event_starting: false,
    })
  })

  it('says which rules buzz and which arrive silently', () => {
    // Loud and quiet are fixed in the backend, so this is the only way the
    // owner learns what leaving a rule on actually costs them.
    show()
    expect(screen.getAllByText('buzzes')).toHaveLength(2)
    expect(screen.getAllByText('silent')).toHaveLength(2)
  })
})

describe('the digest time', () => {
  it('commits a well-formed time on blur', async () => {
    const user = userEvent.setup()
    const { onDigestTimeChange } = show()
    const field = document.getElementById('notif-digest-time') as HTMLInputElement
    await user.clear(field)
    await user.type(field, '06:45')
    await user.tab()
    expect(onDigestTimeChange).toHaveBeenCalledWith('06:45')
  })

  it('never emits an intermediate value while typing', async () => {
    // An <input type="time"> reports every keystroke, and a half-typed time is
    // both a wrong hour and a 422 that would take the whole settings PUT.
    const user = userEvent.setup()
    const { onDigestTimeChange } = show()
    const field = document.getElementById('notif-digest-time') as HTMLInputElement
    await user.clear(field)
    await user.type(field, '0')
    expect(onDigestTimeChange).not.toHaveBeenCalled()
  })

  it('snaps back to the stored value when the draft is unusable', async () => {
    const user = userEvent.setup()
    const { onDigestTimeChange } = show()
    const field = document.getElementById('notif-digest-time') as HTMLInputElement
    await user.clear(field)
    await user.tab()
    expect(onDigestTimeChange).not.toHaveBeenCalled()
    expect(field.value).toBe('07:30')
  })
})

describe('the home-timezone warning', () => {
  it('names the zone when one is set', () => {
    show()
    expect(screen.getByText(/America\/New_York/)).toBeInTheDocument()
  })

  it('warns when there is none, because the digest then never fires', () => {
    // A rule that is on but never fires is worse than one that is off.
    const { container } = render(<NotificationsSection
      triggers={{}} onTriggersChange={vi.fn()}
      digestTime="07:30" onDigestTimeChange={vi.fn()}
      eventLead={10} onEventLeadChange={vi.fn()}
      homeTz="" />)
    expect(container.querySelector('.hintline.warn')).toBeTruthy()
    expect(screen.getByText(/home timezone/i)).toBeInTheDocument()
  })
})

describe('the meeting lead', () => {
  it('is bounded at the floor the pipeline imposes', () => {
    show()
    const field = document.getElementById('notif-lead') as HTMLInputElement
    expect(field.min).toBe('3')
    expect(field.max).toBe('120')
  })
})
