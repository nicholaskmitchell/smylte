// A pane's overlay scroll bar, still showing for a moment after a scroll, was
// drawn on top of Settings. An overlay scroll bar of a scroller that is not a
// stacking context is painted after everything in the context that holds it, so
// the cure is a stacking context around the views that Settings is not inside.
// Painting cannot be observed in jsdom; what can be checked is that the context
// exists in the CSS and that the tree puts the views in it and Settings out.
import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api } from './api'
import { LAYOUT_KEY } from './layout'

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

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.getSettings.mockResolvedValue({ time_format: '12h' })
  m.putSettings.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

const css = (file: string) =>
  readFileSync(`src/styles/${file}`, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

const rule = (sheet: string, selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return sheet.match(new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? ''
}

describe('scroll bars stay under Settings', () => {
  it('makes each frame’s views a stacking context of their own', () => {
    expect(rule(css('app.css'), '.views')).toMatch(/isolation:\s*isolate/)
    expect(rule(css('layout.css'), '.frame-main')).toMatch(/isolation:\s*isolate/)
  })

  for (const layout of ['classic', 'sidebar'] as const) {
    it(`keeps Settings outside the views in the ${layout} layout`, async () => {
      localStorage.setItem(LAYOUT_KEY, layout)
      m.getSettings.mockResolvedValue({ time_format: '12h', layout })
      const { container } = render(<App />)
      await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
      await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
      const dialog = await screen.findByRole('dialog', { name: 'Settings' })

      const views = container.querySelector(layout === 'classic' ? '.views' : '.frame-main')
      expect(views).not.toBeNull()
      await waitFor(() => expect(views!.querySelector('.work, .content')).not.toBeNull())
      expect(views!.contains(dialog)).toBe(false)
    })
  }
})
