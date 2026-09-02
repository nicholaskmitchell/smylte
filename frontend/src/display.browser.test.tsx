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
import { fitNow, measureRoom, measureRows } from './components/DisplayView'

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

// ── how many chips fit, measured against what actually fits ──────────────────
//
// `useCellRoom` decides this, and the browser tier is the only place it can be
// checked: under jsdom every box is 0×0, so the arithmetic would be asserted
// against nothing. Raw markup rather than the component, as everywhere else in
// this file — the class names are held to the real JSX by `DisplayView.test.tsx`.

const chipMarkup = (label: string) => `
  <div class="display-chip display-chip--solid">
    <span class="display-chip__mark"></span>
    <span class="display-chip__time">09:00</span>
    <span class="display-chip__text">${label}</span>
  </div>`

/** A full six-week grid with `n` chips in its first cell. */
const MONTH = (n: number, today = false) => `
  <div class="display display--eink">
    <div class="display-cal">
      <header class="display-cal__head">
        <h1 class="display-title display-cal__title">August 2026</h1>
      </header>
      <div class="display-cal__weekdays">${
        ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
          .map(d => `<span class="display-label display-cal__weekday">${d}</span>`).join('')}
      </div>
      <div class="display-cal__grid" id="grid">
        <div class="display-chip display-cal__probe" aria-hidden="true">
          <span class="display-chip__mark"></span>
          <span class="display-chip__time">00:00</span>
          <span class="display-chip__text">Probe</span>
        </div>
        ${Array.from({ length: 6 }, (_, w) => `
          <div class="display-cal__week">${
            Array.from({ length: 7 }, (_, d) => `
              <div class="display-cal__cell${today && w === 0 && d === 0 ? ' is-today' : ''}">
                <div class="display-cal__daynum">
                  <span class="display-title display-cal__num">${w * 7 + d + 1}</span>
                </div>
                <div class="display-cal__items">${
                  w === 0 && d === 0 ? Array.from({ length: n }, (_, i) => chipMarkup(`Standup ${i}`)).join('') : ''
                }</div>
              </div>`).join('')}
          </div>`).join('')}
      </div>
    </div>
  </div>`

describe('a cell draws only the chips that fit in it', () => {
  // Real panel sizes, portrait and landscape, plus the today cell — whose
  // knocked-out day number is taller than a plain one, so a count taken from
  // the first cell alone overflows on it.
  const PANELS: Array<[number, number]> = [
    [800, 480], [800, 600], [1024, 758], [600, 800], [1280, 800], [480, 800],
  ]

  it.each(PANELS)('at %ix%i the last chip is not cut through its letters',
    async (w, h) => {
      for (const today of [false, true]) {
        document.body.innerHTML = ''
        await viewport(w, h)
        // Measured on a grid with NO chips in it, which is the case that used
        // to be unmeasurable: `measure()` needed a rendered chip to read a
        // height from, so at room 0 — or in a month that simply began with no
        // events — there was nothing to measure and the count latched.
        const empty = await mount(MONTH(0, today))
        const grid = empty.querySelector('#grid') as HTMLElement
        expect(box(grid).h, 'no layout — this is not a browser').toBeGreaterThan(0)
        // THE REAL FUNCTION, imported from the component. A copy of the
        // arithmetic here would go on passing while the page regressed.
        const room = measureRoom(grid)!
        // A panel this size has room for events; a count of 0 here would make
        // every assertion below vacuous.
        expect(room, `${w}x${h}: no room measured at all`).toBeGreaterThan(0)

        document.body.innerHTML = ''
        await viewport(w, h)
        const full = await mount(MONTH(room, today))
        const items = full.querySelector('.display-cal__items') as HTMLElement
        const chips = [...items.querySelectorAll('.display-chip')]
        expect(chips).toHaveLength(room)
        // The property, and the one the old `- 4` broke: every chip the count
        // promised is fully inside the box that clips it. Measured in Chromium
        // before the fix, the last one overflowed by 2.1px at 800×480 — a cut
        // through the middle of the letters, which on a wall reads as a
        // rendering fault rather than as "there is more".
        const bottom = box(items).bottom
        for (const [i, chip] of chips.entries()) {
          expect(box(chip).bottom, `${w}x${h} today=${today}: chip ${i} of ${room} is clipped`)
            .toBeLessThanOrEqual(bottom + 0.5)
        }
        // And it is not simply under-counting: one more would NOT have fitted.
        document.body.innerHTML = ''
        await viewport(w, h)
        const over = await mount(MONTH(room + 1, today))
        const overItems = over.querySelector('.display-cal__items') as HTMLElement
        const last = [...overItems.querySelectorAll('.display-chip')].pop()!
        expect(box(last).bottom, `${w}x${h}: room is too conservative`)
          .toBeGreaterThan(box(overItems).bottom + 0.5)
      }
    })
})

// ── the habits face, held to the same promise as the month grid ─────────────

const dayRow = (label: string) => `
  <li class="display-row">
    <span class="display-row__ring"></span>
    <span class="display-row__text">${label}</span>
  </li>`

const daySection = (label: string, n: number, prefix: string) => n === 0 ? '' : `
  <section class="display-day__section">
    <h2 class="display-label display-day__label">${label}</h2>
    <ul class="display-day__rows">${
      Array.from({ length: n }, (_, i) => dayRow(`${prefix} ${i}`)).join('')}</ul>
  </section>`

const DAY = (habits: number, tasks: number) => `
  <div class="display display--eink">
    <div class="display-day">
      <header class="display-day__head">
        <h1 class="display-title display-day__title">Kitchen</h1>
        <span class="display-title display-day__tally">1/9</span>
      </header>
      <div class="display-day__body" id="body">
        <div class="display-day__section display-day__probe" aria-hidden="true">
          <h2 class="display-label display-day__label">Habits</h2>
          <ul class="display-day__rows">${dayRow('Probe')}</ul>
        </div>
        ${daySection('Habits', habits, 'Habit')}${daySection('Today', tasks, 'Task')}
      </div>
    </div>
  </div>`

describe('the habits face shows only the rows that fit, and counts the rest', () => {
  const PANELS: Array<[number, number]> = [
    [800, 480], [480, 800], [400, 300], [1024, 600],
  ]

  it.each(PANELS)('at %ix%i no row is cut and nothing goes uncounted',
    async (w, h) => {
      const HABITS = 9
      const TASKS = 6
      await viewport(w, h)
      // Measured on a body with NO rows in it — the case that has to work, and
      // the one a real chip could not measure.
      const empty = await mount(DAY(0, 0))
      const body = empty.querySelector('#body') as HTMLElement
      // THE REAL FUNCTION. A copy of the allocation here would go on agreeing
      // with itself while the page regressed.
      const plan = measureRows(body, HABITS, TASKS, 0)!
      expect(plan, `${w}x${h}: nothing measured`).not.toBeNull()

      // Nothing is silently dropped: every row is either drawn or counted.
      expect(plan.habits + plan.tasks + plan.missed).toBe(HABITS + TASKS)
      // And it is not vacuously "draw nothing, count everything".
      expect(plan.habits).toBeGreaterThan(0)

      document.body.innerHTML = ''
      await viewport(w, h)
      const full = await mount(DAY(plan.habits, plan.tasks))
      const shown = full.querySelector('#body') as HTMLElement
      const rows = [...shown.querySelectorAll(
        '.display-day__section:not(.display-day__probe) .display-row')]
      expect(rows).toHaveLength(plan.habits + plan.tasks)
      // The property: every row it promised is inside the box that clips them.
      // Before this, the rows painted straight over the next section's heading
      // and the tail ran off the panel with nothing saying so.
      const bottom = box(shown).bottom
      for (const [i, r] of rows.entries()) {
        expect(box(r).bottom, `${w}x${h}: row ${i} is clipped`)
          .toBeLessThanOrEqual(bottom + 0.5)
      }
      // No heading over an empty block, which is worse than no section at all.
      for (const s of shown.querySelectorAll(
        '.display-day__section:not(.display-day__probe)')) {
        expect(s.querySelectorAll('.display-row').length,
          `${w}x${h}: a heading with nothing under it`).toBeGreaterThan(0)
      }
    })
})

// ── the rolling face, which fits its type instead of clamping it ────────────

const NOW = (title: string, opts: { next?: boolean; est?: boolean } = {}) => `
  <div class="display display--eink">
    <div class="display-now" id="root">
      <header class="display-now__head">
        <h1 class="display-title display-now__name">Kitchen</h1>
        <span class="display-title display-now__tally">1/5</span>
      </header>
      <div class="display-now__main">
        <p class="display-label display-now__eyebrow">
          <span class="display-row__box display-now__mark"></span>Now
        </p>
        <div class="display-now__titlebox">
          <p class="display-title display-now__title" id="title">${title}</p>
        </div>
        ${opts.est === false ? '' : '<p class="display-label display-now__est">1h 30m</p>'}
      </div>
      ${opts.next === false ? '' : `
      <div class="display-now__next">
        <p class="display-label display-now__next-label">Next</p>
        <p class="display-now__next-text">Email Sam about the contract</p>
      </div>`}
      <p class="display-label display-now__more">+2</p>
    </div>
  </div>`

describe('the rolling face fits its headline to the panel', () => {
  const PANELS: Array<[number, number]> = [
    [800, 480], [480, 800], [400, 300], [1024, 600], [296, 128],
  ]
  const LONG = 'Renew the buildings insurance before the renewal date'

  it.each(PANELS)('at %ix%i the headline it chose actually fits its box',
    async (w, h) => {
      await viewport(w, h)
      const host = await mount(NOW(LONG))
      const root = host.querySelector('#root') as HTMLElement
      // THE REAL FUNCTION. A copy of the search here would go on agreeing with
      // itself while the page regressed.
      const fit = fitNow(root)!
      expect(fit, `${w}x${h}: nothing measured`).not.toBeNull()

      const title = host.querySelector('#title') as HTMLElement
      const box = host.querySelector('.display-now__titlebox') as HTMLElement
      title.style.fontSize = `${fit.size}px`
      await new Promise(requestAnimationFrame)
      // The property: what it promised is inside the box that clips it. The
      // headline is the mode — a clipped one is the whole face failing.
      expect(title.scrollHeight, `${w}x${h}: the headline overflows its box`)
        .toBeLessThanOrEqual(box.clientHeight + 1)
      // And not vacuously small: a face that answered 14px everywhere would
      // pass the line above and waste every panel bigger than a badge.
      if (h >= 300) expect(fit.size).toBeGreaterThan(14)
    })

  it('spends a bigger panel on bigger type, not on more of nothing', async () => {
    await viewport(400, 300)
    const small = fitNow((await mount(NOW(LONG))).querySelector('#root') as HTMLElement)!
    document.body.innerHTML = ''
    await viewport(800, 480)
    const big = fitNow((await mount(NOW(LONG))).querySelector('#root') as HTMLElement)!
    expect(big.size).toBeGreaterThan(small.size)
  })

  it('a short title is set larger than a long one in the same box', async () => {
    await viewport(800, 480)
    const long = fitNow((await mount(NOW(LONG))).querySelector('#root') as HTMLElement)!
    document.body.innerHTML = ''
    await viewport(800, 480)
    const short = fitNow((await mount(NOW('Stretch'))).querySelector('#root') as HTMLElement)!
    expect(short.size).toBeGreaterThan(long.size)
  })

  it('concedes the name, then the estimate, then the next item — never the headline',
    async () => {
      // The order is the argument, and `render.py::_render_now` concedes the
      // same three in the same order so the two surfaces drop the same things
      // on the same panel. Asserted as an invariant rather than as an outcome
      // at one size: what a given panel can hold is layout, but "the next item
      // never goes while the display's name is still on screen" is the rule.
      for (const [w, h] of [[800, 480], [400, 300], [296, 128], [240, 80]]) {
        document.body.innerHTML = ''
        await viewport(w, h)
        const fit = fitNow(
          (await mount(NOW(LONG))).querySelector('#root') as HTMLElement)!
        if (!fit.est) expect(fit.head, `${w}x${h}`).toBe(false)
        if (!fit.next) expect(fit.est, `${w}x${h}`).toBe(false)
      }
    })

  it('drops the next item on a panel with no room for it at all', async () => {
    // The case `NowFace` adds one to the count for. If nothing can ever reach
    // it the count's +1 branch is dead code, so it is pinned here.
    await viewport(240, 80)
    const fit = fitNow((await mount(NOW(LONG))).querySelector('#root') as HTMLElement)!
    expect(fit.next).toBe(false)
  })

  it('is set in the app’s own three typefaces, like every other face', async () => {
    await viewport(800, 480)
    const host = await mount(NOW('Stretch'))
    expect(face(host.querySelector('.display-now__title')!)).toBe('Fraunces')
    expect(face(host.querySelector('.display-now__name')!)).toBe('Fraunces')
    expect(face(host.querySelector('.display-now__eyebrow')!)).toBe('JetBrains Mono')
    expect(face(host.querySelector('.display-now__next-text')!)).toBe('Inter')
    // The count is mono and UNTRACKED — a number to be read, not a label to be
    // scanned, the same rule `.display-day__more` follows.
    const more = host.querySelector('.display-now__more')!
    expect(face(more)).toBe('JetBrains Mono')
    expect(getComputedStyle(more).letterSpacing).toBe('normal')
  })
})

describe('the rolling face keeps its last-resort ellipsis', () => {
  it('clamps a title too long for the smallest panel instead of cutting it', async () => {
    // `fitNow` picks a size at which the whole title fits, so this only bites
    // on a title no size can hold. It has to bite: `-webkit-line-clamp` does
    // not survive being a flex item, and when it stopped working the tail ran
    // past the box and `overflow: hidden` cut it through the letters — which on
    // a wall reads as a rendering fault, not as "there is more".
    await viewport(400, 300)
    const host = await mount(NOW(
      'Renew the buildings insurance before the renewal date '.repeat(6)))
    const title = host.querySelector('#title') as HTMLElement
    title.style.fontSize = '30px'
    await new Promise(requestAnimationFrame)
    const lines = Math.round(title.offsetHeight / (30 * 1.24))
    expect(lines, 'the line clamp is not applying').toBeLessThanOrEqual(4)
  })
})
