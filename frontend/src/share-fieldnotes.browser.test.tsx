// The share page's task rows under Field notes, measured in a real browser.
//
// The open row's mark used to be a --rule circle at 1.3:1; Field notes draws the
// frame and the tick instead, and the title is set in Newsreader like Today's.
// Which of them shows is a computed style, and the page must still not scroll
// sideways at 320px with a long title in it. Fixture markup follows
// `share.browser.test.tsx`, plus the marks `SharePage.tsx` adds under Field
// notes (held to the real JSX by `PublicPages.fieldnotes.test.tsx`).
import { beforeEach, describe, expect, it } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const LONG = 'W'.repeat(200)

const MARK = `<span class="share-row__mark" aria-hidden="true"><svg class="check-ink" viewBox="0 0 28 28" aria-hidden="true" focusable="false"><path class="check-frame" d="M4 4L24 5L23 24L5 23Z"/><path class="check-tick ink" pathLength="1" d="M8.6 14.6C10 15.8 11.4 17.6 12.4 19C14.6 14.4 18.6 9.2 23.8 5.8"/></svg></span>`

const PAGE = `
  <div class="share-wrap">
    <main class="share">
      <section class="share-card share-presence">
        <div class="share-today">
          <ul class="share-rows">
            <li class="share-row" id="open">
              ${MARK}
              <span class="share-row__text" id="open-text"><span class="share-row__name">Draft the memo</span></span>
              <span class="share-row__due">Today 3:00 PM</span>
            </li>
            <li class="share-row is-done" id="done">
              ${MARK}
              <span class="share-row__text"><span class="share-row__name">Email Sam</span><span class="share-sr"> done</span></span>
            </li>
            <li class="share-row" id="long">
              ${MARK}
              <span class="share-row__text" id="long-text"><span class="share-row__name">${LONG}</span></span>
              <span class="share-row__due">Today 3:00 PM</span>
            </li>
          </ul>
        </div>
      </section>
    </main>
  </div>`

describe('the share page’s rows under Field notes', () => {
  it('is a real browser with the app’s stylesheet and fonts loaded', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    expect(box(host.querySelector('#open-text')!).h, 'no layout — this is not a browser').toBeGreaterThan(0)
    expect(document.fonts.check('12px "Newsreader"'), 'Newsreader did not load').toBe(true)
  })

  it('hides the tick on an open row and shows it on a done one', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    const tick = (id: string) => host.querySelector(`#${id} .check-tick`)!
    expect(getComputedStyle(tick('open')).opacity).toBe('0')
    expect(getComputedStyle(tick('done')).opacity).toBe('1')
  })

  it('draws the mark with no border and no fill of its own', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    for (const id of ['open', 'done']) {
      const mark = getComputedStyle(host.querySelector(`#${id} .share-row__mark`)!)
      expect(mark.borderTopWidth, `#${id} mark has a border`).toBe('0px')
      expect(mark.backgroundColor, `#${id} mark has a fill`).toBe('rgba(0, 0, 0, 0)')
    }
  })

  it('sets the title in Newsreader at 20px, and a done one without a line-through', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    const text = getComputedStyle(host.querySelector('#open-text')!)
    expect(text.fontFamily.split(',')[0].replace(/["']/g, '').trim()).toBe('Newsreader')
    expect(text.fontSize).toBe('20px')
    expect(getComputedStyle(host.querySelector('#done .share-row__text')!).textDecorationLine).toBe('none')
  })

  it('does not scroll sideways at 320px, with a 200-character title in a row', async () => {
    await viewport(320)
    const host = await mount(PAGE)
    const wrap = host.querySelector('.share-wrap')!
    expect(wrap.scrollWidth, `the page widened to ${wrap.scrollWidth}`).toBeLessThanOrEqual(wrap.clientWidth)
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth)
    const text = host.querySelector('#long-text')!
    expect(box(text).right).toBeLessThanOrEqual(box(text.closest('.share-card')!).right + 0.5)
  })
})

describe('Display mode under Field notes', () => {
  it('keeps a 44px tap height on the mode switch', async () => {
    // A tablet you tap to check things off: the presets' buttons are 44px
    // (app.css .dmode-bar .btn), and the segmented switch keeps that height.
    const host = await mount(`
      <div class="dmode-bar">
        <div class="view-tabs" style="--n: 3; --i: 0">
          <button type="button" class="view-tab active" aria-pressed="true">Today</button>
          <button type="button" class="view-tab" aria-pressed="false">Tasks</button>
          <button type="button" class="view-tab" aria-pressed="false">Calendar</button>
        </div>
      </div>`)
    for (const b of host.querySelectorAll<HTMLElement>('.view-tab')) {
      expect(b.getBoundingClientRect().height, b.textContent!).toBeGreaterThanOrEqual(44)
    }
  })
})
