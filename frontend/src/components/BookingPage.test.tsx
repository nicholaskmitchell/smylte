import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BookingPage } from './BookingPage'
import { api, HttpError, type PublicBookingInfo } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return {
    ...mod,
    api: { ...mod.api, publicBookingInfo: vi.fn(), publicBook: vi.fn() },
  }
})

const infoMock = vi.mocked(api.publicBookingInfo)
const bookMock = vi.mocked(api.publicBook)

// Mid-day UTC times keep the local-day grouping stable in any test timezone.
const INFO: PublicBookingInfo = {
  token: 'tok', title: 'Intro call', description: 'Say hi', duration_minutes: 30,
  timezone: 'UTC',
  slots: [
    { start: '2026-07-20T10:00:00+00:00', end: '2026-07-20T10:30:00+00:00' },
    { start: '2026-07-20T11:00:00+00:00', end: '2026-07-20T11:30:00+00:00' },
    { start: '2026-07-21T10:00:00+00:00', end: '2026-07-21T10:30:00+00:00' },
  ],
}

beforeEach(() => {
  infoMock.mockReset()
  bookMock.mockReset()
})

describe('<BookingPage>', () => {
  it('shows the not-found card when the link is dead (404)', async () => {
    infoMock.mockRejectedValue(new HttpError(404, 'unknown booking link'))
    render(<BookingPage token="dead" />)
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument()
  })

  it('renders title, duration, and day tabs from the link info', async () => {
    infoMock.mockResolvedValue(INFO)
    render(<BookingPage token="tok" />)
    expect(await screen.findByText('Intro call')).toBeInTheDocument()
    expect(screen.getByText('30 min')).toBeInTheDocument()
    expect(screen.getByText('Say hi')).toBeInTheDocument()
    // First day selected: its two slot buttons render.
    expect(document.querySelectorAll('.slot-btn')).toHaveLength(2)
  })

  it('renders hostile link content as inert text, never as markup', async () => {
    // The title/description are attacker-adjacent (the public page shows
    // whatever the link owner typed) — they must render escaped.
    infoMock.mockResolvedValue({
      ...INFO,
      title: '<img src=x onerror="window.__pwned=true">',
      description: '<script>window.__pwned=true</script>',
    })
    render(<BookingPage token="tok" />)
    expect(await screen.findByText('<img src=x onerror="window.__pwned=true">'))
      .toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('script')).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it('books a slot end-to-end: pick, confirm, done', async () => {
    infoMock.mockResolvedValue(INFO)
    bookMock.mockResolvedValue({
      id: 'b1', start: INFO.slots[0].start, end: INFO.slots[0].end,
      title: 'Intro call', duration_minutes: 30, timezone: 'UTC',
    })
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    await userEvent.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    await userEvent.type(screen.getAllByRole('textbox')[0], 'Ada')
    const email = document.querySelector('input[type="email"]') as HTMLInputElement
    await userEvent.type(email, 'ada@example.com')
    await userEvent.click(screen.getByRole('button', { name: /confirm booking/i }))

    expect(bookMock).toHaveBeenCalledWith('tok', {
      client_id: expect.any(String),
      start: INFO.slots[0].start, name: 'Ada', email: 'ada@example.com', notes: undefined,
    })
    expect(await screen.findByText(/you're booked, ada/i)).toBeInTheDocument()
  })

  it('replays the same client_id when a failed booking is retried', async () => {
    // `fetch` rejects both when the write never landed and when the response
    // was lost after the CalDAV PUT committed. The page keeps the slot selected
    // and re-enables the button, so retrying is the obvious move — and a fresh
    // idempotency key per call made that retry a SECOND event on the owner's
    // calendar, then told the visitor their own slot "was just taken".
    infoMock.mockResolvedValue(INFO)
    bookMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    bookMock.mockResolvedValue({
      id: 'b1', start: INFO.slots[0].start, end: INFO.slots[0].end,
      title: 'Intro call', duration_minutes: 30, timezone: 'UTC',
    })
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    await userEvent.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    await userEvent.type(screen.getAllByRole('textbox')[0], 'Ada')
    const email = document.querySelector('input[type="email"]') as HTMLInputElement
    await userEvent.type(email, 'ada@example.com')
    const confirm = screen.getByRole('button', { name: /confirm booking/i })
    await userEvent.click(confirm)
    await screen.findByText(/failed to fetch/i)
    await userEvent.click(confirm)

    expect(bookMock).toHaveBeenCalledTimes(2)
    const [first, second] = bookMock.mock.calls
    expect(second[1].client_id).toBe(first[1].client_id)
    expect(first[1].client_id).toBeTruthy()
    expect(await screen.findByText(/you're booked, ada/i)).toBeInTheDocument()
  })

  it('mints a new client_id when the visitor picks a different slot', async () => {
    // A different slot is a different intent, not a retry of the same one.
    infoMock.mockResolvedValue(INFO)
    bookMock.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    const fill = async () => {
      await userEvent.type(screen.getAllByRole('textbox')[0], 'Ada')
      const email = document.querySelector('input[type="email"]') as HTMLInputElement
      await userEvent.type(email, 'ada@example.com')
      await userEvent.click(screen.getByRole('button', { name: /confirm booking/i }))
      await screen.findByText(/failed to fetch/i)
    }

    await userEvent.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    await fill()
    await userEvent.click(screen.getByRole('button', { name: /change/i }))
    await userEvent.click(document.querySelectorAll('.slot-btn')[1] as HTMLElement)
    await userEvent.click(screen.getByRole('button', { name: /confirm booking/i }))

    const [first, second] = bookMock.mock.calls
    expect(second[1].client_id).not.toBe(first[1].client_id)
  })

  it('keeps the confirm button disabled until name and a plausible email exist', async () => {
    infoMock.mockResolvedValue(INFO)
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')
    await userEvent.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)

    const button = screen.getByRole('button', { name: /confirm booking/i })
    expect(button).toBeDisabled()
    await userEvent.type(screen.getAllByRole('textbox')[0], 'Ada')
    expect(button).toBeDisabled()
    const email = document.querySelector('input[type="email"]') as HTMLInputElement
    await userEvent.type(email, 'not-an-email')
    expect(button).toBeDisabled()
    await userEvent.clear(email)
    await userEvent.type(email, 'ada@example.com')
    expect(button).toBeEnabled()
  })

  it('handles losing the race for a slot: message + fresh slot list', async () => {
    infoMock.mockResolvedValue(INFO)
    bookMock.mockRejectedValue(new Error('slot not available'))
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    await userEvent.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    await userEvent.type(screen.getAllByRole('textbox')[0], 'Ada')
    const email = document.querySelector('input[type="email"]') as HTMLInputElement
    await userEvent.type(email, 'ada@example.com')
    await userEvent.click(screen.getByRole('button', { name: /confirm booking/i }))

    expect(await screen.findByText(/just taken/i)).toBeInTheDocument()
    expect(infoMock).toHaveBeenCalledTimes(2)     // reloaded availability
    expect(document.querySelectorAll('.slot-btn').length).toBeGreaterThan(0)
  })
})

// ── a transient failure is not a dead link ──────────────────────────────────
// The card the visitor used to get on ANY load failure told them the host had
// removed the link and to ask for a fresh one. The backend rate-limits this
// endpoint and counts every request, not just failures, so 121 loads in five
// minutes from one address — a shared office NAT, or one visitor reloading —
// gave everyone behind it a terminal, unrecoverable dead-end.

describe('<BookingPage> load failures', () => {
  it.each([
    ['a rate limit', new HttpError(429, 'too many requests')],
    ['a server error', new HttpError(502, 'bad gateway')],
    ['a dropped connection', new TypeError('Failed to fetch')],
  ])('offers a retry after %s rather than declaring the link dead', async (_l, err) => {
    infoMock.mockRejectedValue(err)
    render(<BookingPage token="tok" />)
    expect(await screen.findByText(/couldn’t load this page just now/i)).toBeInTheDocument()
    expect(screen.queryByText(/no longer available/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('recovers when the retry succeeds', async () => {
    infoMock.mockRejectedValueOnce(new HttpError(429, 'too many requests'))
    infoMock.mockResolvedValue(INFO)
    render(<BookingPage token="tok" />)
    await userEvent.click(await screen.findByRole('button', { name: /try again/i }))
    expect(await screen.findByText('Intro call')).toBeInTheDocument()
  })

  it('does not let a failed refresh bury the lost-the-race message', async () => {
    // submit()'s recovery reloads availability behind the message it just set;
    // a failure there used to replace it with the dead-link card.
    infoMock.mockResolvedValueOnce(INFO).mockRejectedValue(new HttpError(429, 'slow down'))
    bookMock.mockRejectedValue(new Error('slot not available'))
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    await userEvent.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    await userEvent.type(screen.getAllByRole('textbox')[0], 'Ada')
    const email = document.querySelector('input[type="email"]') as HTMLInputElement
    await userEvent.type(email, 'ada@example.com')
    await userEvent.click(screen.getByRole('button', { name: /confirm booking/i }))

    expect(await screen.findByText(/just taken/i)).toBeInTheDocument()
    expect(screen.queryByText(/no longer available/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/couldn’t load this page/i)).not.toBeInTheDocument()
  })
})
