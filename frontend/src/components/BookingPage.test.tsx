import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BookingPage } from './BookingPage'
import { api, type PublicBookingInfo } from '../api'

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
    infoMock.mockRejectedValue(new Error('unknown booking link'))
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
      start: INFO.slots[0].start, name: 'Ada', email: 'ada@example.com', notes: undefined,
    })
    expect(await screen.findByText(/you're booked, ada/i)).toBeInTheDocument()
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
