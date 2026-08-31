// The notifications settings section: toggling a rule, the digest time field's
// commit-on-blur, and the one hint that is a warning.
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { NotificationsSection } from './NotificationsSection'
import { DEFAULT_OFF, DEFAULT_ON, TRIGGERS, TRIGGER_IS_LOUD } from '../notifications'

function show(over: Partial<Parameters<typeof NotificationsSection>[0]> = {}) {
  const onTriggersChange = vi.fn()
  const onDigestTimeChange = vi.fn()
  const onEventLeadChange = vi.fn()
  const onEnabledChange = vi.fn()
  const onChatIdChange = vi.fn()
  const onTokenChange = vi.fn()
  render(<NotificationsSection
    enabled onEnabledChange={onEnabledChange}
    chatId="8517516151" onChatIdChange={onChatIdChange}
    tokenSet={false} botId="" onTokenChange={onTokenChange}
    onExpire={vi.fn()}
    triggers={{}} onTriggersChange={onTriggersChange}
    digestTime="07:30" onDigestTimeChange={onDigestTimeChange}
    eventLead={10} onEventLeadChange={onEventLeadChange}
    eveningTime="21:00" onEveningTimeChange={vi.fn()}
    taskLead={30} onTaskLeadChange={vi.fn()}
    homeTz="America/New_York"
    {...over} />)
  return { onTriggersChange, onDigestTimeChange, onEventLeadChange,
           onEnabledChange, onChatIdChange, onTokenChange }
}

describe('the rule rows', () => {
  it('renders every rule, on in the first tier and off in the second', () => {
    show()
    for (const t of DEFAULT_ON) {
      expect(document.getElementById(`notif-${t}`), t).toHaveAttribute('aria-pressed', 'true')
    }
    for (const t of DEFAULT_OFF) {
      expect(document.getElementById(`notif-${t}`), t).toHaveAttribute('aria-pressed', 'false')
    }
  })

  it('separates the two tiers rather than listing thirteen rows flat', () => {
    // "These are what the app thinks you need" and "these are available if you
    // disagree" are different statements, and a flat list makes neither.
    show()
    expect(screen.getByText('Off by default')).toBeInTheDocument()
    expect(screen.getByText(/know your own days better/)).toBeInTheDocument()
  })

  it('gives every opt-in rule the reason it is off', () => {
    // A rule you switch on should come with the reason the app did not switch
    // it on for you.
    show()
    for (const t of DEFAULT_OFF) {
      const label = document.querySelector(`label[for="notif-${t}"]`)
      const hint = label?.closest('.notif-rule')?.querySelector('.hintline')
      expect(hint?.textContent, t).toBeTruthy()
      expect(hint!.textContent!.length, t).toBeGreaterThan(40)
    }
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
    const loud = TRIGGERS.filter((t) => TRIGGER_IS_LOUD[t]).length
    expect(screen.getAllByText('buzzes')).toHaveLength(loud)
    expect(screen.getAllByText('silent')).toHaveLength(TRIGGERS.length - loud)
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
      enabled onEnabledChange={vi.fn()}
      chatId="" onChatIdChange={vi.fn()}
      tokenSet={false} botId="" onTokenChange={vi.fn()}
      onExpire={vi.fn()}
      triggers={{}} onTriggersChange={vi.fn()}
      digestTime="07:30" onDigestTimeChange={vi.fn()}
      eventLead={10} onEventLeadChange={vi.fn()}
      eveningTime="21:00" onEveningTimeChange={vi.fn()}
      taskLead={30} onTaskLeadChange={vi.fn()}
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


// ── the Telegram connection ──────────────────────────────────────────────────

describe('the bot token', () => {
  it('is a password field that starts empty even when one is stored', () => {
    // There is nothing to prefill it with: the server never sends the token
    // back, so the field can only ever be a place to type a new one.
    render(<NotificationsSection
      enabled onEnabledChange={vi.fn()}
      chatId="1" onChatIdChange={vi.fn()}
      tokenSet botId="123456789" onTokenChange={vi.fn()}
      onExpire={vi.fn()}
      triggers={{}} onTriggersChange={vi.fn()}
      digestTime="07:30" onDigestTimeChange={vi.fn()}
      eventLead={10} onEventLeadChange={vi.fn()}
      eveningTime="21:00" onEveningTimeChange={vi.fn()}
      taskLead={30} onTaskLeadChange={vi.fn()}
      homeTz="America/New_York" />)
    const field = document.getElementById('notif-token') as HTMLInputElement
    expect(field.type).toBe('password')
    expect(field.value).toBe('')
    // It says WHICH bot without being able to speak as it.
    expect(field.placeholder).toContain('123456789')
  })

  it('saves a pasted token on blur and then forgets it', async () => {
    const user = userEvent.setup()
    const { onTokenChange } = show()
    const field = document.getElementById('notif-token') as HTMLInputElement
    await user.type(field, '123:AAHsecret')
    await user.tab()
    expect(onTokenChange).toHaveBeenCalledWith('123:AAHsecret')
    expect(field.value).toBe('')
  })

  it('does not treat an emptied field as a request to disconnect', async () => {
    // A stray click in a field the owner never meant to touch must not silently
    // disconnect the bot. Remove is the only thing that clears it.
    const user = userEvent.setup()
    const { onTokenChange } = show({ tokenSet: true, botId: '1' })
    const field = document.getElementById('notif-token') as HTMLInputElement
    await user.click(field)
    await user.tab()
    expect(onTokenChange).not.toHaveBeenCalled()
  })

  it('offers Remove only when there is something to remove', async () => {
    const user = userEvent.setup()
    expect(screen.queryByText('Remove it')).toBeNull()
    const { onTokenChange } = show({ tokenSet: true, botId: '1' })
    await user.click(screen.getByText('Remove it'))
    expect(onTokenChange).toHaveBeenCalledWith('')
  })
})

describe('the master switch', () => {
  it('reports and toggles', async () => {
    const user = userEvent.setup()
    const { onEnabledChange } = show()
    const el = document.getElementById('notif-enabled')!
    expect(el).toHaveAttribute('aria-pressed', 'true')
    await user.click(el)
    expect(onEnabledChange).toHaveBeenCalledWith(false)
  })
})

describe('the chat id', () => {
  it('writes what was typed, trimmed', () => {
    // fireEvent rather than user.type: the field is CONTROLLED and this harness
    // does not feed the new value back, so typing would report one character at
    // a time against a value that never advances. One change event is the same
    // thing the real parent sees.
    const { onChatIdChange } = show({ chatId: '' })
    fireEvent.change(document.getElementById('notif-chat') as HTMLInputElement,
      { target: { value: '  8517516151 ' } })
    expect(onChatIdChange).toHaveBeenCalledWith('8517516151')
  })
})
