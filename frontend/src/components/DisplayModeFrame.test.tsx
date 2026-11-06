import { describe, expect, it, vi, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BAR_IDLE_MS, DisplayModeFrame } from './DisplayModeFrame'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  delete (navigator as unknown as Record<string, unknown>).wakeLock
})

const frame = () => (
  <DisplayModeFrame tab="today" onTab={() => {}} onExit={() => {}}>
    <div>content</div>
  </DisplayModeFrame>
)

describe('<DisplayModeFrame>', () => {
  it('keeps the screen awake while it is up, and lets go when it is not', async () => {
    const release = vi.fn(async () => {})
    const request = vi.fn(async () => ({ released: false, release }))
    Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request } })
    const { unmount } = render(frame())
    await act(async () => {})
    expect(request).toHaveBeenCalledWith('screen')
    unmount()
    expect(release).toHaveBeenCalled()
  })

  it('works without the wake lock API', () => {
    render(frame())
    expect(screen.getByText('content')).toBeInTheDocument()
  })

  it('folds its bar away once it is left alone', () => {
    vi.useFakeTimers()
    render(frame())
    fireEvent.click(screen.getByRole('button', { name: 'Display controls' }))
    expect(screen.getByRole('toolbar')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(BAR_IDLE_MS - 1) })
    expect(screen.getByRole('toolbar')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(1) })
    expect(screen.queryByRole('toolbar')).toBeNull()
  })
})
