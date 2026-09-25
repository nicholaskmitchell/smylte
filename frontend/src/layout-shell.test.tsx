// The app's two frames, rendered through <App>. What each frame IS — the
// sidebar's CSS, and Classic being the pixels it always was — is measured in a
// real browser (sidebar-layout.browser.test.tsx) and by the screenshot
// comparison the layout commit describes; this file pins the part jsdom can see: which tree
// mounts, where the collections go, which setting is written, and what the
// first paint draws before the account has answered.
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, subscribe, HttpError, type List } from './api'
import { LAYOUT_KEY, SIDEBAR_COLLAPSED_KEY } from './layout'
import { setBreakpoint } from './test/setup'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
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

const m = vi.mocked(api)

const list = (id: string, name: string): List => ({
  id, href: `/u/${id}/`, name, is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#5E7D4A',
})
const calendar = (id: string, name: string): List => ({
  ...list(id, name), is_task_list: false, is_calendar: true,
})

const shell = () => document.querySelector('.shell')!
const views = () => screen.queryByRole('navigation', { name: 'Views' })

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

describe('the sidebar layout', () => {
  it('is what an account that never chose gets', async () => {
    render(<App />)
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    expect(shell().getAttribute('data-layout')).toBe('sidebar')
    const nav = views()!
    expect(nav).toHaveClass('appnav')
    // The strip's own buttons, with the strip's semantics: page navigation
    // with `aria-current`, not a tablist (Settings' nav is the tablist).
    for (const name of ['Today', 'Home', 'Tasks', 'Calendar', 'Scheduling']) {
      expect(within(nav).getByRole('button', { name })).toBeInTheDocument()
    }
    expect(within(nav).getByRole('button', { name: 'Home' })).toHaveAttribute('aria-current', 'page')
    expect(document.querySelector('.topbar')).toBeNull()
  })

  it('lends the Tasks lists to the sidebar, and takes them back on another view', async () => {
    m.lists.mockResolvedValue([list('l1', 'Errands'), list('l2', 'Work')])
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    const slot = document.querySelector('.appnav-slot')!
    await waitFor(() => expect(within(slot as HTMLElement).getByText('Errands')).toBeInTheDocument())
    // Inside the app sidebar, not beside the pane: the view draws no sidebar
    // of its own, so the pane is the whole of `.work`.
    expect(document.querySelector('.work > .side')).toBeNull()
    // And the app owns the fold: the lists' own « is not drawn twice.
    expect(within(slot as HTMLElement).queryByRole('button', { name: 'Collapse sidebar' })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Home' }))
    await waitFor(() => expect(slot.childElementCount).toBe(0))
  })

  it('puts the quick add at the foot of the list, after the rows it adds to', async () => {
    m.lists.mockResolvedValue([list('l1', 'Errands')])
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    const foot = await waitFor(() => {
      const el = document.querySelector('.composer-foot > .quickadd')
      expect(el).not.toBeNull()
      return el!
    })
    // DOM order is the order on screen: the scroller first, then the composer.
    const scroll = document.querySelector('.content[data-pane="list"] > .scroll')!
    expect(scroll.compareDocumentPosition(foot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(document.querySelector('.content > .quickadd')).toBeNull()
  })

  it('folds to a rail through the one flag both frames share', async () => {
    render(<App />)
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await userEvent.click(within(views()!).getByRole('button', { name: 'Collapse sidebar' }))
    expect(m.putSettings).toHaveBeenCalledWith({ sidebar_collapsed: true })
    const nav = views()!
    expect(nav).toHaveClass('collapsed')
    // The rail holds no views; one press brings them back.
    expect(within(nav).queryByRole('button', { name: 'Tasks' })).toBeNull()
    await userEvent.click(within(nav).getByRole('button', { name: 'Expand sidebar' }))
    expect(within(views()!).getByRole('button', { name: 'Tasks' })).toBeInTheDocument()
  })

  it('says where the tab order shows', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
    expect(await screen.findByText(/order down the sidebar/)).toBeInTheDocument()
  })

  it('on a phone, puts the views in a bar along the bottom with the gear', async () => {
    setBreakpoint(true)
    render(<App />)
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    const bar = views()!
    expect(bar).toHaveClass('tabbar')
    expect(document.querySelector('.appnav')).toBeNull()
    for (const name of ['Today', 'Home', 'Tasks', 'Calendar', 'Scheduling', 'Settings']) {
      expect(within(bar).getByRole('button', { name })).toBeInTheDocument()
    }
    // The bar comes after the view, so it is drawn under it.
    const main = document.querySelector('.frame-main')!
    expect(main.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('on a phone, keeps the lists in the view, where the drawer opens from', async () => {
    setBreakpoint(true)
    m.lists.mockResolvedValue([list('l1', 'Errands')])
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    await waitFor(() => expect(document.querySelector('.work .side-mobilebar')).not.toBeNull())
  })
})

describe('the sidebar layout, further', () => {
  it('lends the Calendar its calendars and task lists the same way', async () => {
    m.calendars.mockResolvedValue([calendar('c1', 'Family'), calendar('c2', 'Work')])
    m.lists.mockResolvedValue([list('l1', 'Errands')])
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Calendar' }))
    const slot = document.querySelector('.appnav-slot') as HTMLElement
    await waitFor(() => expect(within(slot).getByText('Family')).toBeInTheDocument())
    expect(within(slot).getByText('Work')).toBeInTheDocument()
    // The calendar's own Tasks section comes along (Sidebar's `extra`).
    await waitFor(() => expect(slot.querySelector('.cal-tasks')).not.toBeNull())
    expect(document.querySelector('.work > .side')).toBeNull()
  })

  it('folds to a rail that keeps the open view\'s collection dots', async () => {
    m.lists.mockResolvedValue([list('l1', 'Errands'), list('l2', 'Work')])
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    await userEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(document.querySelector('.frame')).toHaveAttribute('data-nav', 'folded')
    const slot = document.querySelector('.appnav-slot')!
    await waitFor(() => expect(slot.querySelectorAll('.side.collapsed .rail-dot')).toHaveLength(2))
    // One unfold, the app's: Sidebar draws none of its own inside the rail.
    expect(slot.querySelector('.side-toggle')).toBeNull()
    expect(screen.getAllByRole('button', { name: 'Expand sidebar' })).toHaveLength(1)
  })

  it('paints folded from the boot cache before the account has answered', async () => {
    // Under this layout the fold is the width of the whole frame, so an
    // uncached `false` would paint the full column and then fold it 184px.
    localStorage.setItem(LAYOUT_KEY, 'sidebar')
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, '1')
    m.getSettings.mockReturnValue(new Promise(() => {}))
    render(<App />)
    expect(views()).toHaveClass('collapsed')
    expect(document.querySelector('.frame')).toHaveAttribute('data-nav', 'folded')
  })

  it('caches the fold when it changes, and when the account says', async () => {
    m.getSettings.mockResolvedValue({ sidebar_collapsed: true })
    render(<App />)
    await waitFor(() => expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('1'))
    await userEvent.click(within(views()!).getByRole('button', { name: 'Expand sidebar' }))
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('0')
  })

  it('draws the settings menu beside the nav, not inside its landmark', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
    const menu = document.querySelector('.settings-menu')!
    expect(menu).not.toBeNull()
    expect(views()!.contains(menu), 'the menu is part of the Views landmark').toBe(false)
    expect(menu.parentElement).toBe(document.querySelector('.frame'))
  })

  it('keeps settings where they were when the window crosses to a phone', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Calendar' }))
    act(() => setBreakpoint(true))
    expect(views()).toHaveClass('tabbar')
    // The same menu, now a sheet, still on the section that was open.
    await waitFor(() => expect(document.querySelector('.set-sheet')).not.toBeNull())
    expect(document.querySelector('.set-sheet')).toHaveAttribute('data-view', 'panel')
    expect(screen.getByRole('tab', { name: 'Calendar' })).toHaveAttribute('aria-selected', 'true')
  })

  it('draws the offline bar in the view\'s column', async () => {
    m.me.mockRejectedValue(new HttpError(502, 'bad gateway'))
    localStorage.setItem(LAYOUT_KEY, 'sidebar')
    render(<App />)
    const bar = await screen.findByRole('status')
    expect(bar).toHaveClass('offline-bar')
    expect(bar.parentElement).toBe(document.querySelector('.frame-main'))
  })
})

describe('Classic', () => {
  it('is drawn when the account chose it, and remembered for the next boot', async () => {
    m.getSettings.mockResolvedValue({ layout: 'classic' })
    render(<App />)
    await waitFor(() => expect(document.querySelector('.topbar')).not.toBeNull())
    expect(shell().getAttribute('data-layout')).toBe('classic')
    expect(views()).toBeNull()
    expect(document.querySelectorAll('.topbar .tabs .tab')).toHaveLength(5)
    expect(localStorage.getItem(LAYOUT_KEY)).toBe('classic')
  })

  it('keeps each view its own sidebar and the quick add under the header', async () => {
    m.getSettings.mockResolvedValue({ layout: 'classic' })
    m.lists.mockResolvedValue([list('l1', 'Errands')])
    render(<App />)
    await waitFor(() => expect(document.querySelector('.topbar')).not.toBeNull())
    await userEvent.click(screen.getByRole('button', { name: 'Tasks' }))
    await waitFor(() => expect(document.querySelector('.work > .side')).not.toBeNull())
    await waitFor(() => expect(document.querySelector('.content > .quickadd')).not.toBeNull())
    expect(document.querySelector('.composer-foot')).toBeNull()
    expect(document.querySelector('.appnav-slot')).toBeNull()
  })

  it('paints from the boot cache before the account has answered', async () => {
    // The frame decides which tree mounts, so the first paint has to be the
    // right one — a swap when the settings read lands would rebuild the
    // whole screen under the pointer.
    localStorage.setItem(LAYOUT_KEY, 'classic')
    m.getSettings.mockReturnValue(new Promise(() => {}))
    render(<App />)
    expect(document.querySelector('.topbar')).not.toBeNull()
    expect(views()).toBeNull()
  })

  it('does not outlive an account that never chose it', async () => {
    // The cache is per browser. A blob with no `layout` is the default frame,
    // not "keep whatever the last account here had".
    localStorage.setItem(LAYOUT_KEY, 'classic')
    render(<App />)
    await waitFor(() => expect(views()).not.toBeNull())
    expect(localStorage.getItem(LAYOUT_KEY)).toBe('sidebar')
  })

  it('ignores a frame it does not know', async () => {
    m.getSettings.mockResolvedValue({ layout: 'masthead' as never })
    render(<App />)
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await waitFor(() => expect(shell().getAttribute('data-layout')).toBe('sidebar'))
  })
})

describe('switching', () => {
  it('writes the frame, swaps it, and keeps settings open where the switch was made', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Appearance' }))
    const row = screen.getByRole('button', { name: 'Sidebar or classic layout' })
    expect(row).toHaveTextContent('Sidebar')
    await userEvent.click(row)

    expect(m.putSettings).toHaveBeenCalledWith({ layout: 'classic' })
    // Focus follows the switch to the new frame's Layout row, rather than
    // falling to <body> with the button that had it.
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Sidebar or classic layout' }))
    expect(localStorage.getItem(LAYOUT_KEY)).toBe('classic')
    expect(document.querySelector('.topbar')).not.toBeNull()
    expect(views()).toBeNull()
    // The menu is drawn inside the frame, so it remounted in the new one —
    // on Appearance, still showing the row that was pressed.
    expect(screen.getByRole('tab', { name: 'Appearance' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: 'Sidebar or classic layout' })).toHaveTextContent('Classic')

    // And back, from the keyboard this time.
    await userEvent.keyboard('{Enter}')
    expect(m.putSettings).toHaveBeenLastCalledWith({ layout: 'sidebar' })
    expect(views()).not.toBeNull()
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Sidebar or classic layout' }))
  })

  it('opens at the top again from the gear', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Appearance' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sidebar or classic layout' }))
    // Close from the gear, then open again: General, not Appearance.
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    expect(screen.getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
  })

  it('caches another device\'s frame for the next load, and leaves this one alone', async () => {
    // A frame chosen on the phone reaches the desktop tab's settings read
    // (a `settings_updated` from that write triggers one). It is not applied
    // mid-session: the frame decides which tree mounts, so switching it would
    // remount every view — and an open editor or a half-typed quick add with
    // it — because someone changed a preference elsewhere.
    m.lists.mockResolvedValue([list('l1', 'Errands')])
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    const field = await screen.findByPlaceholderText(/Add a task/)
    await userEvent.type(field, 'buy milk')
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(1))

    m.getSettings.mockResolvedValue({ layout: 'classic' })
    await act(async () => {
      vi.mocked(subscribe).mock.calls[0][0]('settings_updated')
      await new Promise((r) => setTimeout(r, 400))
    })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(2))
    expect(views(), 'the frame switched under the user').not.toBeNull()
    expect(field.isConnected).toBe(true)
    expect(field).toHaveValue('buy milk')
    expect(localStorage.getItem(LAYOUT_KEY), 'the next load draws it').toBe('classic')
  })
})
