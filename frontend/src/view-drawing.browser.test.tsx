// The Settings section column's drawing under Field notes, measured in a real
// browser: it sits at the foot of the column on a tall window and is gone on a
// short one, where it would not fit. Fixture markup follows
// `settings-fieldnotes.browser.test.tsx` (the wrapper is held to the real JSX by
// `SettingsMenu.fieldnotes.test.tsx`).
import { beforeEach, describe, expect, it } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

// All eleven sections SettingsMenu.tsx lists (`SECTIONS`, not exported): the
// drawing has to fit under the real count, not under two.
const SECTION_NAMES = ['General', 'Appearance', 'Tasks', 'Calendar', 'Focus', 'Notifications',
  'Email', 'Sharing', 'Displays', 'Account', 'About']
// A panel taller than any window, so the menu is held at its real max-height
// and the section column has the height of the menu rather than of its items.
const NAV = `
  <div class="menu settings-menu"><div class="set-head"><span class="set-title">Settings</span></div>
    <div class="set-body"><div class="set-nav" role="tablist">
      ${SECTION_NAMES.map((n, i) =>
    `<button class="set-nav-item${i === 0 ? ' active' : ''}"><span>${n}</span></button>`).join('\n      ')}
      <div class="view-drawing set-nav-drawing" aria-hidden="true"><svg class="day-drawing" viewBox="0 0 100 125"><path class="dm-line" d="M10 10L90 110"/></svg></div>
    </div>
    <div class="set-panels"><div class="set-panel"><div class="menu-head">Working day</div><div style="height:3000px"></div></div></div></div>
  </div>`

async function measure(height: number) {
  await viewport(1280, height)
  const host = await mount(NAV)
  const items = host.querySelectorAll('.set-nav-item')
  expect(items.length).toBe(SECTION_NAMES.length)
  const drawing = host.querySelector('.view-drawing.set-nav-drawing')!
  return {
    drawing,
    last: box(items[items.length - 1]),
    nav: box(host.querySelector('.set-nav')!),
    d: box(drawing),
  }
}

describe('the Settings drawing under Field notes', () => {
  it('sits below the last section, at the foot of the column, at 1280x900', async () => {
    const { drawing, last, nav, d } = await measure(900)
    expect(d.h, 'the drawing has no box').toBeGreaterThan(0)
    expect(d.top).toBeGreaterThanOrEqual(last.bottom)
    expect(d.top).toBeGreaterThanOrEqual(nav.top)
    expect(d.bottom).toBeLessThanOrEqual(nav.bottom + 0.5)
    expect(nav.bottom - d.bottom, 'the drawing is not at the foot of the column').toBeLessThan(1)
    expect(d.left).toBeGreaterThanOrEqual(nav.left)
    expect(d.right).toBeLessThanOrEqual(nav.right + 0.5)
    const svg = box(drawing.querySelector('.day-drawing')!)
    expect([svg.w, svg.h]).toEqual([112, 140])
  })

  it('still fits inside the column at 1280x760, the shortest height it shows', async () => {
    const { last, nav, d } = await measure(760)
    expect(d.h, 'the drawing has no box').toBeGreaterThan(0)
    expect(d.top).toBeGreaterThanOrEqual(last.bottom)
    expect(d.bottom).toBeLessThanOrEqual(nav.bottom + 0.5)
  })

  it('is not displayed at 1280x700', async () => {
    await viewport(1280, 700)
    const host = await mount(NAV)
    expect(getComputedStyle(host.querySelector('.view-drawing.set-nav-drawing')!).display).toBe('none')
  })
})
