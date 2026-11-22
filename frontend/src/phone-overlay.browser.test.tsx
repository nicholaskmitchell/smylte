// The phone's tab bar against a dialog, measured in a real browser.
//
// On a phone the frame is a column: the view (`.frame-main`), then `nav.tabbar`.
// The bar's children are positioned, and the view is only isolated, so the bar
// drew over the scrim and sheet of a dialog opened inside the view. Which one
// paints on top is stacking order, which jsdom does not compute: ask the
// browser what is at the point instead. Fixture markup follows the frame in
// `App.tsx` and the planning ritual's overlay in `TodayView.tsx`.
import { beforeEach, describe, expect, it } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => {
  document.body.innerHTML = ''
  // Field notes, which the browser setup already switches on; said again here
  // because the tab bar's `+` is drawn by its rules.
  document.documentElement.dataset.surface = 'app'
})

const PAGE = `
  <div class="frame">
    <div class="frame-main">
      <div class="overlay"><div class="modal plan-ritual"><button id="skip">Skip</button></div></div>
    </div>
    <nav class="tabbar"><button class="tab">Today</button><button class="tab-add">+</button></nav>
  </div>`

describe('a dialog on the phone', () => {
  it('is drawn over the tab bar, not under it', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    const overlay = host.querySelector('.overlay')!
    for (const sel of ['.tab-add', '.tab']) {
      const b = box(host.querySelector(sel)!)
      expect(b.h, `${sel} has no layout`).toBeGreaterThan(0)
      const hit = document.elementFromPoint(b.left + b.w / 2, b.top + b.h / 2)
      expect(hit, `nothing at ${sel}`).not.toBeNull()
      expect(overlay.contains(hit), `${sel} paints over the dialog's scrim`).toBe(true)
    }
  })
})
