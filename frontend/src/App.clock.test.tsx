// Inside the Android client, an account with no clock shows the phone's
// setting and saves it once. The file is separate because the host env is
// module state per test file, and App.test.tsx must stay a browser.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, HttpError, subscribe } from './api'
import { ANDROID_EVENT, startAndroidHost } from './android'
import { translate } from './i18n/index'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

// Every value App hands the clock's provider, in render order, so a test can
// read the very first frame's. The env listener's first `follow()` runs in an
// effect after mount and would cover a wrong seed before any query could see it.
const provided = vi.hoisted(() => [] as string[])
vi.mock('./timeformat', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./timeformat')>()
  return {
    ...mod,
    TimeFormatProvider: (p: Parameters<typeof mod.TimeFormatProvider>[0]) => {
      provided.push(p.value)
      return mod.TimeFormatProvider(p)
    },
  }
})

vi.mock('./desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./desktop')>()
  return {
    ...mod,
    readState: vi.fn(async () => null),
    floatWindow: vi.fn(async () => null), dockWindow: vi.fn(async () => null),
    pinWindow: vi.fn(async () => null), dragWindow: vi.fn(async () => null),
  }
})

const phone = (env: Record<string, unknown>) =>
  window.dispatchEvent(new CustomEvent(ANDROID_EVENT, {
    detail: { type: 'env', env: { v: 1, ...env } },
  }))
const phoneClock = (clock24: boolean) => act(() => { phone({ clock24 }) })

const deferred = <T,>() => {
  let resolve: (v: T) => void = () => {}
  let reject: (e: unknown) => void = () => {}
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const openSettings = async (section?: string) => {
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  if (section) await userEvent.click(screen.getByRole('tab', { name: section }))
}
const clockRow = () => screen.getByRole('button', { name: '12- or 24-hour clock' })
const clockWrites = () =>
  m.putSettings.mock.calls.map((c) => c[0]).filter((b) => 'time_format' in b)
const emit = () => {
  const calls = vi.mocked(subscribe).mock.calls
  return calls[calls.length - 1][0]
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const refetch = () => act(async () => {
  emit()('settings_updated')
  await new Promise((r) => setTimeout(r, 400))
})

beforeAll(() => {
  vi.stubGlobal('SmylteAndroid', { hello: () => '{"v":1,"clock24":true}' })
  startAndroidHost()
})
afterAll(() => {
  vi.unstubAllGlobals()
})

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  // The phone is on 24-hour unless a test says otherwise. Nothing is mounted
  // yet, so no `act` is needed.
  phone({ clock24: true })
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

describe('<App> in the Android client: the clock', () => {
  it('shows the phone\'s clock before the account has answered', async () => {
    const read = deferred<Record<string, unknown>>()
    m.getSettings.mockReturnValue(read.promise)
    provided.length = 0
    render(<App />)
    // The first frame, from the `useState` seed: no 12-hour flash before the
    // phone's setting arrives.
    expect(provided[0]).toBe('24h')
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('General')
    expect(clockRow()).toHaveTextContent('24-hour')
    expect(clockWrites()).toEqual([])
  })

  it.each([
    [true, '24h', '24-hour'],
    [false, '12h', '12-hour'],
  ])('writes the phone\'s clock to an account that has none, once', async (clock24, saved, label) => {
    phone({ clock24 })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(clockWrites()).toEqual([{ time_format: saved }]))
    await openSettings('General')
    expect(clockRow()).toHaveTextContent(label)

    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    await refetch()
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(2))
    await flush()
    expect(clockWrites()).toHaveLength(1)
  })

  it('leaves an account that has chosen alone, and stops following the phone', async () => {
    m.getSettings.mockResolvedValue({ time_format: '12h' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await waitFor(() => expect(clockRow()).toHaveTextContent('12-hour'))
    await phoneClock(false)
    await phoneClock(true)
    expect(clockRow()).toHaveTextContent('12-hour')
    expect(clockWrites()).toEqual([])
  })

  it('never puts the phone\'s setting over a toggle made while the read was in flight', async () => {
    const read = deferred<Record<string, unknown>>()
    m.getSettings.mockReturnValue(read.promise)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('General')
    expect(clockRow()).toHaveTextContent('24-hour')
    await userEvent.click(clockRow())
    expect(clockRow()).toHaveTextContent('12-hour')
    await waitFor(() => expect(clockWrites()).toEqual([{ time_format: '12h' }]))

    await act(async () => {
      read.resolve({})
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(clockRow()).toHaveTextContent('12-hour')
    expect(clockWrites()).toEqual([{ time_format: '12h' }])

    await phoneClock(true)
    expect(clockRow()).toHaveTextContent('12-hour')
  })

  it('follows the phone until the account answers, then saves what the phone says then', async () => {
    const read = deferred<Record<string, unknown>>()
    m.getSettings.mockReturnValue(read.promise)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('General')
    await phoneClock(false)
    expect(clockRow()).toHaveTextContent('12-hour')
    await phoneClock(true)
    expect(clockRow()).toHaveTextContent('24-hour')
    await phoneClock(false)
    expect(clockRow()).toHaveTextContent('12-hour')

    await act(async () => {
      read.resolve({})
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(clockWrites()).toEqual([{ time_format: '12h' }])
    await phoneClock(true)
    expect(clockRow()).toHaveTextContent('12-hour')
  })

  it('writes nothing when the settings read failed, and goes on following the phone', async () => {
    m.getSettings.mockRejectedValue(new HttpError(502, 'bad gateway'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await flush()
    expect(clockWrites()).toEqual([])
    await openSettings('General')
    expect(clockRow()).toHaveTextContent('24-hour')
    await phoneClock(false)
    expect(clockRow()).toHaveTextContent('12-hour')
  })

  it('neither writes nor warns after an earlier read failed, and writes on the next good one', async () => {
    const a = deferred<Record<string, unknown>>()
    const b = deferred<Record<string, unknown>>()
    m.getSettings
      .mockReturnValueOnce(a.promise)
      .mockReturnValueOnce(b.promise)
      .mockResolvedValue({})
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    await refetch()
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(2))

    await act(async () => {
      a.reject(new HttpError(502, 'x'))
      await new Promise((r) => setTimeout(r, 0))
    })
    // Separate from the rejection: it takes an extra microtask through `.then`
    // before it reaches `.catch`.
    await act(async () => {
      b.resolve({})
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(clockWrites()).toEqual([])
    expect(screen.queryByText(translate('en', 'app.settingsNotLoaded'))).toBeNull()

    await refetch()
    await waitFor(() => expect(clockWrites()).toEqual([{ time_format: '24h' }]))
  })

  it('an older client that does not report the clock changes nothing', async () => {
    phone({})
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await flush()
    expect(clockWrites()).toEqual([])
    await openSettings('General')
    expect(clockRow()).toHaveTextContent('12-hour')
  })

  it('a second account in the same window gets its own answer', async () => {
    m.getSettings.mockResolvedValue({ time_format: '12h' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await waitFor(() => expect(clockRow()).toHaveTextContent('12-hour'))

    await userEvent.click(screen.getByRole('tab', { name: 'Account' }))
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))
    await screen.findByRole('button', { name: /sign in/i })

    m.getSettings.mockResolvedValue({})
    m.login.mockResolvedValue({ authenticated: true, user: 'bob' })
    await userEvent.type(screen.getByLabelText('Username'), 'bob')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(clockWrites()).toEqual([{ time_format: '24h' }]))
    await openSettings('General')
    expect(clockRow()).toHaveTextContent('24-hour')
  })
})
