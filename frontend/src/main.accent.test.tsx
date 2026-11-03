// main.tsx paints this phone's accent from the wallpaper before the first
// render, on the app's own route only (the later paints are App's, and are
// covered by App.accent.test.tsx).
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { RAMP, SURFACES_CSS } from './test/accent'

// What the inline accent was each time the app rendered, so a test can read the
// very first frame's.
const seen = vi.hoisted(() => [] as string[])
vi.mock('./App', () => ({
  App: () => {
    seen.push(document.documentElement.style.getPropertyValue('--accent'))
    return null
  },
}))
vi.mock('./components/BookingPage', () => ({ BookingPage: () => null }))
vi.mock('./components/DisplayView', () => ({ DisplayView: () => null }))
vi.mock('./components/SharePage', () => ({ SharePage: () => null }))
vi.mock('./desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./desktop')>()),
  startCaptionSync: vi.fn(),
}))

const PALETTE = JSON.stringify({ v: 1, clock24: false, accent: RAMP })
const accent = () => document.documentElement.style.getPropertyValue('--accent')

async function load(path: string, hello?: string, on = true) {
  vi.resetModules()
  seen.length = 0
  history.replaceState(null, '', path)
  document.body.innerHTML = '<div id="root"></div>'
  localStorage.setItem('smylte-device-accent', on ? '1' : '0')
  if (hello !== undefined) vi.stubGlobal('SmylteAndroid', { hello: () => hello })
  await import('./main')
}

let sheet: HTMLStyleElement
beforeAll(() => {
  sheet = document.createElement('style')
  sheet.textContent = SURFACES_CSS
  document.head.appendChild(sheet)
})
afterAll(() => sheet.remove())

afterEach(() => {
  vi.unstubAllGlobals()
  document.documentElement.removeAttribute('style')
  delete document.documentElement.dataset.theme
  localStorage.clear()
  document.body.innerHTML = ''
  history.replaceState(null, '', '/')
})

describe('main.tsx: the accent from the wallpaper', () => {
  it('paints the tone before the first render', async () => {
    await load('/', PALETTE)
    expect(accent()).toBe('#005ac1')
    await waitFor(() => expect(seen.length).toBeGreaterThan(0))
    expect(seen[0]).toBe('#005ac1')
  })

  it('in the dark mode\'s tone', async () => {
    document.documentElement.dataset.theme = 'dark'
    await load('/', PALETTE)
    expect(accent()).toBe('#adc6ff')
  })

  it.each([
    ['the switch is off', '/', PALETTE, false],
    ['the booking page', '/book/abc', PALETTE, true],
    ['a display', '/display/abc', PALETTE, true],
    ['a share page', '/share/abc', PALETTE, true],
    ['the phone has no palette', '/', '{"v":1}', true],
    ['there is no bridge', '/', undefined, true],
  ])('paints nothing when %s', async (_name, path, hello, on) => {
    await load(path, hello, on)
    expect(accent()).toBe('')
  })
})
