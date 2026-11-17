// Settings' section list under Field notes, measured in a real browser: the
// open item is marked by a drawn underline instead of the coral bar, a panel's
// headings are set in the serif, and the phone's index keeps its chevron rows
// without the underline. What they change is a computed style, which only a
// browser reads.

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mount, viewport } from './test/browser-measure'
import { applyDesign } from './appearance'

beforeEach(() => { document.body.innerHTML = '' })
afterEach(() => { applyDesign(document.documentElement, null) })

const INK = '<svg class="tab-ink" viewBox="0 0 34 6"><path class="ink" pathLength="1" d="M2 4C9 2.4 18 2 32 3.2"/></svg>'
const NAV = `
  <div class="menu settings-menu"><div class="set-head"><span class="set-title">Settings</span></div>
    <div class="set-body"><div class="set-nav" role="tablist">
      <button class="set-nav-item active"><span>General</span>${INK}</button>
      <button class="set-nav-item"><span>Appearance</span>${INK}</button>
    </div>
    <div class="set-panels"><div class="set-panel"><div class="menu-head">Working day</div></div></div></div>
  </div>`

describe('Settings under Field notes', () => {
  it('marks the open section with the drawn underline, not the coral bar', async () => {
    await viewport(1280)
    const host = await mount(NAV)
    const items = host.querySelectorAll('.set-nav-item')
    const open = getComputedStyle(items[0])
    expect(open.borderLeftColor).toBe('rgba(0, 0, 0, 0)')
    expect(getComputedStyle(items[0].querySelector('.ink')!).opacity).toBe('1')
    // The other one carries an ink too, undrawn, so moving between them draws one on.
    expect(getComputedStyle(items[1].querySelector('.ink')!).opacity).toBe('0')
    expect(getComputedStyle(items[0].querySelector('.tab-ink')!).display).not.toBe('none')
  })

  it('sets a panel heading in Newsreader', async () => {
    await viewport(1280)
    const host = await mount(NAV)
    const head = getComputedStyle(host.querySelector('.set-panel > .menu-head')!)
    expect(head.fontFamily).toMatch(/Newsreader/)
    expect(head.textTransform).toBe('none')
  })

  it('hides the underline in the phone sheet, where the rows carry a chevron', async () => {
    await viewport(390)
    const host = await mount(`<div class="set-sheet">${NAV}</div>`)
    const ink = host.querySelector('.set-sheet .set-nav-item .tab-ink')!
    expect(getComputedStyle(ink).display).toBe('none')
  })

  it('leaves the presets as they were', async () => {
    applyDesign(document.documentElement, 'refined')
    await viewport(1280)
    const host = await mount(NAV)
    const item = host.querySelector('.set-nav-item.active')!
    expect(getComputedStyle(item).borderLeftColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(getComputedStyle(item.querySelector('.tab-ink')!).display).toBe('none')
    expect(getComputedStyle(host.querySelector('.set-panel > .menu-head')!).fontFamily)
      .not.toMatch(/Newsreader/)
  })
})
