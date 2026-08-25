import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BookingPage } from './BookingPage'
import { api, AuthError, HttpError, type PublicBookingInfo } from '../api'

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

  it('names the zone when the fall-back hour repeats', async () => {
    // generate_slots deliberately offers BOTH passes of the repeated hour on
    // the fall-back day. The suite runs in America/New_York, where 2026-11-01
    // 01:00 happens twice: 05:00Z (EDT) and 06:00Z (EST). Both printed
    // "1:00 AM", on the buttons and everywhere downstream, so the visitor had
    // no way to tell which hour they were booking.
    infoMock.mockResolvedValue({
      ...INFO,
      slots: [
        { start: '2026-11-01T05:00:00+00:00', end: '2026-11-01T05:30:00+00:00' },
        { start: '2026-11-01T06:00:00+00:00', end: '2026-11-01T06:30:00+00:00' },
        { start: '2026-11-01T15:00:00+00:00', end: '2026-11-01T15:30:00+00:00' },
      ],
    })
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    const labels = [...document.querySelectorAll('.slot-btn')].map((b) => b.textContent)
    expect(new Set(labels).size).toBe(labels.length)
    expect(labels[0]).toMatch(/EDT/)
    expect(labels[1]).toMatch(/EST/)
    // The unambiguous slot is left alone — no zone suffix on every button.
    expect(labels[2]).not.toMatch(/E[DS]T/)
  })

  it('carries the disambiguated label through to the confirmation card', async () => {
    infoMock.mockResolvedValue({
      ...INFO,
      slots: [
        { start: '2026-11-01T05:00:00+00:00', end: '2026-11-01T05:30:00+00:00' },
        { start: '2026-11-01T06:00:00+00:00', end: '2026-11-01T06:30:00+00:00' },
      ],
    })
    bookMock.mockResolvedValue({
      id: 'b1', start: '2026-11-01T05:00:00+00:00', end: '2026-11-01T05:30:00+00:00',
      title: 'Intro call', duration_minutes: 30, timezone: 'UTC',
    })
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    await userEvent.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    // The confirm bar says it too, not just the button that opened it.
    expect(document.querySelector('.booking-picked')!.textContent).toMatch(/EDT/)

    await userEvent.type(screen.getAllByRole('textbox')[0], 'Ada')
    const email = document.querySelector('input[type="email"]') as HTMLInputElement
    await userEvent.type(email, 'ada@example.com')
    await userEvent.click(screen.getByRole('button', { name: /confirm booking/i }))

    expect(await screen.findByText(/you're booked, ada/i)).toBeInTheDocument()
    expect(document.querySelector('.booking-lead')!.textContent).toMatch(/EDT/)
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


describe('the public page never renders as a blank document', () => {
  it('says it is loading instead of returning null', async () => {
    // main.tsx mounts this directly with no shell or spinner, so returning null
    // was a blank white page for the whole round trip — and that round trip runs
    // slot generation and busy expansion inside the global service lock, so it
    // is seconds on a loaded server, not milliseconds.
    let settle: (v: PublicBookingInfo) => void = () => {}
    infoMock.mockReturnValue(new Promise<PublicBookingInfo>((r) => { settle = r }))
    render(<BookingPage token="tok" />)
    expect(await screen.findByRole('status')).toHaveTextContent(/loading/i)
    settle(INFO)
    expect(await screen.findByText('Intro call')).toBeInTheDocument()
  })

  it('shows the unavailable card on a 401 rather than staying blank forever', async () => {
    // This endpoint needs no session, so a 401 means something in FRONT of it
    // wants one — an Access policy or proxy auth layer that swept /api/public/*
    // in with the rest. The AuthError branch returned without touching `phase`,
    // pinning the page on 'loading' permanently.
    infoMock.mockRejectedValue(new AuthError('unauthenticated'))
    render(<BookingPage token="tok" />)
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
    expect(screen.getByText(/Couldn.t load this page just now/i)).toBeInTheDocument()
    // ...and "Try again" now shows the loading card rather than the blank page
    // that used to replace a readable error.
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})
