// Settings → Developer. The value of this section is entirely in what it
// REQUESTS — it draws nothing itself — so that is what is asserted: the right
// panel sizes, the current controls, and a URL that is the authed preview
// rather than a token one.

import { describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DeveloperSection } from './DeveloperSection'

const shots = () =>
  [...document.querySelectorAll<HTMLImageElement>('.dev-panel__shot')]

const paramsOf = (img: HTMLImageElement) =>
  new URLSearchParams(img.getAttribute('src')!.split('?')[1])

describe('<DeveloperSection>', () => {
  it('previews through the authed route, never a display token', async () => {
    // The reason the section exists. A preview built on `/api/public/display/`
    // would need a live token per size — a credential reaching this calendar
    // with no session — and someone to remember to revoke them.
    render(<DeveloperSection />)
    const all = shots()
    expect(all.length).toBeGreaterThan(6)
    for (const img of all) {
      expect(img.getAttribute('src')).toMatch(/^\/api\/displays\/preview\.png\?/)
      expect(img.getAttribute('src')).not.toContain('/public/')
    }
    cleanup()
  })

  it('asks for each panel at its own pixels, not at one size scaled', async () => {
    render(<DeveloperSection />)
    const sizes = shots().map((i) => {
      const q = paramsOf(i)
      return `${q.get('w')}x${q.get('h')}`
    })
    // The interesting ones are the ends of the range: a badge that cannot hold
    // a month at all, and a panel where the type stops being the constraint.
    expect(sizes).toContain('296x128')
    expect(sizes).toContain('800x480')      // the 7.5" the firmware drives
    expect(sizes).toContain('1872x1404')
    expect(new Set(sizes).size).toBe(sizes.length)   // no size asked for twice
    cleanup()
  })

  it('carries the controls into every request', async () => {
    render(<DeveloperSection />)
    expect(paramsOf(shots()[0]).get('mode')).toBe('calendar')

    await userEvent.click(screen.getByRole('button', { name: /the month/i }))
    for (const img of shots()) expect(paramsOf(img).get('mode')).toBe('habits')

    // Three modes, cycled by one control, so the preview grid reaches all of
    // them — a mode nobody can select here ships with no panel-size coverage.
    await userEvent.click(screen.getByRole('button', { name: /habits \+ today/i }))
    for (const img of shots()) expect(paramsOf(img).get('mode')).toBe('now')
    await userEvent.click(screen.getByRole('button', { name: /now \+ next/i }))
    for (const img of shots()) expect(paramsOf(img).get('mode')).toBe('calendar')

    await userEvent.click(screen.getByRole('button', { name: /e-ink/i }))
    for (const img of shots()) expect(paramsOf(img).get('palette')).toBe('color')

    await userEvent.click(screen.getByRole('button', { name: '0°' }))
    for (const img of shots()) expect(paramsOf(img).get('rotate')).toBe('90')
    cleanup()
  })

  it('redraws on demand, because an unchanged URL is served from memory', async () => {
    render(<DeveloperSection />)
    const before = shots()[0].getAttribute('src')
    await userEvent.click(screen.getByRole('button', { name: /redraw/i }))
    expect(shots()[0].getAttribute('src')).not.toBe(before)
    cleanup()
  })

  it('names the framebuffer an e-ink panel would have to allocate', async () => {
    // Not obvious from the pixels, and the whole reason `.bin` exists:
    // 1872×1404 is 329 KB, which is most of a Pico 2's RAM.
    render(<DeveloperSection />)
    expect(screen.getByText('329 KB')).toBeInTheDocument()
    // 800×480 and 480×800 are the same 48,000 bytes, which is the point: the
    // buffer is the panel's pixels, not its shape.
    expect(screen.getAllByText('48 KB')).toHaveLength(2)
    expect(screen.getByText('5 KB')).toBeInTheDocument()      // 296×128
    cleanup()
  })

  it('gives every preview an alt text that says which panel it is', async () => {
    render(<DeveloperSection />)
    for (const img of shots()) {
      expect(img.getAttribute('alt')).toBeTruthy()
      expect(img.getAttribute('alt')).toMatch(/\d+ by \d+ pixels/)
    }
    cleanup()
  })
})
