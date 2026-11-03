// The Android client's splash signal (markReady), in real browser engines.
//
// While the client holds its splash screen the window does not draw, so the
// page may get no animation frames. What jsdom cannot say is that React's real
// scheduler in a real engine still runs App's effect, and so still says ready.
// Production-shaped mount (`createRoot` + `StrictMode`, as main.tsx does), with
// requestAnimationFrame stopped, in Chromium AND WebKit.
import { StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api } from './api'
import { startAndroidHost } from './android'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

vi.mock('./desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./desktop')>()
  return {
    ...mod,
    readState: vi.fn(async () => null),
    floatWindow: vi.fn(async () => null), dockWindow: vi.fn(async () => null),
    pinWindow: vi.fn(async () => null), dragWindow: vi.fn(async () => null),
  }
})

const ready = vi.fn()

beforeAll(() => {
  vi.stubGlobal('SmylteAndroid', { hello: () => '{"v":1,"clock24":false}', ready })
  startAndroidHost()
})
afterAll(() => { vi.unstubAllGlobals() })

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.getSettings.mockResolvedValue({ time_format: '12h' })
  m.putSettings.mockResolvedValue({})
  m.login.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

let root: Root | null = null
let host: HTMLElement | null = null
const originalFrame = window.requestAnimationFrame
afterEach(() => {
  root?.unmount(); host?.remove(); root = null; host = null
  window.requestAnimationFrame = originalFrame
  ready.mockClear()
})

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function until(what: string, ok: () => boolean) {
  for (let i = 0; i < 200 && !ok(); i++) await sleep(10)
  expect(ok(), what).toBe(true)
}

function mount(children: React.ReactNode) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(<StrictMode>{children}</StrictMode>)
}

describe('the splash signal in a real engine', () => {
  it('says ready once the sign-in check answers, with no frames', async () => {
    window.requestAnimationFrame = () => 0
    let answer: (v: { authenticated: boolean; user: string }) => void = () => {}
    m.me.mockReturnValue(new Promise((res) => { answer = res }))
    mount(<App />)
    await until('the shell paints', () => !!document.querySelector('.shell'))
    await sleep(50)
    expect(ready).not.toHaveBeenCalled()
    answer({ authenticated: true, user: 'alice' })
    await until('ready is said', () => ready.mock.calls.length > 0)
    await sleep(50)
    expect(ready).toHaveBeenCalledTimes(1)
  })
})
