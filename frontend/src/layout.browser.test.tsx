// The layout facts, measured in a real browser.
//
// Everything else in this repo that defends the stylesheet reads it as TEXT.
// `mobile-layout.test.ts` says why in its own header: vitest runs the unit
// project with `css: false` and jsdom applies no layout at all, so a broken
// stylesheet is invisible to the thousand-odd tests beside it. What that file
// cannot do — and says so — is check that a declaration WINS. It added a
// cascade-shadow parser for exactly that reason, and that parser is a model of
// the cascade, not the cascade.
//
// This file is the cascade. Real Chromium, real stylesheets in `main.tsx`'s
// order, real media queries, real fonts, real `getBoundingClientRect()`.
//
// Every assertion below has TWO numbers behind it: what it measures now, and what
// it measured before the fix that made it true. The second number is the one that
// makes it evidence — a layout assertion that has never been seen red proves
// nothing, and four dead mobile rules shipped green precisely because nobody had
// one.

import { describe, expect, it, beforeEach } from 'vitest'

// The harness — `viewport`, `mount`, `box` — is shared with
// `backlog.aug25.stage4.browser.test.tsx`. It moved out of this file when that
// one arrived, and the reasoning that used to live here (why `document.fonts.
// ready` is awaited AFTER the mount, in particular) moved with it.
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

describe('the harness is actually a browser', () => {
  // A vacuity guard, and not a formality: every assertion in this file is a
  // number read back off a box. Under jsdom every one of those numbers is 0 and
  // every comparison below would pass or fail for reasons having nothing to do
  // with the stylesheet. If this project is ever misconfigured into the unit
  // project's environment, this is what says so.
  it('computes layout, applies the stylesheets, and evaluates media queries', async () => {
    await viewport(390)
    const host = await mount('<div class="shell"><button class="btn ghost">x</button></div>')
    const btn = host.querySelector('.btn')!

    expect(box(btn).h, 'no layout — this is not a browser').toBeGreaterThan(0)
    expect(getComputedStyle(btn).borderTopWidth,
      'the stylesheets did not load; `.btn.ghost` has no border')
      .toBe('1px')
    expect(matchMedia('(max-width: 720px)').matches,
      'the viewport did not take, so no mobile rule is in force').toBe(true)
    expect(document.fonts.status, 'the self-hosted faces never resolved').toBe('loaded')
  })
})

// ── the iOS zoom-on-focus floor ─────────────────────────────────────────────

describe('every text input on a phone clears the 16px iOS floor', () => {
  // Safari zooms the page when a focused input's font-size is under 16px, and
  // the zoom does not come back — on a phone-primary app that is a trap you tap
  // your way into. app.css carries the floor plus two restoring rules explaining
  // why later declarations beat it, and this shipped broken FOUR times: the
  // comment above the rule calls itself "the third time this exact regression has
  // shipped", and the fix written under that comment lost to the same mechanism
  // again. Measured before that fourth fix: `.shut-date` 11px,
  // `.today-est-input` 11px, `.shut-reflect` 14px.
  //
  // Swept, not enumerated. The failure mode every time has been a NEW field
  // added below the media block, so a test naming today's three would have missed
  // each of the four regressions it is written for.
  const FIELDS = [
    '<input class="input" />',
    '<input class="input shut-date" type="date" />',
    '<textarea class="input shut-reflect"></textarea>',
    '<input class="input today-est-input" type="number" />',
    '<input class="input appear-text" />',
    '<select class="input"><option>x</option></select>',
  ]

  it('computes to at least 16px at 390px', async () => {
    await viewport(390)
    const host = await mount(`<div class="shell">${FIELDS.join('')}</div>`)
    const under: string[] = []
    for (const el of host.querySelectorAll<HTMLElement>('.input')) {
      const px = parseFloat(getComputedStyle(el).fontSize)
      if (px < 16) under.push(`${el.className} at ${px}px`)
    }
    expect(under, `${under.join(', ')} — Safari zooms on focus below 16px, and the `
      + 'zoom does not come back').toEqual([])
  })

  it('and the floor only ever scales up', async () => {
    // `--fs-scale` goes down to 0.8 in the Appearance editor. The floor is
    // `max(16px, calc(16px * var(--fs-scale)))` for that reason — a text scale
    // below 1 would drop under 16px and re-arm the zoom.
    await viewport(390)
    const host = await mount('<div class="shell" style="--fs-scale: 0.8">'
      + '<input class="input" /></div>')
    expect(parseFloat(getComputedStyle(host.querySelector('.input')!).fontSize))
      .toBeGreaterThanOrEqual(16)
  })
})

// ── the Today header's three controls ──────────────────────────────────────

const TODAY_HEADER = `
  <div class="shell"><div class="content today-pane"><div class="content-head today-head">
    <span class="content-title">Today</span>
    <div class="today-nav">
      <button type="button" class="icon-btn" aria-label="Previous day">&#8249;</button>
      <button type="button" class="icon-btn" aria-label="Next day">&#8250;</button>
    </div>
    <span class="content-sub">Tuesday 26 August</span>
    <span class="content-sub today-week mono">12 this week</span>
    <span class="spacer"></span>
    <span class="content-sub today-count">4 open &middot; 4 on the day</span>
    <div class="today-acts">
      <button type="button" class="btn ghost today-review">Review</button>
      <button type="button" class="btn ghost today-focus">
        <span class="today-focus__word">Start working</span>
        <span class="today-focus__glyph mono" aria-hidden="true">&#9654;</span></button>
      <button type="button" class="btn ghost today-menu-btn mono" aria-label="More actions">&#183;&#183;&#183;</button>
    </div>
  </div></div></div>`

describe("the Today header's buttons sit on one line", () => {
  // Two separate defects met here, both reported by eye and both invisible to
  // every other test in the repo.
  //
  // `.today-shutdown` shipped with no rule of its own while its siblings carried
  // `flex: none; align-self: center`. `.content-head` aligns on the BASELINE, so
  // at >=800px it sat 2.5px low; and between 721 and ~795px it was the only
  // shrinkable item in a nowrap row, so it absorbed the whole shortfall, its
  // label wrapped, and it stood 46px tall beside two 33px buttons — taller AND
  // lower, which is what the screenshot showed.
  //
  // Then the row read 12px, 12px, 22px, because `.today-habits-open` still
  // carried a `margin-left: 10px` from when it was the only button in this header
  // and had to be held off the counts text.
  //
  // Those two buttons are in the ⋯ popover now, and the finding outlived them:
  // it is about what `.content-head` does to ANY word-bearing child, so the
  // three that remain are held to it.
  //
  // 760 is in the shrink band and 390 is past the wrap, so both are load-bearing
  // widths rather than a spread for its own sake.
  it.each([1200, 900, 760])('are the same height and evenly spaced at %ipx', async (w) => {
    await viewport(w)
    const host = await mount(TODAY_HEADER)
    const [review, focus, more] = ['.today-review', '.today-focus', '.today-menu-btn']
      .map((s) => box(host.querySelector(s)!))

    expect([focus.h, more.h], 'one of these wrapped and grew').toEqual([review.h, review.h])
    expect([focus.top, more.top], 'these do not share a baseline').toEqual([review.top, review.top])
    expect(+(more.left - focus.right).toFixed(1),
      "the gap after Start working differs from the one before it — something is "
      + "adding its own margin on top of .today-acts' `gap`")
      .toBe(+(focus.left - review.right).toFixed(1))
  })

  it('and every figure in the row sits on the buttons\' centre line', async () => {
    // `.content-head` aligns its children on the BASELINE, which is right for a
    // header that is a title and a label and wrong for this one. Every CONTROL
    // here had already opted out of it one at a time — `.today-nav` and
    // `.today-acts` each carry an `align-self: center` — which left the three
    // FIGURES as the only children still on it, hanging off the 24px serif
    // title's baseline. Measured in this harness at 1100px before the fix:
    // buttons and nav centred at 29, the date, the week's total and the day's
    // count at 33.25 and 32.25 — a row whose text sits four pixels below the
    // buttons it shares a line with.
    //
    // `.today-head { align-items: center }` is one declaration on the container
    // rather than a fourth, fifth and sixth `align-self`, and it has to WIN
    // over `.content-head`'s at equal specificity — which is the defect family
    // this whole file exists for, and is why this is measured rather than read
    // out of the stylesheet.
    //
    // At a width where the header is one row, so "the same centre line" is a
    // question with an answer. Every visible child, rather than the three
    // figures by name: what has to hold is that nothing in this header is left
    // on the baseline, including whatever is added to it next.
    await viewport(1200)
    const host = await mount(TODAY_HEADER)
    const head = host.querySelector('.content-head')!
    const mid = (r: DOMRect) => (r.top + r.bottom) / 2
    const band = mid(head.getBoundingClientRect())
    const kids = [...head.children]
      .filter((c) => getComputedStyle(c).display !== 'none')
      .map((c) => ({ cls: c.className, r: c.getBoundingClientRect() }))
      .filter((k) => k.r.height > 0)

    expect(kids.length, 'the fixture stopped rendering the header').toBeGreaterThan(5)
    for (const k of kids) {
      expect(Math.abs(mid(k.r) - band),
        `\`${k.cls}\` is centred at ${mid(k.r).toFixed(2)} against the header's `
        + `${band.toFixed(2)} — it is still on the baseline`)
        .toBeLessThanOrEqual(1)
    }
  })

  it('and the three figures are one size, not two', async () => {
    // `.today-week` colours the week's total and nothing else; `.content-sub`
    // is what makes a header figure 11px mono in the label case. The component
    // shipped the span as `today-week mono` alone, so it inherited the page's
    // 15px body type and read half again as large as the date and the count
    // either side of it.
    //
    // This fixture has always carried `content-sub`, which is exactly why the
    // measured suite could not catch it — the class list is held to the JSX by
    // `TodayView.test.tsx`, and this pins the consequence: the three figures
    // are one type, whatever the cascade does to them.
    await viewport(1200)
    const host = await mount(TODAY_HEADER)
    const size = (sel: string) => getComputedStyle(host.querySelector(sel)!).fontSize

    expect(size('.today-week'), 'the week\'s total is not the date\'s size')
      .toBe(size('.content-sub'))
    expect(size('.today-count')).toBe(size('.content-sub'))
  })

  it('and every wrapped row starts on the page gutter at 390px', async () => {
    // Below 720px `.content-head` wraps. `margin-left` on the last button put
    // its whole row 10px right of every other left edge in the header —
    // measured at x=24 against a 14px gutter.
    //
    // Asserted over the FIRST CHILD OF EVERY ROW rather than over one named
    // button, which is what this did. Which button happens to lead a wrapped
    // row depends on how the row above it filled up, so naming one pins the
    // test to today's wrap point and quietly stops testing the moment that
    // moves — it did, when two of the buttons left for the ⋯ popover.
    await viewport(390)
    const host = await mount(TODAY_HEADER)
    const head = host.querySelector('.content-head')!
    const gutter = parseFloat(getComputedStyle(head).paddingLeft)
    const left = head.getBoundingClientRect().left
    for (const [i, band] of headerRows(head).entries()) {
      const first = [...head.children]
        .filter((c) => getComputedStyle(c).display !== 'none')
        .map((c) => c.getBoundingClientRect())
        .filter((r) => r.height > 0 && r.top < band.bottom - 1 && r.bottom > band.top + 1)
        .sort((a, b) => a.left - b.left)[0]
      expect(+(first.left - left).toFixed(1),
        `row ${i + 1} of the header is indented past the gutter`).toBe(gutter)
    }
  })

  it('keeps its shipped touch height on a phone', async () => {
    // The fence sizes these down to `7px 11px` — 30px tall — because three
    // bordered ghost buttons at full size beside a 24px serif title read as a
    // toolbar. The mobile block puts the shipped `9px 13px` back, at 34px.
    //
    // 34, not 44. These have never reached the touch guideline the row
    // controls are held to, and this does not pretend otherwise: the assertion
    // is that a phone does not get the SMALLER of the two, which is the thing
    // that would be a regression. Closing the last 10px means either growing
    // the buttons — a row of the header, on the tab this pass exists to
    // shorten — or a 44px `::after`, which at this gap would overlap its
    // neighbour's and trip the no-overlap assertion in
    // `backlog.aug25.stage4.browser.test.tsx`.
    //
    // The rule has to WIN, besides: the fence sits ~1300 lines below the mobile
    // block and declares the same property, so it is qualified with `.btn` to
    // out-rank it. That is the defect family this file exists for, and reading
    // the stylesheet cannot catch it.
    await viewport(390)
    const host = await mount(TODAY_HEADER)
    for (const sel of ['.today-review', '.today-focus', '.today-menu-btn']) {
      expect(box(host.querySelector(sel)!).h,
        `${sel} is at its compact desktop size on a phone`).toBeGreaterThanOrEqual(33)
    }
  })
})

// ── one left edge down the Today tab ────────────────────────────────────────

describe('the Today tab has one left edge on a phone', () => {
  // The mobile block used to narrow the gutter by naming selectors one at a time
  // — `.task, .quickadd, .content-head, .cal-head, .empty, .banner` plus
  // `.section-label` — and the Today fence, added ~500 lines later, resolves
  // `var(--gutter)` everywhere. So the labels and the add box were inset 14px and
  // the rows under them 26px: a stair-step repeated down the one tab a phone user
  // opens every morning. The two empty states even disagreed with each other,
  // because `.today-quiet`'s later `padding` shorthand beat the media rule that
  // `.empty` was in.
  //
  // Both roots are checked. A preset is a whole alternative design and declares
  // its own gutter as `:root[data-preset="workspace"]` — (0,2,0) against a bare
  // `:root`'s (0,1,0) — so a plain re-declaration in the media block loses to it
  // and every preset user keeps the desktop gutter, which is this finding again
  // for them.
  //
  // FOUR MORE SELECTORS than the list this started as, and each of the four was
  // drifting the whole time — which is the argument for the list being the
  // whole tab rather than the parts someone happened to look at:
  //
  //   * `.today-load` absorbed the nudge band, whose `padding: 9px 12px`
  //     hardcoded a horizontal instead of taking the gutter. Its text sat at
  //     gutter+12px: 38px against every row's 26px on a desktop, 26px against
  //     14px on a phone.
  //   * `.today-committed-over` had `margin: 0 0 10px` and NO horizontal
  //     padding, on a direct child of `.scroll` — so the look-back's one line
  //     about a day started over capacity rendered flush at x=0.
  //   * `.today-reflection-text` and the agenda rows were right, and are here
  //     so they stay right.
  const TODAY_TAB = `
    <div class="shell"><div class="content today-pane">
      <div class="content-head today-head"><span class="content-title">Today</span></div>
      <form class="quickadd today-add"><input class="input" /></form>
      <div class="today-load"><div class="today-load-line">
        <span class="today-load-fig mono">4h30 of 6h</span></div>
        <div class="today-load-bar"><div class="today-load-fill"></div></div></div>
      <div class="label section-label">Habits</div>
      <ul class="today-list"><li class="today-row"><span class="today-title">Water the plants</span></li></ul>
      <div class="empty">Nothing on today yet</div>
      <div class="today-quiet">Nothing on the calendar today.</div>
      <p class="today-committed-over">Started 45m over.</p>
      <p class="today-reflection-text">Good day, mostly.</p>
      <div class="today-agenda"><div class="agenda-ev"><span>Standup</span></div></div>
      <div class="today-more">3 more</div>
    </div></div>`

  it.each([undefined, 'workspace'])('under preset=%s', async (preset) => {
    await viewport(390)
    if (preset) document.documentElement.dataset.preset = preset
    const host = await mount(TODAY_TAB)

    const edges = new Map<string, number>()
    for (const sel of ['.content-head', '.quickadd', '.today-load', '.section-label',
      '.today-row', '.empty', '.today-quiet', '.today-committed-over',
      '.today-reflection-text', '.today-agenda .agenda-ev', '.today-more']) {
      edges.set(sel, parseFloat(getComputedStyle(host.querySelector(sel)!).paddingLeft))
    }
    expect([...new Set(edges.values())], 'the Today tab renders as a staircase: '
      + `${[...edges].map(([s, px]) => `${s} ${px}px`).join(', ')}`)
      .toHaveLength(1)
  })
})

// ── one centre line across the two lists ────────────────────────────────────

describe("a Today row's cells sit on the title's first line", () => {
  // Reported by eye, in two rounds, and the second round is the interesting one.
  //
  // ROUND ONE was a pixel: `.check` carries `margin-top: 2px`, written for
  // `.task`, whose row is `align-items: flex-start` and where the margin drops
  // the tick from the top of the row onto the first line of the title. The
  // Today row centred, so the margin was added to a box that was then centred
  // WITH it, and the tick landed half the margin below the coloured square
  // beside it. `.dash-day-row` met the same thing when the dashboard borrowed
  // the control and neutralised it there; this row never did.
  //
  // ROUND TWO was a whole line and a half. On a WRAPPED title the centring put
  // every cell in the middle of the block: measured at 390px on three lines,
  // all of them 33.75 down the title against the Tasks tab's 10.5-12.5; at
  // 900px on two lines, 22.5.
  //
  // The fix reopens what the row aligns on. `align-items: flex-start` is what
  // makes the title's box top the content box top — the anchor flexbox cannot
  // otherwise express between siblings — and each cell is then moved to the
  // middle of that first line by half a line minus half its own height, as a
  // percentage of itself so one declaration serves cells of six heights.
  //
  // THE WHOLE ROW moves, not the tick and square alone. `.task` puts its
  // actions on the first line too and its meta line BELOW the title, so
  // "like the Tasks tab" means the row. The half measure was built and
  // rendered: it reads as two records, the square beside line one and
  // `25m  Aug 28` floating at the middle of the block touching nothing.
  //
  // Measured with the REAL faces, which is not a detail: `.list-dot` is placed
  // by `vertical-align: middle`, so where it lands is a fact about Inter's
  // x-height. A rig that failed to load the self-hosted woff2 put it a whole
  // pixel off and made the coloured square look like the defect when the tick
  // was the thing out of place. The harness waits on `document.fonts` for
  // exactly this reason.
  const rows = (title: string) => `
    <div class="shell"><div class="content today-pane"><ul class="today-list">
      <li class="today-row">
        <button class="check">&#10003;</button>
        <span class="today-kind-mark" data-kind="task"><span class="today-kind-box"></span></span>
        <span class="today-title">${title}</span>
        <span class="today-est mono">25m</span><span class="today-due mono">Aug 28</span>
        <button class="today-drop">&#10005;</button></li>
    </ul></div></div>
    <div class="shell"><div class="content">
      <div class="task"><div class="pri-bar"></div><button class="check">&#10003;</button>
        <div class="task-body"><div class="task-title">
          <span class="list-dot"></span>${title}</div></div></div>
    </div></div>`

  const SHORT = 'Hxxg'
  // Long enough to wrap at BOTH widths this runs at — the Today row spends
  // width on its estimate and due cells, so it wraps sooner than the Tasks row
  // does, and the assertions below never compare the two tabs' line counts.
  const LONG = 'Hxxg the quarterly summary and send it round to everyone on the '
    + 'team before the end of the week so that nobody is surprised by it later'

  /** A box's centre, as an offset from the top of the title beside it — the two
   *  lists are mounted one above the other, so absolute tops are not comparable
   *  and offsets are. */
  const off = (host: Element, sel: string, title: string) => {
    const m = host.querySelector(sel)!.getBoundingClientRect()
    const t = host.querySelector(title)!.getBoundingClientRect()
    return +(((m.top + m.bottom) / 2) - t.top).toFixed(2)
  }

  // Both widths and both wrap states, because the four disagree about which
  // element is tallest and that is the whole difficulty. At 390px `.today-est`
  // carries a 34px min-height for its tap target, taller than the 22.5px title,
  // so the row's content box is NOT the title's box — which is what makes
  // `flex-start` alone the wrong fix and the per-cell offset necessary.
  it.each([
    [900, SHORT], [390, SHORT], [900, LONG], [390, LONG],
  ])('every cell, at %ipx', async (w, title) => {
    await viewport(w)
    const host = await mount(rows(title))
    const today = host.querySelector('.today-title')!
    const line = parseFloat(getComputedStyle(today).lineHeight)

    // The title's own first line, which is what every cell is held to. Not a
    // pinned pixel: `--fs-scale` and a preset both move it, and the two engines
    // disagree about font metrics in the last fraction.
    const first = line / 2
    for (const sel of ['.check', '.today-kind-box', '.today-est', '.today-due', '.today-drop']) {
      expect(Math.abs(off(host, sel, '.today-title') - first),
        `at ${w}px on a ${Math.round(today.getBoundingClientRect().height / line)}-line `
        + `title, \`${sel}\` sits ${off(host, sel, '.today-title')} down the title, `
        + `not on its first line at ${first}`)
        .toBeLessThanOrEqual(0.5)
    }

    // …and the Tasks tab, which is the thing the report actually asked for.
    // A comparison rather than a pinned number, and a loose one: the two tabs
    // reach the first line by different routes — `.list-dot` rides it inline on
    // Inter's x-height, the Today mark is placed on it — so they agree to about
    // half a pixel, not exactly.
    const tasksTitle = host.querySelector('.task-title')!
    expect(getComputedStyle(today).fontSize).toBe(getComputedStyle(tasksTitle).fontSize)
    expect(Math.abs(off(host, '.today-kind-box', '.today-title')
      - off(host, '.list-dot', '.task-title')), 'the two tabs disagree about the mark')
      .toBeLessThanOrEqual(1)
  })

  it('and the wrapped phone row keeps its 44px tap boxes', async () => {
    // THE COST OF THE RULE ABOVE, and the reason `.today-row` grew 1.75px of
    // top padding on a phone. The tap target is a 44x44 `::after` CENTRED ON
    // ITS CONTROL. While the row centred, that box was centred in the row and
    // fitted; on the first line it is centred 20.25px down, so 22px of it wants
    // to be above that and the row had 9. The overhang lands on the row ABOVE,
    // which owns those pixels, and the guideline is quietly not met.
    //
    // `backlog.aug25.stage4.browser.test.tsx` measures this properly and in
    // both engines, and it went red at 42px — but only because its own fixture
    // rows happen to be one line. The wrapped row is checked HERE, beside the
    // rule that moved the controls, so the case that motivated the change is
    // the case that is covered.
    // A SPACER above the list, and it is load-bearing rather than tidiness: a
    // row mounted flush against the top of the page has nothing above it, so
    // the pixels a tap box would overhang into are off the document and
    // `elementFromPoint` answers null there. The walk would then measure the
    // clipping rather than the box, and pass or fail for the wrong reason. The
    // real tab has a header above its first row; this stands in for it.
    await viewport(390)
    const host = await mount(`<div style="height:60px"></div>${rows(LONG)}`)
    const el = host.querySelector<HTMLElement>('.today-row .check')!
    const b = el.getBoundingClientRect()
    const cx = b.left + b.width / 2
    const cy = b.top + b.height / 2
    const owns = (y: number) => document.elementFromPoint(cx, y) === el

    expect(cy, 'the row is off the top of the page, so the walk below is vacuous')
      .toBeGreaterThan(44)
    let top = cy; let bot = cy
    while (cy - top < 100 && owns(top - 1)) top -= 1
    while (bot - cy < 100 && owns(bot + 1)) bot += 1
    expect(Math.round(bot - top + 1),
      'the tick on a wrapped phone row has less than a thumb of height')
      .toBeGreaterThanOrEqual(44)
  })
})

// ── the settings sheet on a phone ───────────────────────────────────────────

describe('the settings sheet is reachable to its end on a phone', () => {
  // `.set-panels` carried `height: 100%; overflow-y: auto`, which looks like it
  // should scroll the sheet and does not: `.set-body` has no SPECIFIED height —
  // its 500px comes out of flex layout — so the percentage had nothing definite
  // to resolve against and fell back to `auto`, the content height. The panel
  // then sized itself to 1084px inside a 500px parent that was `overflow: hidden`,
  // and 584 pixels of Settings, including the whole day-capacity section, were
  // unreachable on the device the app is most used on.
  //
  // The rule was applying the whole time, which is exactly why reading the
  // stylesheet would not have found this — only a resolved percentage against a
  // real containing block does.
  it('scrolls the body rather than clipping it', async () => {
    await viewport(390)
    const host = await mount(`
      <div class="shell"><div class="set-overlay"><div class="settings-menu set-sheet">
        <div class="set-head">Settings</div>
        <div class="set-body"><div class="set-panels"><div class="set-panel">
          ${Array.from({ length: 40 }, (_, i) => `<div class="set-row">Row ${i}</div>`).join('')}
        </div></div></div>
      </div></div></div>`)

    const body = host.querySelector<HTMLElement>('.set-body')!
    const panels = host.querySelector<HTMLElement>('.set-panels')!
    const scroller = [body, panels].find((el) => el.scrollHeight > el.clientHeight + 1
      && /auto|scroll/.test(getComputedStyle(el).overflowY))

    expect(scroller, 'the sheet overflows its own height and nothing scrolls, so '
      + 'everything past the fold is unreachable').toBeTruthy()
  })
})

// ── the Today header on a phone ─────────────────────────────────────────────

// The header the real component renders, class for class: a title, the two-
// button day nav, the date, the week's total, the spacer, the count, and the
// three controls. `today-head` and `today-count` are the two names the phone
// fix added; the component suite holds them to the JSX.
const TODAY_HEAD = `
  <div class="shell"><div class="main"><div class="content today-pane">
    <div class="content-head today-head">
      <span class="content-title">Today</span>
      <div class="today-nav">
        <button type="button" class="icon-btn" aria-label="Previous day">&#8249;</button>
        <button type="button" class="icon-btn" aria-label="Next day">&#8250;</button>
      </div>
      <span class="content-sub">Friday, August 28</span>
      <span class="content-sub today-week mono">12 this week</span>
      <span class="spacer"></span>
      <span class="content-sub today-count">3 open &middot; 5 on the day</span>
      <div class="today-acts">
        <button type="button" class="btn ghost today-review">Review</button>
        <button type="button" class="btn ghost today-focus" aria-label="Start working">
          <span class="today-focus__word">Start working</span>
          <span class="today-focus__glyph mono" aria-hidden="true">&#9654;</span></button>
        <button type="button" class="btn ghost today-menu-btn mono" aria-label="More actions">&#183;&#183;&#183;</button>
      </div>
    </div>
  </div></div></div>`

/** The header's rows, as bands of children that OVERLAP vertically.
 *
 *  Not "distinct tops", which is the obvious way to write this and is wrong
 *  here: `.content-head` aligns its children on the BASELINE, so a 24px serif
 *  title and an 11px mono label sitting side by side on one row have tops
 *  several pixels apart. Counting those gave six rows for a header that has
 *  two. Two boxes that overlap vertically are on the same row whatever their
 *  tops say, and that holds under both engines' font metrics. */
function headerRows(head: Element): { top: number; bottom: number; n: number }[] {
  const boxes = [...head.children]
    .filter((c) => getComputedStyle(c).display !== 'none')
    .map((c) => c.getBoundingClientRect())
    .filter((r) => r.height > 0)
    .sort((a, b) => a.top - b.top)
  const bands: { top: number; bottom: number; n: number }[] = []
  for (const b of boxes) {
    const last = bands[bands.length - 1]
    if (last && b.top < last.bottom - 1) {
      last.bottom = Math.max(last.bottom, b.bottom); last.n++
    } else bands.push({ top: b.top, bottom: b.bottom, n: 1 })
  }
  return bands
}

describe('the Today header keeps its actions together on a phone', () => {
  const actions = (host: Element) =>
    ['.today-review', '.today-focus', '.today-menu-btn']
      .map((sel) => ({ sel, ...box(host.querySelector(sel)!) }))

  it('puts Review, Start working and the overflow on one row', async () => {
    // EVIDENCE. Measured in this harness at 390x844: the header was 147px over
    // four lines, with `Habits` alone on the last one under `Review` and
    // `Shut down` — which is what "the top buttons are on different rows"
    // means. Two of those four lines were spent on nothing: `.spacer` is
    // `flex: 1` and claimed 81px of trailing space on the title line, pushing
    // everything after it down. Dropping the spacer and giving the count a line
    // of its own took it to three lines and 129.5px.
    //
    // It is two lines and ~91px now: the week's total moved up beside the date
    // and Shut down and Habits moved into the ⋯ popover, so the count and the
    // three controls share one row and the count's own line went back.
    //
    // It is structural now rather than a measurement that happened to come out
    // right: the three sit in `.today-acts`, one flex item, so no width can put
    // them on different rows. This is what proves the wrapper is actually in
    // the cascade — it failed here in WebKit at 360px when they were siblings.
    //
    // Checked across the phone range rather than at one width. 320 is the
    // narrowest phone still in use and the width a rule tuned to 390 would
    // quietly break.
    for (const w of [320, 360, 390, 430]) {
      document.body.innerHTML = ''
      await viewport(w)
      const host = await mount(TODAY_HEAD)
      const tops = actions(host).map((a) => Math.round(a.top))

      expect(new Set(tops).size,
        `at ${w}px the actions are on ${new Set(tops).size} rows, `
        + `at tops ${tops.join(', ')}`).toBe(1)
    }
  })

  it('in the order they are read, none of them clipped', async () => {
    await viewport(390)
    const host = await mount(TODAY_HEAD)
    const laid = actions(host)

    // Left to right, in DOM order — a wrapped row that reflowed them would
    // still share a top.
    expect(laid.map((a) => a.left)).toEqual([...laid.map((a) => a.left)].sort((x, y) => x - y))
    // …and the last one ends inside the viewport. The ⋯ is the trailing
    // control, so it is the one that would overflow if the row were forced
    // instead of made to fit.
    expect(laid[2].right, 'the actions run past the right edge').toBeLessThanOrEqual(390)
  })

  it('and does not eat the screen doing it', async () => {
    // Measured in this harness against this exact markup, at 390x844:
    // 172px over four rows before, 124px over three after. Not a target so
    // much as a ratchet — this is the one tab opened every morning, and a
    // header that grows back a row is a regression whether or not it wraps
    // tidily.
    //
    // The 172 is the honest baseline and is higher than the 147/129.5 this
    // file used to quote, because those were measured before the week's total
    // joined the header and the fixture did not carry it.
    await viewport(390)
    const host = await mount(TODAY_HEAD)
    expect(box(host.querySelector('.content-head')!).h).toBeLessThanOrEqual(130)
  })

  it('in three rows on a phone, two once there is room', async () => {
    // The ratchet above measures HEIGHT, which a shorter button flatters
    // without anything actually fitting better. This measures what the finding
    // was about: how many rows the header takes. Four at every width before.
    //
    // Two numbers because the answer honestly differs, and the split is at 430
    // rather than at 390 on purpose. Measured widths at 390 inside a 362px
    // content box: title 69, nav 46, date 130, week 101, count 161, actions
    // 161, at an 8px gap. Title+nav+date+week comes to 361 — it FITS, by one
    // pixel, and an earlier draft of this pinned 2 rows at 390 on the strength
    // of it. That is not a layout, it is a coincidence about the length of an
    // English date: `Freitag, 28. August` is wider and would have taken the
    // row back, in a locale this app ships.
    //
    // So the rows each carry ~90px of slack instead, and the header degrades
    // by wrapping rather than by breaking.
    for (const [w, max] of [[320, 3], [360, 3], [390, 3], [430, 2]] as const) {
      document.body.innerHTML = ''
      await viewport(w)
      const host = await mount(TODAY_HEAD)
      const rows = headerRows(host.querySelector('.content-head')!)
      expect(rows.length, `at ${w}px the header takes ${rows.length} rows`)
        .toBeLessThanOrEqual(max)
    }
  })

  it('leaves the other tabs\' spacer alone', async () => {
    // `.cal-head` has dropped its spacer on a phone since the calendar was
    // written; `.content-head` never did, and the fix is scoped to `today-head`
    // rather than to every tab. The Tasks header is shorter and its spacer is
    // what right-aligns the view switcher, so a blanket rule would have moved
    // something nobody complained about.
    await viewport(390)
    const host = await mount(`
      <div class="shell"><div class="main"><div class="content">
        <div class="content-head">
          <span class="content-title">All lists</span>
          <span class="content-sub">4 open</span>
          <span class="spacer"></span>
          <div class="view-tabs"><button class="view-tab active">List</button></div>
        </div>
      </div></div></div>`)
    expect(getComputedStyle(host.querySelector('.spacer')!).display).not.toBe('none')
  })
})

// ── the floating window ──────────────────────────────────────────────────────
//
// The Windows client opens /focus?float=1 in a window that is 420×280 to begin
// with and 320×200 at its floor, and draws a six-pixel ring around the page —
// so the page's viewport is 408×268 down to 308×188. The float rules in app.css
// concede NEXT, then the qualifier line, then the title's second line as the
// height runs out, by media query, because here the viewport IS the window.
// The class names are held to the JSX by FocusView.test.tsx; this file holds
// the numbers.
const FLOAT_FACE = (over = false) => `
  <div class="focus" data-float="" data-state="${over ? 'over' : 'running'}" data-phase="focus">
    <header class="focus-head">
      <span class="label">Focus</span>
      <span class="focus-head__interval">Interval 3</span>
      <span class="spacer"></span>
      <span class="focus-head__tally">2 / 8 done</span>
      <button type="button" class="btn ghost focus-pin" aria-pressed="true">&#9679;</button>
      <button type="button" class="btn ghost focus-back">Dock</button>
    </header>
    <main class="focus-main">
      <div class="focus-phase" role="status">${over ? 'Interval over' : 'Focus'}</div>
      <div class="focus-clock">${over ? '0:00' : '24:59'}</div>
      <div class="focus-now">
        <div class="focus-now__eyebrow">Now</div>
        <h1 class="focus-now__title">Draft the quarterly memo for the board and both of the auditors</h1>
        <div class="focus-now__meta">
          <span>25m est</span><span>12m worked</span>
          <button type="button" class="focus-cap">Until done</button>
        </div>
        <div class="focus-actions">
          <button type="button" class="btn">Done</button>
          <button type="button" class="btn ghost">Not now</button>
          ${over
            ? '<button type="button" class="btn ghost">Take a break</button>'
              + '<button type="button" class="btn ghost">Keep going</button>'
            : '<button type="button" class="btn ghost">Pause</button>'}
        </div>
      </div>
      <div class="focus-next">
        <div class="focus-now__eyebrow">Next</div>
        <div class="focus-next__text"><button type="button" class="focus-pick">Invoice Friday</button></div>
        <div class="focus-next__more">+6 behind that</div>
      </div>
    </main>
  </div>`

describe('the floating window fits its face', () => {
  const shown = (el: Element | null) => !!el && getComputedStyle(el).display !== 'none'
  const fits = (host: HTMLElement) => {
    const main = host.querySelector('.focus-main') as HTMLElement
    expect(main.scrollHeight, `the face overflows: ${main.scrollHeight} in ${main.clientHeight}`)
      .toBeLessThanOrEqual(main.clientHeight + 1)
  }

  it('holds the whole face at its opening size', async () => {
    await viewport(408, 268)
    const host = await mount(FLOAT_FACE())
    fits(host)
    expect(shown(host.querySelector('.focus-next'))).toBe(true)
    expect(shown(host.querySelector('.focus-now__meta'))).toBe(true)
    expect(box(host.querySelector('.focus-head')!).h).toBeLessThanOrEqual(40)
  })

  it('concedes NEXT, then the qualifier line, then the second line of the title', async () => {
    await viewport(408, 230)
    let host = await mount(FLOAT_FACE())
    fits(host)
    expect(shown(host.querySelector('.focus-next'))).toBe(false)
    expect(shown(host.querySelector('.focus-now__meta'))).toBe(true)

    document.body.innerHTML = ''
    await viewport(408, 200)
    host = await mount(FLOAT_FACE())
    fits(host)
    expect(shown(host.querySelector('.focus-now__meta'))).toBe(false)

    document.body.innerHTML = ''
    await viewport(308, 188)
    host = await mount(FLOAT_FACE())
    fits(host)
    // One line of title at the floor: the box is one line-height tall.
    const title = box(host.querySelector('.focus-now__title')!)
    expect(title.h).toBeLessThanOrEqual(15 * 1.12 + 2)
  })

  it('keeps the four-button row of an ended interval inside the window', async () => {
    for (const [w, h] of [[408, 268], [308, 188]] as const) {
      document.body.innerHTML = ''
      await viewport(w, h)
      const host = await mount(FLOAT_FACE(true))
      fits(host)
      for (const btn of host.querySelectorAll('.focus-actions .btn')) {
        const b = box(btn)
        expect(b.right, `${btn.textContent} runs past the right edge at ${w}×${h}`).toBeLessThanOrEqual(w + 0.5)
        expect(b.bottom, `${btn.textContent} runs past the bottom at ${w}×${h}`).toBeLessThanOrEqual(h + 0.5)
      }
    }
  })
})
