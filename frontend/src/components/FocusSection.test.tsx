import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FocusSection } from './FocusSection'
import { DEFAULT_FOCUS } from '../focus'
import { notifyPermission, requestNotify } from '../notify'

vi.mock('../notify', () => ({
  notifyPermission: vi.fn(() => 'default'),
  requestNotify: vi.fn(async () => 'granted'),
  showNotify: vi.fn(),
}))

const perm = vi.mocked(notifyPermission)

beforeEach(() => { vi.clearAllMocks(); perm.mockReturnValue('default') })
afterEach(() => vi.restoreAllMocks())

function show(over = {}) {
  const onChange = vi.fn()
  render(<FocusSection value={{ ...DEFAULT_FOCUS, ...over }} onChange={onChange} />)
  return onChange
}

describe('<FocusSection>', () => {
  it('commits a length on blur, clamped to the bounds the server keeps', async () => {
    const onChange = show()
    const field = screen.getByLabelText('Interval')
    await userEvent.clear(field)
    await userEvent.type(field, '50')
    expect(onChange).not.toHaveBeenCalled()      // not on every keystroke
    await userEvent.tab()
    expect(onChange).toHaveBeenCalledWith({ interval: 50 })
    await userEvent.clear(screen.getByLabelText('Break'))
    await userEvent.type(screen.getByLabelText('Break'), '999{Enter}')
    expect(onChange).toHaveBeenCalledWith({ brk: 60 })
    // 0 long breaks is a real answer, and says what it means.
    await userEvent.clear(screen.getByLabelText('Long break every'))
    await userEvent.type(screen.getByLabelText('Long break every'), '0{Enter}')
    expect(onChange).toHaveBeenCalledWith({ longEvery: 0 })
  })

  it('reads the two behaviours back as what they will do, and flips them', async () => {
    const onChange = show()
    // Named by their labels, like every toggle in Settings; what they SAY is
    // what pressing them will do.
    const end = screen.getByLabelText('When an interval ends')
    expect(end).toHaveAttribute('aria-pressed', 'false')
    expect(end).toHaveTextContent('Wait for me')
    await userEvent.click(end)
    expect(onChange).toHaveBeenCalledWith({ autoContinue: true })
    const cap = screen.getByLabelText('Estimates')
    expect(cap).toHaveTextContent('Work until done')
    await userEvent.click(cap)
    expect(onChange).toHaveBeenCalledWith({ capDefault: true })
    await userEvent.click(screen.getByLabelText('Chime'))
    expect(onChange).toHaveBeenCalledWith({ chime: false })
  })

  it('asks the browser only from a click, and only while the switch is on', async () => {
    show()
    expect(screen.queryByRole('button', { name: 'Allow notifications' })).not.toBeInTheDocument()
    const onChange = show({ notify: true })
    void onChange
    await userEvent.click(screen.getByRole('button', { name: 'Allow notifications' }))
    expect(requestNotify).toHaveBeenCalledTimes(1)
  })

  it('reports a blocked or absent permission rather than promising a sound', () => {
    perm.mockReturnValue('denied')
    show({ notify: true })
    expect(screen.getByText('Blocked in the browser')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Allow notifications' })).not.toBeInTheDocument()
  })
})
