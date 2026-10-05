// The Suggested pane: what a row says about where it came from, what approving
// it sends, and that nothing can be pressed twice while a request is out.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SuggestionsPane } from './SuggestionsPane'
import { api, type List, type MailSuggestion } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})

const m = vi.mocked(api)

const list = (id: string, name: string): List => ({
  id, href: `/${id}/`, name, is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
})

const task = (over: Partial<MailSuggestion> = {}): MailSuggestion => ({
  id: 'abc', kind: 'task', status: 'pending', title: 'Return the permission slip',
  notes: 'Ms Smith asked for it signed.', due: '2026-10-09', confidence: 0.87,
  event: null, target: null,
  source: {
    sender: 'office@school.example', sender_name: 'Ms Smith',
    subject: 'Trip on Friday', sent_at: '2026-10-05T08:00:00Z',
    message_id: 'm1@school.example', thread_id: 'mid:m1@school.example', folder: 'INBOX',
  },
  updates: [], created_at: '2026-10-05T08:01:00Z', decided_at: null, result: null,
  ...over,
})

function show(over: Partial<Parameters<typeof SuggestionsPane>[0]> = {}) {
  const onApprove = vi.fn().mockResolvedValue(true)
  const onReject = vi.fn().mockResolvedValue(true)
  render(<SuggestionsPane onExpire={vi.fn()} lists={[list('l1', 'Home'), list('l2', 'Work')]}
    items={[task()]} loaded error={null} onApprove={onApprove} onReject={onReject}
    {...over} />)
  return { onApprove, onReject }
}

beforeEach(() => {
  vi.clearAllMocks()
  m.calendars.mockResolvedValue([])
})
afterEach(cleanup)

describe('a task suggestion', () => {
  it('says what it would become and who it came from', () => {
    show()
    const row = document.querySelector('.mail-sug')!
    expect(row).toHaveAttribute('data-kind', 'task')
    expect(row.querySelector('.mail-kind')).toHaveTextContent('Task')
    expect(row.querySelector('.mail-sug-src')).toHaveTextContent('From Ms Smith · Trip on Friday')
    // How sure the model was is a hint on the row, not a ranking.
    expect(screen.getByTitle('How sure the model was')).toHaveTextContent('87%')
  })

  it('falls back to the address when the sender sent no name', () => {
    show({ items: [task({ source: { ...task().source, sender_name: null } })] })
    expect(document.querySelector('.mail-sug-src')).toHaveTextContent('From office@school.example')
  })

  it('mentions the later messages folded into it', () => {
    const updates = [{ sender: 'a@b.example', subject: null, sent_at: null, notes: 'n', due: null }]
    show({ items: [task({ updates })] })
    expect(document.querySelector('.mail-sug-src')).toHaveTextContent('+1 later message')
  })

  it('keeps the details behind a disclosure', () => {
    show()
    expect(screen.getByText('Details').closest('details')).not.toHaveAttribute('open')
    expect(screen.getByText('Ms Smith asked for it signed.')).toBeInTheDocument()
  })

  it('sends the edited title and date on approve', async () => {
    const user = userEvent.setup()
    const { onApprove } = show()
    const title = screen.getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Sign the form')
    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-10-12' } })
    await user.click(screen.getByRole('button', { name: 'Add task' }))
    expect(onApprove).toHaveBeenCalledWith('abc', { title: 'Sign the form', due: '2026-10-12' })
  })

  it('sends a cleared date as null, and leaves the list out unless one was chosen', async () => {
    const user = userEvent.setup()
    const { onApprove } = show()
    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '' } })
    await user.click(screen.getByRole('button', { name: 'Add task' }))
    expect(onApprove).toHaveBeenCalledWith('abc', { title: 'Return the permission slip', due: null })
  })

  it('sends the chosen list', async () => {
    const user = userEvent.setup()
    const { onApprove } = show()
    await user.selectOptions(screen.getByLabelText('Add to list'), 'l2')
    await user.click(screen.getByRole('button', { name: 'Add task' }))
    expect(onApprove).toHaveBeenCalledWith('abc',
      { title: 'Return the permission slip', due: '2026-10-09', list: 'l2' })
  })

  it('will not approve a row with no title', async () => {
    const user = userEvent.setup()
    show()
    await user.clear(screen.getByLabelText('Title'))
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled()
  })

  it('dismisses through onReject', async () => {
    const user = userEvent.setup()
    const { onReject, onApprove } = show()
    await user.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(onReject).toHaveBeenCalledWith('abc')
    expect(onApprove).not.toHaveBeenCalled()
  })

  it('disables both buttons while a request is out', async () => {
    const user = userEvent.setup()
    show({ onApprove: vi.fn(() => new Promise<boolean>(() => {})) })
    await user.click(screen.getByRole('button', { name: 'Add task' }))
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeDisabled()
  })
})

describe('an update suggestion', () => {
  it('names the task it adds to and offers no list', () => {
    show({
      items: [task({ kind: 'update', target: { list: 'l1', uid: 'u1', title: 'Buy paint' } })],
    })
    expect(screen.getByText('Adds to “Buy paint”')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply update' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Add to list')).toBeNull()
    // It still has a date to move, like a task.
    expect(screen.getByLabelText('Due date')).toBeInTheDocument()
  })
})

describe('an event suggestion', () => {
  const event = task({
    kind: 'event', title: 'Parent evening', due: null,
    event: {
      start: '2026-10-14T18:30:00', end: '2026-10-14T20:00:00', all_day: false,
      location: 'Room 4', rrule: null,
    },
  })

  it('shows when and where, with no date to edit', async () => {
    m.calendars.mockResolvedValue([list('c1', 'Family')])
    show({ items: [event] })
    const when = document.querySelector('.mail-sug .hintline')!
    expect(when).toHaveTextContent('Room 4')
    expect(when).toHaveTextContent(/6:30/)
    expect(screen.queryByLabelText('Due date')).toBeNull()
    expect(screen.getByRole('button', { name: 'Add event' })).toBeInTheDocument()
    // Let the lazy calendar fetch land before the test ends.
    await screen.findByRole('option', { name: 'Family' })
  })

  it('fetches the calendars only once an event is on screen', async () => {
    show({ items: [task()] })
    expect(m.calendars).not.toHaveBeenCalled()
    cleanup()
    m.calendars.mockResolvedValue([list('c1', 'Family')])
    show({ items: [event] })
    expect(await screen.findByRole('option', { name: 'Family' })).toBeInTheDocument()
    expect(m.calendars).toHaveBeenCalledTimes(1)
  })

  it('sends only the title, and the calendar when one was chosen', async () => {
    const user = userEvent.setup()
    m.calendars.mockResolvedValue([list('c1', 'Family')])
    const { onApprove } = show({ items: [event] })
    await user.click(screen.getByRole('button', { name: 'Add event' }))
    expect(onApprove).toHaveBeenLastCalledWith('abc', { title: 'Parent evening' })
    await user.selectOptions(screen.getByLabelText('Add to calendar'), await screen.findByRole('option', { name: 'Family' }))
    await user.click(screen.getByRole('button', { name: 'Add event' }))
    expect(onApprove).toHaveBeenLastCalledWith('abc', { title: 'Parent evening', calendar: 'c1' })
  })
})

describe('the pane itself', () => {
  it('says so when nothing is waiting', () => {
    show({ items: [] })
    expect(screen.getByText(/Nothing waiting/)).toBeInTheDocument()
  })

  it('says nothing before the first answer has arrived', () => {
    show({ items: [], loaded: false })
    expect(screen.queryByText(/Nothing waiting/)).toBeNull()
  })

  it('shows a failure above whatever is still listed', () => {
    show({ error: 'this suggestion was just handled elsewhere' })
    expect(screen.getByRole('status')).toHaveTextContent('handled elsewhere')
    expect(screen.getByLabelText('Title')).toBeInTheDocument()
  })
})
