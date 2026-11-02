// A sidebar fold that arrives from another device (settings_updated) must not
// close the list editor that is open, nor drop the rename in it, nor the
// "Discard changes?" question over it. Sidebar draws the editor in one place in
// the tree whichever way the sidebar is drawn. The file is separate because the
// host is module state per test file, and App.test.tsx must stay a browser.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, subscribe, type List } from './api'
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

const work: List = {
  id: 'w', href: '/u/w/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
}

/** The SSE callback App hands to `subscribe`. */
let emit: (type: string) => void

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  vi.mocked(subscribe).mockImplementation((cb) => { emit = cb; return () => {} })
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.putSettings.mockResolvedValue({})
  m.lists.mockResolvedValue([work])
  m.updateList.mockResolvedValue({ ...work, name: 'Work stuff' })
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
const editor = () => screen.queryByRole('dialog', { name: 'List' })
const question = () => screen.queryByRole('alertdialog', { name: 'Discard changes?' })

describe.each(['classic', 'sidebar'] as const)(
  '<App> a sidebar fold from another device, in the %s layout',
  (layout) => {
    const account = { time_format: '12h', layout } as const

    beforeEach(() => {
      setBreakpoint(false)
      m.getSettings.mockResolvedValue(account)
    })

    /** Open Tasks and the editor of "Work", and rename it. */
    async function rename() {
      render(<App />)
      // The account's layout is applied by the first settings read, which
      // swaps the frame; open Tasks only once it has.
      await waitFor(() => expect(document.querySelector('.shell')).toHaveAttribute('data-layout', layout))
      await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
      await userEvent.click(await screen.findByRole('button', { name: 'Edit Work' }))
      const name = within(editor()!).getByDisplayValue('Work')
      await userEvent.clear(name)
      await userEvent.type(name, 'Work stuff')
      expect(name).toHaveValue('Work stuff')
    }

    /** The owner folds the sidebar on another device. */
    async function fold() {
      m.getSettings.mockResolvedValue({ ...account, sidebar_collapsed: true })
      act(() => emit('settings_updated'))
      await waitFor(() => expect(document.querySelector('.side.collapsed')).toBeInTheDocument(),
        { timeout: 3000 })
    }

    it('keeps the editor, the rename and the question, and still saves it', async () => {
      await rename()
      back()
      expect(question()).toBeInTheDocument()

      await fold()
      expect(editor()).toBeInTheDocument()
      expect(within(editor()!).getByDisplayValue('Work stuff')).toBeInTheDocument()
      expect(question()).toBeInTheDocument()

      await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
      expect(question()).toBeNull()
      await userEvent.click(within(editor()!).getByRole('button', { name: 'Save' }))
      expect(m.updateList).toHaveBeenCalledWith('w', expect.objectContaining({ name: 'Work stuff' }))
    })

    it('keeps the editor and the rename when nothing was asked', async () => {
      await rename()

      await fold()
      expect(editor()).toBeInTheDocument()
      expect(within(editor()!).getByDisplayValue('Work stuff')).toBeInTheDocument()
      expect(question()).toBeNull()
    })
  },
)
