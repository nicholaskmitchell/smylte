// Settings → Shares: the section that decides what a read-only link reaches.
// Shaped after DisplaysSection's suite, and for the same reason: a regression
// here is silent by construction, since every state renders confident prose.
// The cases that matter most are the ones where a share differs from a display
// — an emptied allowlist means NOTHING, so no click may collapse or widen it.

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SharesSection } from './SharesSection'
import { api, HttpError, type Share, type ShareView } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})

const m = vi.mocked(api)

const SHARE: Share = {
  id: 'a'.repeat(32), name: 'Mum', token: 'tok-mum', url: null,
  lists: [], calendars: [], show_focus: false, horizon_days: 7,
  enabled: true, switched_off_by_password: false, last_seen_at: null,
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
}
const OTHER: Share = { ...SHARE, id: 'b'.repeat(32), name: 'Dad', token: 'tok-dad' }

const CALS = [{ id: 'work', name: 'Work' }, { id: 'home', name: 'Home' }, { id: 'old', name: 'Old' }]
const LISTS = [{ id: 'inbox', name: 'Inbox' }, { id: 'chores', name: 'Chores' }]

beforeEach(() => {
  vi.clearAllMocks()
  cleanup()
  m.calendars.mockResolvedValue(CALS as never)
  m.lists.mockResolvedValue(LISTS as never)
  // The server replaces the row with what it stored; echoing the body is the
  // same thing for every field these tests write.
  m.patchShare.mockImplementation((async (id: string, body: object) =>
    ({ ...SHARE, id, ...body })) as never)
})

const mount = (props: { archived?: string[] } = {}) =>
  render(<SharesSection onExpire={vi.fn()} {...props} />)

/** Open the editor on the first row. */
const openEditor = async (name = 'Mum') => {
  const row = (await screen.findByText(name)).closest('.disp') as HTMLElement
  await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
  return row
}

/** The name field inside an open editor. The add box at the foot of the section
 *  asks the same question ("Who is it for?"), so the editor's is found by scope. */
const nameField = (row: HTMLElement) => within(row).getByRole('textbox', { name: 'Who is it for?' })

describe('<SharesSection>', () => {
  it('says the account has no shares only when it really has none', async () => {
    m.shares.mockResolvedValue([] as never)
    const { unmount } = mount()
    expect(await screen.findByText(/no shares yet/i)).toBeInTheDocument()
    unmount()

    // A failed fetch is not an empty account: "none" over a 502 would be a lie
    // on the only screen that can revoke a link.
    m.shares.mockRejectedValue(new HttpError(502, 'bad gateway'))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn’t load/i)
    expect(screen.queryByText(/no shares yet/i)).not.toBeInTheDocument()
  })

  it('creates a share with its name only, and opens its editor', async () => {
    m.shares.mockResolvedValue([] as never)
    m.createShare.mockResolvedValue(SHARE as never)
    mount()
    await screen.findByText(/no shares yet/i)
    await userEvent.type(screen.getByRole('textbox', { name: 'Who is it for?' }), 'Mum')
    await userEvent.click(screen.getByRole('button', { name: 'Create link' }))
    await waitFor(() => expect(m.createShare).toHaveBeenCalledWith({ name: 'Mum' }))
    // Straight into the editor, where the link and the pickers are.
    expect(await screen.findByText(`${location.origin}/share/tok-mum`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Done' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('shows a new share as showing nothing, and says so twice', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    mount()
    expect(await screen.findByText('Shows nothing')).toBeInTheDocument()
    await openEditor()
    expect(screen.getByRole('status')).toHaveTextContent(/shows nothing/i)
    expect(screen.getByText(/marked private in other apps show as Busy/i)).toBeInTheDocument()
  })

  it('prefers the server’s absolute url, and falls back to the origin', async () => {
    m.shares.mockResolvedValue([{ ...SHARE, url: 'https://smylte.example/share/tok-mum' }] as never)
    mount()
    await openEditor()
    expect(screen.getByText('https://smylte.example/share/tok-mum')).toBeInTheDocument()
  })
})

describe('the lists and calendars a share reaches', () => {
  it('writes one id when the first list is turned on', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'Inbox' }))
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { lists: ['inbox'] })
  })

  it('writes [] when the last chip is turned off, never "everything"', async () => {
    // The opposite of a display: an emptied allowlist is NOTHING, so the write
    // narrows the link exactly as the click says.
    m.shares.mockResolvedValue([{ ...SHARE, lists: ['inbox'] }] as never)
    mount()
    await openEditor()
    const inbox = screen.getByRole('button', { name: 'Inbox', pressed: true })
    expect(inbox).toBeEnabled()
    await userEvent.click(inbox)
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { lists: [] })
  })

  it('writes every id when all are selected, never []', async () => {
    m.shares.mockResolvedValue([{ ...SHARE, lists: ['inbox'] }] as never)
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'Chores' }))
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { lists: ['inbox', 'chores'] })
  })

  it('offers an archived calendar only while it is selected, muted', async () => {
    m.shares.mockResolvedValue([SHARE, { ...OTHER, calendars: ['old'] }] as never)
    mount({ archived: ['old'] })
    const mum = await openEditor('Mum')
    expect(within(mum).queryByRole('button', { name: 'Old' })).not.toBeInTheDocument()
    expect(within(mum).getByRole('button', { name: 'Work' })).toBeInTheDocument()

    const dad = await openEditor('Dad')
    const old = within(dad).getByRole('button', { name: 'Old' })
    expect(old).toHaveAttribute('aria-pressed', 'true')
    expect(old).toHaveAttribute('title', 'Archived — not shown')
  })

  it('writes the focus toggle', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'Focus session' }))
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { show_focus: true })
  })

  it('writes how far ahead the agenda reaches, and marks the current choice', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    mount()
    await openEditor()
    const group = screen.getByRole('group', { name: 'How far ahead' })
    expect(within(group).getAllByRole('button').map((b) => b.textContent))
      .toEqual(['Today', '1 week', '2 weeks', '4 weeks'])
    expect(within(group).getByRole('button', { name: '1 week' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(within(group).getByRole('button', { name: '4 weeks' }))
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { horizon_days: 28 })
    await waitFor(() =>
      expect(within(group).getByRole('button', { name: '4 weeks' })).toHaveAttribute('aria-pressed', 'true'))

    // Choosing what is already chosen writes nothing.
    m.patchShare.mockClear()
    await userEvent.click(within(group).getByRole('button', { name: '4 weeks' }))
    expect(m.patchShare).not.toHaveBeenCalled()
  })

  it('puts a failed edit back on that row only', async () => {
    m.shares.mockResolvedValue([SHARE, OTHER] as never)
    m.patchShare.mockRejectedValue(new HttpError(500, 'nope'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mount()
    const mum = await openEditor('Mum')
    await userEvent.click(within(mum).getByRole('button', { name: 'Inbox' }))
    await waitFor(() => expect(m.patchShare).toHaveBeenCalled())
    await waitFor(() =>
      expect(within(mum).getByRole('button', { name: 'Inbox' })).toHaveAttribute('aria-pressed', 'false'))
    // Dad's row is untouched and still listed.
    expect(screen.getByText('Dad')).toBeInTheDocument()
  })
})

describe('the link itself', () => {
  it('rotating keeps the editor open and shows the new url', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    m.rotateShareToken.mockResolvedValue({ ...SHARE, token: 'tok-fresh' } as never)
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'New link' }))
    expect(await screen.findByText(`${location.origin}/share/tok-fresh`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Done' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('asks before deleting, then removes the row', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    m.deleteShare.mockResolvedValue(null as never)
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    expect(m.deleteShare).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Delete share' }))
    await waitFor(() => expect(m.deleteShare).toHaveBeenCalledWith(SHARE.id))
    expect(screen.queryByText('Mum')).not.toBeInTheDocument()
  })

  it('puts a row back where it was when its delete fails', async () => {
    m.shares.mockResolvedValue([SHARE, OTHER] as never)
    m.deleteShare.mockRejectedValue(new HttpError(500, 'nope'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mount()
    await openEditor('Mum')
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete share' }))
    await waitFor(() => expect(m.deleteShare).toHaveBeenCalled())
    await waitFor(() => {
      const names = [...document.querySelectorAll('.disp-name')].map((n) => n.textContent)
      expect(names).toEqual(['Mum', 'Dad'])
    })
  })

  it('commits a renamed share on blur, and Escape drops the draft', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    mount()
    const row = await openEditor()
    const field = nameField(row)
    await userEvent.clear(field)
    await userEvent.type(field, 'Mother{Escape}')
    expect(field).toHaveValue('Mum')
    expect(m.patchShare).not.toHaveBeenCalled()

    await userEvent.clear(field)
    await userEvent.type(field, 'Mother')
    await userEvent.tab()
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { name: 'Mother' })
  })
})

describe('whether the link is on', () => {
  it('switches a link off and on', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    mount()
    await openEditor()
    const toggle = screen.getByRole('button', { name: 'Link' })
    expect(toggle).toHaveTextContent('On')
    await userEvent.click(toggle)
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { enabled: false })
  })

  it('says a password change switched it off, shows it Off, and turning it on clears that', async () => {
    // The server reports `enabled` false for such a link; the sentence is what
    // tells the owner WHY, and the toggle must agree with it.
    m.shares.mockResolvedValue([{ ...SHARE, enabled: false, switched_off_by_password: true }] as never)
    mount()
    expect(await screen.findByText(/switched off because your password changed/i)).toBeInTheDocument()
    await openEditor()
    const toggle = screen.getByRole('button', { name: 'Link' })
    expect(toggle).toHaveTextContent('Off')
    expect(toggle).toHaveAttribute('aria-pressed', 'false')

    await userEvent.click(toggle)
    expect(m.patchShare).toHaveBeenCalledWith(SHARE.id, { enabled: true })
    await waitFor(() =>
      expect(screen.queryByText(/switched off because your password changed/i)).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Link' })).toHaveTextContent('On')
  })

  it('shows the Off chip for a link that is plainly off, without the password sentence', async () => {
    m.shares.mockResolvedValue([{ ...SHARE, enabled: false }] as never)
    mount()
    await screen.findByText('Mum')
    expect(screen.getByText('Off')).toBeInTheDocument()
    expect(screen.queryByText(/password changed/i)).not.toBeInTheDocument()
  })
})

describe('when it was last opened', () => {
  afterEach(() => { vi.useRealTimers() })

  it('says Open now within two minutes, and the date otherwise', async () => {
    const now = Date.now()
    m.shares.mockResolvedValue([
      { ...SHARE, last_seen_at: new Date(now - 30_000).toISOString() },
      { ...OTHER, last_seen_at: new Date(now - 3 * 3_600_000).toISOString() },
    ] as never)
    mount()
    await screen.findByText('Mum')
    expect(screen.getByText('Open now')).toBeInTheDocument()
    expect(screen.getByText(/^Last opened /)).toBeInTheDocument()
  })

  it('refreshes last_seen_at every 30 seconds without clobbering a draft', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    m.shares.mockResolvedValue([SHARE] as never)
    mount()
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    const row = await openEditor()
    const field = nameField(row)
    await userEvent.clear(field)
    await userEvent.type(field, 'Mother')

    // The server has meanwhile been opened, AND renamed elsewhere: only the
    // first of those may reach the screen.
    m.shares.mockResolvedValue([
      { ...SHARE, name: 'Renamed elsewhere', last_seen_at: new Date().toISOString() },
    ] as never)
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })

    expect(screen.getByText('Open now')).toBeInTheDocument()
    expect(field).toHaveValue('Mother')
    expect(document.querySelector('.disp-name')).toHaveTextContent('Mum')
  })
})

describe('the preview', () => {
  const VIEW: ShareView = {
    v: 1, generated_at: '2026-10-26T14:00:00.000Z', poll_seconds: 30, day: '2026-10-26', days: 7,
    focus: null, calendars: [], events: [], events_more: 0,
    lists: [{
      name: 'Chores', color: null, more: 0,
      tasks: [{ title: 'Water the plants', due: null, all_day: false, depth: 0, private: false }],
    }],
  }

  it('renders what the viewer sees, and hides it again', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    m.sharePreview.mockResolvedValue(VIEW as never)
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'See what they see' }))
    expect(m.sharePreview).toHaveBeenCalledWith(SHARE.id)
    expect(await screen.findByText('Water the plants')).toBeInTheDocument()
    expect(screen.getByText(/exactly what they see right now/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Hide preview' }))
    expect(screen.queryByText('Water the plants')).not.toBeInTheDocument()
  })

  it('says so when the preview cannot be loaded', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    m.sharePreview.mockRejectedValue(new HttpError(500, 'nope'))
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'See what they see' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn’t load the preview/i)
  })

  it('is dropped by any edit, so it never shows a link as it used to be', async () => {
    m.shares.mockResolvedValue([SHARE] as never)
    m.sharePreview.mockResolvedValue(VIEW as never)
    mount()
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'See what they see' }))
    await screen.findByText('Water the plants')
    await userEvent.click(screen.getByRole('button', { name: 'Inbox' }))
    await waitFor(() => expect(screen.queryByText('Water the plants')).not.toBeInTheDocument())
  })
})
