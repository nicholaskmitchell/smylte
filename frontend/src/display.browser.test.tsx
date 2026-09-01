// The display's typography, measured in a real browser.
//
// A display is drawn in the app's own three typefaces — Fraunces for the things
// that are looked at, tracked uppercase JetBrains Mono for micro-labels and
// every clock, Inter for the things that are read — and `render.py` draws the
// server-side version in the same three. That is what makes a panel on a wall
// read as Smylte rather than as a dashboard that happens to hold the same data,
// and it is exactly the kind of thing that rots silently: a refactor drops a
// class, everything still renders, and the page quietly becomes system-sans.
//
// It cannot be asserted anywhere else. The unit project runs jsdom with
// `css: false` — no cascade, no `document.fonts`, no computed family — so every
// assertion below would be vacuous there. Hence real Chromium, the real
// stylesheets in `main.tsx`'s order (browser-setup.ts), and the real fonts.
//
// Raw markup rather than the component, matching the convention `browser
// -measure.ts` documents: the class names are held to the real JSX by
// `DisplayView.test.tsx`, so this file stays a measurement harness rather than a
// second source of truth about what the page renders.

import { describe, expect, it, beforeEach } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

/** The face that actually won, not the stack that was asked for. */
const face = (el: Element) =>
  getComputedStyle(el).fontFamily.split(',')[0].replace(/["']/g, '').trim()

const CAL = (palette: 'color' | 'eink') => `
  <div class="display display--${palette}">
    <div class="display-cal">
      <div class="display-cal__toosmall">
        <p class="display-title display-cal__toosmall-title">Too small for a month.</p>
        <p class="display-cal__toosmall-hint">Set it to habits + today.</p>
      </div>
      <header class="display-cal__head">
        <h1 class="display-title display-cal__title">August 2026</h1>
        <span class="display-label display-cal__name">Hallway</span>
      </header>
      <div class="display-cal__weekdays">
        <span class="display-label display-cal__weekday">Sun</span>
      </div>
      <div class="display-cal__grid">
        <div class="display-cal__week">
          <div class="display-cal__cell">
            <div class="display-cal__daynum">
              <span class="display-title display-cal__num" id="inside">17</span>
              <span class="display-label display-cal__more">+3</span>
            </div>
            <div class="display-cal__items">
              <div class="display-chip display-chip--solid">
                <span class="display-chip__mark"></span>
                <span class="display-chip__time">09:00</span>
                <span class="display-chip__text">Standup</span>
              </div>
            </div>
          </div>
          <div class="display-cal__cell is-outside" id="outside-cell">
            <div class="display-cal__daynum">
              <span class="display-title display-cal__num" id="outside">31</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>`

describe('the display is drawn in the app’s own type', () => {
  it('is a real browser with the display stylesheet loaded', async () => {
    // The vacuity guard `layout.browser.test.tsx` argues for: under jsdom every
    // family below comes back empty and every assertion in this file passes or
    // fails for reasons having nothing to do with the stylesheet.
    await viewport(800, 480)
    const host = await mount(CAL('eink'))
    const title = host.querySelector('.display-cal__title')!
    expect(box(title).h, 'no layout — this is not a browser').toBeGreaterThan(0)
    expect(getComputedStyle(host.querySelector('.display')!).backgroundColor,
      'display.css did not load')
      .toBe('rgb(255, 255, 255)')
    // And the faces themselves are really here. `getComputedStyle` reports the
    // stack that was DECLARED whether or not the file ever arrived, so every
    // family assertion below would pass against three missing fonts and a page
    // rendering entirely in Times. `mount` awaits `document.fonts.ready` after
    // inserting the markup, so by now these have either loaded or failed.
    for (const family of ['Fraunces', 'Inter', 'JetBrains Mono']) {
      expect(document.fonts.check(`12px "${family}"`), `${family} did not load`)
        .toBe(true)
    }
  })

  it('sets headlines and day numbers in the serif, at the app’s own weight',
    async () => {
      await viewport(800, 480)
      const host = await mount(CAL('color'))
      expect(face(host.querySelector('.display-cal__title')!)).toBe('Fraunces')
      expect(face(host.querySelector('#inside')!)).toBe('Fraunces')
      // 500, the weight `.cal-title` and `.day-col-head .dnum` use in app.css.
      // The display borrows the product's headline rather than inventing one.
      expect(getComputedStyle(host.querySelector('.display-cal__title')!).fontWeight)
        .toBe('500')
    })

  it('sets micro-labels in tracked uppercase mono', async () => {
    await viewport(800, 480)
    const host = await mount(CAL('color'))
    for (const sel of ['.display-cal__name', '.display-cal__weekday']) {
      const el = host.querySelector(sel)!
      expect(face(el), sel).toBe('JetBrains Mono')
      expect(getComputedStyle(el).textTransform, sel).toBe('uppercase')
      // The tracking is the label: uppercase mono set solid is a different
      // thing from the app's, which is airy on purpose.
      expect(parseFloat(getComputedStyle(el).letterSpacing), sel).toBeGreaterThan(0.5)
    }
  })

  it('sets every clock in mono and the text beside it in the sans', async () => {
    await viewport(800, 480)
    const host = await mount(CAL('color'))
    // `.task-meta .due` is mono in app.css and so is this; it also buys tabular
    // figures, which is what lets times line up down a column.
    expect(face(host.querySelector('.display-chip__time')!)).toBe('JetBrains Mono')
    expect(face(host.querySelector('.display-chip__text')!)).toBe('Inter')
  })

  it('counts are mono but NOT tracked — a number to read, not a label to scan',
    async () => {
      await viewport(800, 480)
      const host = await mount(CAL('color'))
      const more = host.querySelector('.display-cal__more')!
      expect(face(more)).toBe('JetBrains Mono')
      expect(getComputedStyle(more).letterSpacing).toBe('normal')
    })

  it('pins Fraunces to its sturdy optical size on eink, and lets it breathe on colour',
    async () => {
      await viewport(800, 480)
      // Fraunces' high optical sizes are a display cut with fine hairlines,
      // which is exactly what one bit deep destroys — measured against a
      // thresholded render, the top of the axis loses the stems of "August".
      // `none` pins the font's own default, which is the instance the
      // server-side renderer is built at.
      const ink = await mount(CAL('eink'))
      expect(getComputedStyle(ink.querySelector('.display')!).fontOpticalSizing)
        .toBe('none')
      document.body.innerHTML = ''
      const colour = await mount(CAL('color'))
      // An LCD has no threshold to survive and the display cut is better there.
      expect(getComputedStyle(colour.querySelector('.display')!).fontOpticalSizing)
        .toBe('auto')
    })

  it('tells a day outside the month apart by SIZE, not by colour alone',
    async () => {
      await viewport(800, 480)
      const host = await mount(CAL('eink'))
      const inside = getComputedStyle(host.querySelector('#inside')!)
      const outside = getComputedStyle(host.querySelector('#outside')!)
      // The eink palette has exactly one ink: `--d-muted` there IS black. So a
      // colour step alone left July's last week indistinguishable from August's
      // first — the whole reason those days are drawn. Size is one of the three
      // things that survive thresholding.
      expect(inside.color).toBe(outside.color)
      expect(parseFloat(outside.fontSize)).toBeLessThan(parseFloat(inside.fontSize))
    })

  it('swaps the month for a sentence only on a screen no phone ever is',
    async () => {
      // A 2.9" panel: 296×128. Seven columns of 39px is a smear, and the
      // browser version of it was six empty slivers with no day numbers, which
      // reads as broken rather than as misconfigured.
      await viewport(296, 128)
      let host = await mount(CAL('eink'))
      expect(getComputedStyle(host.querySelector('.display-cal__grid')!).display)
        .toBe('none')
      expect(getComputedStyle(host.querySelector('.display-cal__toosmall')!).display)
        .toBe('block')

      // A 4.2" panel renders a real month and must not be caught...
      document.body.innerHTML = ''
      await viewport(400, 300)
      host = await mount(CAL('eink'))
      expect(getComputedStyle(host.querySelector('.display-cal__grid')!).display)
        .not.toBe('none')

      // ...and neither must a phone. The owner checking their hallway display
      // from bed should get the month, not a lecture about panel sizes.
      for (const [w, h] of [[360, 780], [390, 844], [667, 375]]) {
        document.body.innerHTML = ''
        await viewport(w, h)
        host = await mount(CAL('eink'))
        expect(getComputedStyle(host.querySelector('.display-cal__toosmall')!).display,
          `${w}x${h}`).toBe('none')
      }
    })

  it('takes no input, in the cascade rather than only in the JSX', async () => {
    await viewport(800, 480)
    const host = await mount(CAL('color'))
    // `DisplayView.test.tsx` asserts there is nothing clickable in the markup;
    // this is the other half — even if something focusable appeared, the page
    // itself does not accept a pointer.
    expect(getComputedStyle(host.querySelector('.display')!).pointerEvents).toBe('none')
  })
})
