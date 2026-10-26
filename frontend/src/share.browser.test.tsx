// The share page, measured in a real browser.
//
// The page shows text another person typed, to a stranger on a phone, in a
// column that must never scroll sideways. A long unbroken token (a pasted URL is
// one) is the way that goes wrong, and so is a clock too wide for its card at
// 320px. Neither is visible to the unit project: jsdom computes no layout and
// `css: false` stubs the stylesheets. Hence raw markup, the real stylesheets in
// `main.tsx`'s order, and `getBoundingClientRect()`.
//
// Class-for-class from `SharePage.tsx`, held to the real JSX by
// `SharePage.test.tsx`, so this file stays a measurement harness rather than a
// second source of truth about what the page renders.
import { describe, expect, it, beforeEach } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const LONG = 'W'.repeat(200)

// The live dot pulses forever, and `mount()` settles every animation with
// `finish()`, which throws on one that never ends. The dot is 7px and its pulse
// moves nothing, so it is stilled here rather than the harness changed.
const DOT = '<span class="share-live__dot" style="animation: none"></span>'

const PAGE = `
  <div class="share-wrap">
    <main class="share">
      <header class="share-head">
        <h1 class="share-head__title">Shared with you</h1>
        <div class="share-head__day">Monday, October 26</div>
        <div class="share-head__meta">
          <span class="share-live">${DOT}Live</span>
          <span class="share-readonly">Read-only</span>
        </div>
      </header>
      <section class="share-card share-presence" data-state="focusing" data-phase="focus">
        <div class="share-presence__eyebrow">Focusing</div>
        <div class="share-presence__clock" id="clock">1:02:03</div>
        <div class="share-presence__bar"><span style="width: 40%"></span></div>
        <div class="share-now">
          <div class="share-now__label">Working on</div>
          <h2 class="share-now__title" id="now">${LONG}</h2>
        </div>
        <div class="share-today">
          <div class="share-today__head">
            <span class="share-label">Today</span>
            <span class="share-today__count">1 of 2 done</span>
          </div>
          <ul class="share-rows">
            <li class="share-row is-now">
              <span class="share-row__mark"></span>
              <span class="share-row__text" id="row">${LONG}</span>
              <span class="share-row__due">Today 3:00 PM</span>
            </li>
          </ul>
        </div>
      </section>
      <section class="share-card share-agenda">
        <div class="share-label">Coming up</div>
        <div class="share-day">
          <h2 class="share-day__label">Today</h2>
          <ul class="share-evs">
            <li class="share-ev">
              <time class="share-ev__time">10:00 AM–11:30 AM</time>
              <span class="share-ev__dot" style="background: #D94F70"></span>
              <span class="share-ev__title" id="ev">${LONG}</span>
            </li>
          </ul>
        </div>
      </section>
      <details class="share-card share-list" open>
        <summary class="share-list__sum">
          <span class="share-list__dot"></span>
          <span class="share-list__name" id="list">${LONG}</span>
          <span class="share-list__count">12</span>
        </summary>
        <ul class="share-tasks">
          <li class="share-task" data-depth="3">
            <span class="share-task__text" id="task">${LONG}</span>
            <span class="share-task__due is-late">Due Oct 20</span>
          </li>
        </ul>
      </details>
      <footer class="share-foot"><span>Read-only. Updates on its own.</span></footer>
    </main>
  </div>`

describe.each([320, 390])('the share page at %ipx', (width) => {
  it('is a real browser with the app’s stylesheet and fonts loaded', async () => {
    // The vacuity guard `layout.browser.test.tsx` argues for: under jsdom every
    // box is 0x0 and everything below would pass for the wrong reason.
    await viewport(width)
    const host = await mount(PAGE)
    expect(box(host.querySelector('#clock')!).h, 'no layout — this is not a browser').toBeGreaterThan(0)
    const family = getComputedStyle(host.querySelector('#clock')!).fontFamily
    expect(family.split(',')[0].replace(/["']/g, '').trim()).toBe('Newsreader')
    expect(document.fonts.check('12px "Newsreader"'), 'Newsreader did not load').toBe(true)
  })

  it('does not scroll sideways, whatever a title is made of', async () => {
    await viewport(width)
    const host = await mount(PAGE)
    const wrap = host.querySelector('.share-wrap')!
    expect(wrap.scrollWidth, `the page widened to ${wrap.scrollWidth}`)
      .toBeLessThanOrEqual(wrap.clientWidth)
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth)
  })

  it('wraps a 200-character unbroken title inside the card it is in', async () => {
    await viewport(width)
    const host = await mount(PAGE)
    for (const id of ['now', 'row', 'ev', 'list', 'task']) {
      const el = host.querySelector(`#${id}`)!
      const card = el.closest('.share-card')!
      expect(box(el).right, `#${id} runs past its card`).toBeLessThanOrEqual(box(card).right + 0.5)
      // Wrapped onto more than one line: 200 W's are far wider than a phone.
      const line = parseFloat(getComputedStyle(el).lineHeight) || parseFloat(getComputedStyle(el).fontSize) * 1.2
      expect(box(el).h, `#${id} did not wrap`).toBeGreaterThan(line * 1.5)
    }
  })

  it('keeps the clock on one line inside its card, even past an hour', async () => {
    await viewport(width)
    const host = await mount(PAGE)
    const clock = host.querySelector('#clock')!
    const card = clock.closest('.share-card')!
    const size = parseFloat(getComputedStyle(clock).fontSize)
    // `line-height: 1`: one line is the font size tall, two would be double.
    expect(box(clock).h, 'the clock wrapped').toBeLessThan(size * 1.5)
    expect(clock.scrollWidth).toBeLessThanOrEqual(clock.clientWidth + 1)
    expect(box(clock).right).toBeLessThanOrEqual(box(card).right)
  })
})
