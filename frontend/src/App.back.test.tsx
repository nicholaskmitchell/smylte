// Inside the Android client, Back over Settings asks before it drops text that
// only Enter or a button sends, and the answer is final: "Keep editing" keeps
// Settings open with the text in it. The file is separate because the host is
// module state per test file, and App.test.tsx must stay a browser.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api } from './api'
import { ANDROID_EVENT, startAndroidHost } from './android'
import { setBreakpoint } from './test/setup'

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

beforeAll(() => {
  vi.stubGlobal('SmylteAndroid', { hello: () => '{"v":1,"clock24":false}', layers: () => {} })
  startAndroidHost()
})
afterAll(() => {
  vi.unstubAllGlobals()
})

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  // The account has its own clock, so nothing is written at startup.
  m.getSettings.mockResolvedValue({ time_format: '12h' })
  m.putSettings.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.displays.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

/** Android's Back, as the host delivers it to the page. */
const back = () => act(() => {
  window.dispatchEvent(new CustomEvent(ANDROID_EVENT, { detail: { type: 'back' } }))
})
const settings = () => screen.queryByRole('dialog', { name: 'Settings' })
const question = () => screen.queryByRole('alertdialog', { name: 'Discard changes?' })

/** Open Settings on Displays and type a name that has not been added. */
async function typeDisplayName() {
  render(<App />)
  await screen.findByRole('button', { name: 'Tasks' })
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  await userEvent.click(within(settings()!).getByRole('tab', { name: 'Displays' }))
  const name = await within(settings()!).findByLabelText('Name')
  await userEvent.type(name, 'Hallway')
  return name
}

describe.each([
  ['a wide layout', false, 1],
  // The first Back on a phone steps from the section to the index, which
  // keeps the section, and the name, mounted underneath.
  ['a phone', true, 2],
])('<App> in the Android client: Back over Settings, on %s', (_, phone, presses) => {
  beforeEach(() => setBreakpoint(phone))

  it('keeps Settings open, with the text in it, on "Keep editing"', async () => {
    const name = await typeDisplayName()
    for (let i = 0; i < presses; i++) back()
    expect(question()).toBeInTheDocument()

    // The press lands outside the menu. It must not count as a tap outside.
    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(question()).toBeNull()
    expect(settings()).toBeInTheDocument()
    expect(name).toHaveValue('Hallway')
  })

  it('keeps Settings open on a tap on the question\'s scrim', async () => {
    const name = await typeDisplayName()
    for (let i = 0; i < presses; i++) back()
    await userEvent.click(document.querySelector('.discard-overlay')!)
    expect(question()).toBeNull()
    expect(settings()).toBeInTheDocument()
    expect(name).toHaveValue('Hallway')
  })

  it('closes Settings on "Discard", and adds nothing', async () => {
    await typeDisplayName()
    for (let i = 0; i < presses; i++) back()
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(settings()).toBeNull())
    expect(question()).toBeNull()
    expect(m.createDisplay).not.toHaveBeenCalled()
  })
})

describe('<App> in the Android client: a tap outside Settings', () => {
  it('still closes it when nothing is being asked', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    expect(settings()).toBeInTheDocument()
    await userEvent.click(document.body)
    expect(settings()).toBeNull()
  })
})
