// Inside the Android client, Back over Settings asks before it drops text that
// only Enter or a button sends, and the answer is final: "Keep editing" keeps
// Settings open with the text in it. The file is separate because the host is
// module state per test file, and App.test.tsx must stay a browser.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, type List } from './api'
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

const taskList = (id: string, name: string): List => ({
  id, href: `/${id}/`, name, is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
})
const drawer = () => screen.queryByRole('dialog', { name: 'Manage lists' })

/** Open the Tasks tab, and on a phone the Lists drawer from its bar. */
async function openDrawer() {
  render(<App />)
  await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
  await userEvent.click(await screen.findByRole('button', { name: /^Lists/ }))
  await screen.findByRole('dialog', { name: 'Manage lists' })
}

describe('<App> in the Android client: Back over a group rename in the Lists drawer, on a phone', () => {
  beforeEach(() => {
    setBreakpoint(true)
    m.getSettings.mockResolvedValue({
      time_format: '12h', task_groups: [{ id: 'g1', name: 'Focus', lists: ['work'] }],
    })
    m.lists.mockResolvedValue([taskList('work', 'Work')])
  })

  /** Rename "Focus" to "Deep work", without Enter, and press Back. */
  async function renameAndBack() {
    await openDrawer()
    await userEvent.click(screen.getByRole('button', { name: 'Rename group Focus' }))
    const input = document.activeElement as HTMLInputElement
    expect(input.tagName).toBe('INPUT')
    await userEvent.clear(input)
    await userEvent.type(input, 'Deep work')
    back()
    return input
  }

  it('asks, and "Keep editing" keeps the field, focused, with the name in it', async () => {
    const input = await renameAndBack()
    expect(question()).toBeInTheDocument()
    expect(drawer()).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(question()).toBeNull()
    expect(drawer()).toBeInTheDocument()
    expect(document.activeElement).toBe(input)
    expect(input).toHaveValue('Deep work')

    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(m.putSettings).toHaveBeenCalled())
    const sent = m.putSettings.mock.calls.map((c) => c[0] as { task_groups?: { name: string }[] })
    expect(sent.some((s) => s.task_groups?.[0]?.name === 'Deep work')).toBe(true)
  })

  it('closes the drawer on "Discard", and saves nothing', async () => {
    await renameAndBack()
    expect(question()).toBeInTheDocument()
    expect(drawer()).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(drawer()).toBeNull())
    expect(question()).toBeNull()
    const sent = m.putSettings.mock.calls.map((c) => c[0] as object)
    expect(sent.some((s) => 'task_groups' in s)).toBe(false)
  })

  it('closes the drawer without a question when the name was not changed', async () => {
    await openDrawer()
    await userEvent.click(screen.getByRole('button', { name: 'Rename group Focus' }))
    back()
    expect(question()).toBeNull()
    await waitFor(() => expect(drawer()).toBeNull())
  })
})

describe.each([
  ['a wide layout', false],
  ['a phone', true],
])('<App> in the Android client: Tab inside the question, on %s', (_, phone) => {
  beforeEach(() => {
    setBreakpoint(phone)
    m.lists.mockResolvedValue([taskList('work', 'Work')])
  })

  it('stays on the two answers, so Enter cannot add the half-typed task', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Tasks' }))
    await user.click(await screen.findByRole('button', { name: 'New…' }))
    const add = await screen.findByRole('dialog', { name: 'Add task' })
    await user.type(within(add).getByLabelText('Title'), 'Buy mi')
    back()
    expect(question()).toBeInTheDocument()

    for (const shift of [true, true, true, false]) {
      await user.tab({ shift })
      expect(question()!.contains(document.activeElement)).toBe(true)
    }

    act(() => { screen.getByRole('button', { name: 'Keep editing' }).focus() })
    await user.tab({ shift: true })
    await user.tab({ shift: true })
    await user.keyboard('{Enter}')

    expect(m.createTask).not.toHaveBeenCalled()
    expect(question()).toBeNull()
    const still = screen.getByRole('dialog', { name: 'Add task' })
    expect(within(still).getByLabelText('Title')).toHaveValue('Buy mi')
  })
})

describe('<App> in the Android client: Back while a new list is being created, on a phone', () => {
  beforeEach(() => {
    setBreakpoint(true)
    m.lists.mockResolvedValue([taskList('work', 'Work')])
  })

  /** Click Tasks, then the bar's "New list", and send a name that is held. */
  async function createHeld() {
    let resolve!: (l: List) => void
    m.createList.mockReturnValue(new Promise<List>((r) => { resolve = r }))
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    await userEvent.click(await screen.findByRole('button', { name: 'New list' }))
    await screen.findByRole('dialog', { name: 'Manage lists' })
    await userEvent.type(within(drawer()!).getByRole('textbox'), 'Groceries{Enter}')
    expect(m.createList).toHaveBeenCalled()
    return resolve
  }

  it('closes the drawer without a question, and the list still arrives', async () => {
    const resolve = await createHeld()
    back()
    expect(question()).toBeNull()
    expect(drawer()).toBeNull()

    await act(async () => { resolve(taskList('groc', 'Groceries')) })
    await userEvent.click(await screen.findByRole('button', { name: /^Lists/ }))
    const open = await screen.findByRole('dialog', { name: 'Manage lists' })
    expect(await within(open).findByText('Groceries')).toBeInTheDocument()
  })

  it('does not let the late reply close the add form opened since', async () => {
    const resolve = await createHeld()
    await userEvent.click(within(drawer()!).getByRole('button', { name: 'Close' }))
    expect(drawer()).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'New list' }))
    const open = await screen.findByRole('dialog', { name: 'Manage lists' })
    const hardware = within(open).getByRole('textbox')
    await userEvent.type(hardware, 'Hardware')

    await act(async () => { resolve(taskList('groc', 'Groceries')) })
    expect(hardware.isConnected).toBe(true)
    expect(hardware).toHaveValue('Hardware')
  })

  // "Being sent" belongs to the form that sent. A form opened after the drawer
  // closed mid-create holds new text, and Back has to ask about it.
  it.each([
    ['Back', () => back()],
    ['its ✕', () => userEvent.click(within(drawer()!).getByRole('button', { name: 'Close' }))],
  ] as const)('asks about a form opened after %s closed the drawer mid-create', async (_, close) => {
    await createHeld()
    await close()
    expect(drawer()).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'New list' }))
    const open = await screen.findByRole('dialog', { name: 'Manage lists' })
    const hardware = within(open).getByRole('textbox')
    await userEvent.type(hardware, 'Hardware')
    back()
    expect(question()).toBeInTheDocument()
    expect(drawer()).toBeInTheDocument()
    expect(hardware).toHaveValue('Hardware')
  })
})

describe.each([
  ['a wide layout', false],
  ['a phone', true],
])('<App> in the Android client: Back while a booking link is saving, on %s', (_, phone) => {
  beforeEach(() => setBreakpoint(phone))

  it('keeps the editor and its title through a failed save', async () => {
    let reject!: (e: Error) => void
    m.calendars.mockResolvedValue([{ ...taskList('cal', 'Personal'), is_task_list: false, is_calendar: true }])
    m.createSchedulingLink.mockReturnValue(new Promise((_r, rj) => { reject = rj }))
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Scheduling' }))
    await userEvent.click(await screen.findByRole('button', { name: 'New link' }))
    const editor = () => screen.queryByRole('dialog', { name: 'New booking link' })
    await userEvent.type(within(editor()!).getByPlaceholderText('30-minute intro call'), 'Coffee')
    await userEvent.click(within(editor()!).getByRole('button', { name: 'Create link' }))
    expect(m.createSchedulingLink).toHaveBeenCalled()

    back()
    expect(question()).toBeNull()
    expect(editor()).toBeInTheDocument()

    await act(async () => { reject(new Error('502 Bad Gateway')) })
    expect(editor()).toBeInTheDocument()
    expect(within(editor()!).getByPlaceholderText('30-minute intro call')).toHaveValue('Coffee')
    await waitFor(() =>
      expect(within(editor()!).getByRole('button', { name: 'Create link' })).toBeEnabled())

    back()
    expect(question()).toBeInTheDocument()
  })
})

describe('<App> in the Android client: crossing the phone breakpoint with the question open', () => {
  it('keeps the field and drops the question when a wide layout turns into a phone', async () => {
    setBreakpoint(false)
    const name = await typeDisplayName()
    back()
    expect(question()).toBeInTheDocument()

    act(() => setBreakpoint(true))
    expect(name.isConnected).toBe(true)
    expect(name).toHaveValue('Hallway')
    expect(question()).toBeNull()
  })

  it('keeps the field and the question when a phone turns wide, and Discard closes Settings', async () => {
    setBreakpoint(true)
    const name = await typeDisplayName()
    back()
    back()
    expect(question()).toBeInTheDocument()

    act(() => setBreakpoint(false))
    expect(name.isConnected).toBe(true)
    expect(name).toHaveValue('Hallway')
    expect(question()).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(settings()).toBeNull())
  })
})

describe.each([
  ['a wide layout', false],
  ['a phone', true],
])('<App> in the Android client: Back over the Appearance panel, on %s', (_, phone) => {
  beforeEach(() => setBreakpoint(phone))

  const appearance = () => screen.queryByRole('dialog', { name: 'Appearance' })

  /** Open the panel and leave a colour half typed. */
  async function halfTyped() {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(within(settings()!).getByRole('tab', { name: 'Appearance' }))
    await userEvent.click(within(settings()!).getByRole('button', { name: 'Customize appearance' }))
    await screen.findByRole('dialog', { name: 'Appearance' })
    const accent = screen.getByLabelText('Accent', { selector: 'input.appear-text' })
    await userEvent.clear(accent)
    await userEvent.type(accent, 'oklch(0.55 0.2')
    return accent
  }

  it('asks, and "Keep editing" keeps the text, focused', async () => {
    const accent = await halfTyped()
    back()
    expect(question()).toBeInTheDocument()
    expect(appearance()).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(question()).toBeNull()
    expect(appearance()).toBeInTheDocument()
    expect(accent).toHaveValue('oklch(0.55 0.2')
    expect(document.activeElement).toBe(accent)
  })

  it('closes the panel on "Discard"', async () => {
    await halfTyped()
    back()
    expect(question()).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(appearance()).toBeNull())
  })

  it('closes an untouched panel without a question', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(within(settings()!).getByRole('tab', { name: 'Appearance' }))
    await userEvent.click(within(settings()!).getByRole('button', { name: 'Customize appearance' }))
    await screen.findByRole('dialog', { name: 'Appearance' })
    back()
    expect(question()).toBeNull()
    await waitFor(() => expect(appearance()).toBeNull())
  })

  it('still closes on Escape with the text half typed, as a browser does', async () => {
    await halfTyped()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(question()).toBeNull()
    await waitFor(() => expect(appearance()).toBeNull())
  })
})

describe.each([
  ['a wide layout', false, 1],
  ['a phone', true, 2],
])('<App> in the Android client: Back while a display is being added, on %s', (_, phone, presses) => {
  beforeEach(() => setBreakpoint(phone))

  it('keeps Settings and the name through a failed add', async () => {
    let reject!: (e: Error) => void
    m.createDisplay.mockReturnValue(new Promise((_r, rj) => { reject = rj }))
    const name = await typeDisplayName()
    await userEvent.click(within(settings()!).getByRole('button', { name: 'Add' }))
    expect(m.createDisplay).toHaveBeenCalled()

    for (let i = 0; i < presses; i++) back()
    expect(settings()).toBeInTheDocument()
    expect(question()).toBeNull()

    await act(async () => { reject(new Error('offline')) })
    expect(name).toHaveValue('Hallway')

    back()
    expect(question()).toBeInTheDocument()
  })
})

describe('<App> in the Android client: the tap shield after "Keep editing", on a wide layout', () => {
  beforeEach(() => setBreakpoint(false))

  it('takes a second press without closing Settings, then goes', async () => {
    await typeDisplayName()
    back()
    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }))

    const shield = document.querySelector('.discard-shield')
    expect(shield).not.toBeNull()
    expect(shield).toHaveAttribute('aria-hidden', 'true')

    fireEvent.mouseDown(shield!)
    expect(settings()).not.toBeNull()

    await waitFor(() => expect(document.querySelector('.discard-shield')).toBeNull(),
      { timeout: 1500 })
  })
})
