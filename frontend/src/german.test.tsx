// The app, actually rendered in German.
//
// Every other test in this repo runs outside `I18nProvider` and so reads
// English, which is deliberate — that is what let 1300 assertions survive the
// extraction untouched. The cost is that nothing was proving the other branch
// renders at all: a key held in a table rather than passed to `tr` is out of
// reach of the source scan in `i18n.test.ts`, and a screen that quietly printed
// "module.today" where a heading belongs would have passed every suite here.
//
// So this file is small on purpose and asks two questions the others cannot:
// does the German catalogue reach the DOM, and does anything reach the DOM that
// is obviously a key rather than a sentence.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

beforeEach(() => {
  cleanup()
  vi.clearAllMocks()
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
  // The one line this file turns on.
  m.getSettings.mockResolvedValue({ language: 'de' })
  m.putSettings.mockResolvedValue({})
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
  m.day.mockResolvedValue({
    day: '2026-08-28', planned: false, entries: [], capacity_minutes: null,
    capacity: null, committed_at: null, committed_over_minutes: null, shutdown_at: null, reflection: null,
  })
  m.days.mockResolvedValue([])
  m.habits.mockResolvedValue([])
})

/** Anything on screen that looks like a catalogue key rather than a sentence:
 *  lower-case, dotted, no spaces. The shape `translate` falls back to when it
 *  cannot answer. */
const KEYISH = /^[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+$/

/** Every visible string in the tree — text nodes plus the attributes a screen
 *  reader would read, since half this app's copy lives in an `aria-label`. */
function visibleStrings(root: HTMLElement): string[] {
  const out: string[] = []
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const t = n.textContent?.trim()
    if (t) out.push(t)
  }
  for (const el of root.querySelectorAll('[aria-label],[title],[placeholder]')) {
    for (const a of ['aria-label', 'title', 'placeholder']) {
      const v = el.getAttribute(a)?.trim()
      if (v) out.push(v)
    }
  }
  return out
}

describe('the app in German', () => {
  it('names the tabs in German', async () => {
    render(<App />)
    // "Heute" is the tab and the Today tab's own title, so the strip is asked
    // for by role rather than by text.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Aufgaben' }))
      .toBeInTheDocument())
    for (const name of ['Heute', 'Start', 'Aufgaben', 'Kalender', 'Buchungen']) {
      expect(screen.getAllByRole('button', { name }).length).toBeGreaterThan(0)
    }
  })

  it('prints no catalogue key anywhere on the shell', async () => {
    const { container } = render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Aufgaben' }))
      .toBeInTheDocument())
    const keys = visibleStrings(container).filter((s) => KEYISH.test(s))
    expect(keys, `unresolved keys on screen: ${keys.join(', ')}`).toEqual([])
  })

  it('prints no catalogue key inside settings, where the tables live', async () => {
    // The settings sheet is where the label helpers that hand back IDENTITIES
    // rather than strings all surface at once — the clock, the session length,
    // the calendar fit, the tab labels. If any of them stopped being looked up,
    // this is the screen it would show on.
    const { container } = render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Aufgaben' }))
      .toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Einstellungen' }))
    const keys = visibleStrings(container).filter((s) => KEYISH.test(s))
    expect(keys, `unresolved keys in settings: ${keys.join(', ')}`).toEqual([])
    // And it really is the German sheet, not an English one that happens to
    // contain no dots.
    // Plural: the row's label and the select's accessible name are both it.
    expect(screen.getAllByText('Sprache').length).toBeGreaterThan(0)
  })

  it('prints no catalogue key on any tab', async () => {
    // Every tab, because the keys most likely to rot are the ones held in
    // TABLES rather than passed to `tr` — MODULE_SPECS on Home, VIEWS on Tasks,
    // REPEATS in the event modal, REVIEW_GROUPS on a look-back. The source scan
    // in i18n.test.ts cannot see any of them; a render can.
    const { container } = render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Aufgaben' }))
      .toBeInTheDocument())
    for (const tab of ['Start', 'Aufgaben', 'Kalender', 'Buchungen', 'Heute']) {
      await userEvent.click(screen.getAllByRole('button', { name: tab })[0])
      const keys = visibleStrings(container).filter((s) => KEYISH.test(s))
      expect(keys, `unresolved keys on ${tab}: ${keys.join(', ')}`).toEqual([])
    }
  })

  it('prints no catalogue key in a module that is not on the stock board', async () => {
    // The tab walk above only ever reaches the five modules DEFAULT_LAYOUT
    // ships, so a module nobody has placed is invisible to it. This puts one on
    // the board deliberately — the day-plan card, which is the newest and the
    // one whose keys nothing else would exercise.
    m.getSettings.mockResolvedValue({
      language: 'de',
      dashboard: [{ id: 'p', kind: 'day_plan', x: 0, y: 0, w: 6, h: 6 }],
    })
    m.day.mockResolvedValue({
      day: new Date().toISOString().slice(0, 10), planned: true,
      entries: [], capacity_minutes: null, capacity: null,
      committed_at: null, committed_over_minutes: null, shutdown_at: null, reflection: null,
    })
    const { container } = render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Aufgaben' }))
      .toBeInTheDocument())
    await userEvent.click(screen.getAllByRole('button', { name: 'Start' })[0])
    await screen.findByText('Tagesplan')
    const keys = visibleStrings(container).filter((s) => KEYISH.test(s))
    expect(keys, `unresolved keys on the plan card: ${keys.join(', ')}`).toEqual([])
  })

  it('offers each language under its own name', async () => {
    // The endonyms, which are the one pair of strings that must NOT follow the
    // setting: a menu that offered "German" to somebody who cannot read the
    // English it is written in has failed at the moment it matters.
    render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Aufgaben' }))
      .toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Einstellungen' }))
    const select = screen.getByRole('combobox', { name: /Sprache/i })
    expect([...select.querySelectorAll('option')].map((o) => o.textContent))
      .toEqual(['English', 'Deutsch'])
  })
})
