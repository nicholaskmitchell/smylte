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

// ── the Today header's three buttons ────────────────────────────────────────

const TODAY_HEADER = `
  <div class="shell"><div class="content"><div class="content-head">
    <span class="content-title">Today</span>
    <div class="today-nav">
      <button type="button" class="icon-btn" aria-label="Previous day">&#8249;</button>
      <button type="button" class="icon-btn" aria-label="Next day">&#8250;</button>
    </div>
    <span class="content-sub">Tuesday 26 August</span>
    <span class="spacer"></span>
    <span class="content-sub">4 open &middot; 4 on the day</span>
    <button type="button" class="btn ghost today-review">Review</button>
    <button type="button" class="btn ghost today-shutdown">Shut down</button>
    <button type="button" class="btn ghost today-habits-open"><span class="mono" aria-hidden="true">&#8635;</span> Habits</button>
  </div></div></div>`

describe("the Today header's buttons sit on one line", () => {
  // Two separate defects met here, both reported by eye and both invisible to
  // every other test in the repo.
  //
  // `.today-shutdown` shipped with no rule of its own while its two siblings
  // carried `flex: none; align-self: center`. `.content-head` aligns on the
  // BASELINE, so at >=800px it sat 2.5px low; and between 721 and ~795px it was
  // the only shrinkable item in a nowrap row, so it absorbed the whole shortfall,
  // its label wrapped, and it stood 46px tall beside two 33px buttons — taller
  // AND lower, which is what the screenshot showed.
  //
  // Then the row read 12px, 12px, 22px, because `.today-habits-open` still
  // carried a `margin-left: 10px` from when it was the only button in this header
  // and had to be held off the counts text.
  //
  // 760 is in the shrink band and 390 is past the wrap, so both are load-bearing
  // widths rather than a spread for its own sake.
  it.each([1200, 900, 760])('are the same height and evenly spaced at %ipx', async (w) => {
    await viewport(w)
    const host = await mount(TODAY_HEADER)
    const [review, shut, habits] = ['.today-review', '.today-shutdown', '.today-habits-open']
      .map((s) => box(host.querySelector(s)!))

    expect([shut.h, habits.h], 'one of these wrapped and grew').toEqual([review.h, review.h])
    expect([shut.top, habits.top], 'these do not share a baseline').toEqual([review.top, review.top])
    expect(+(habits.left - shut.right).toFixed(1),
      "the gap after Shut down differs from the one before it — something is "
      + "adding its own margin on top of .content-head's `gap`")
      .toBe(+(shut.left - review.right).toFixed(1))
  })

  it('and the wrapped row starts on the page gutter at 390px', async () => {
    // Below 720px `.content-head` wraps. `margin-left` on the last button put its
    // whole row 10px right of every other left edge in the header — measured at
    // x=24 against a 14px gutter.
    await viewport(390)
    const host = await mount(TODAY_HEADER)
    const gutter = parseFloat(getComputedStyle(host.querySelector('.content-head')!).paddingLeft)
    const habits = box(host.querySelector('.today-habits-open')!)
    const head = box(host.querySelector('.content-head')!)
    expect(+(habits.left - head.left).toFixed(1),
      'the wrapped button row is indented past the header gutter').toBe(gutter)
  })
})

// ── a solid button and the ghost beside it ──────────────────────────────────

describe('a solid button boxes the same as the ghost beside it', () => {
  // `.btn` declared `border: 0`; `.btn.ghost` adds `border: 1px solid var(--rule)`
  // with the same padding and nothing took a pixel back out, so every action row
  // pairing them had the primary button 2px smaller and 1px lower. Measured in the
  // shutdown ritual's own row: Back 57.1x33 at y=4, Shut down 91.5x31 at y=5.
  //
  // `box-sizing: border-box` does not cover it — that governs elements with a
  // specified width or height, and a button has neither, so an auto height is
  // content + padding + border either way. Only a browser can tell you that.
  it('to the pixel, in a modal action row', async () => {
    await viewport(1200)
    const host = await mount(`
      <div class="shell"><div class="modal plan-ritual">
        <div class="modal-actions plan-actions">
          <button class="btn ghost">Back</button>
          <span class="spacer"></span>
          <button class="btn">Shut down</button>
        </div>
      </div></div>`)
    const ghost = box(host.querySelector('.btn.ghost')!)
    const solid = box(host.querySelector('.btn:not(.ghost)')!)

    expect(solid.h, 'the solid button is a different height from the ghost').toBe(ghost.h)
    expect(solid.top, 'the solid button sits off its neighbour').toBe(ghost.top)
  })

  it('and .btn.danger has a border to colour', async () => {
    // `.btn.danger` sets `border-color` and nothing else. Over `border: 0` that
    // coloured nothing, so Settings -> Account's Disconnect — the only control
    // that revokes a live MCP OAuth grant — rendered as bare red text with no
    // outline in a row of bordered controls.
    await viewport(1200)
    const host = await mount('<div class="shell"><button class="btn danger">Disconnect</button></div>')
    const css = getComputedStyle(host.querySelector('.btn.danger')!)
    expect(css.borderTopWidth, 'the danger button has no border at all').not.toBe('0px')
    expect(css.borderTopStyle).not.toBe('none')
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
  const TODAY_TAB = `
    <div class="shell"><div class="content">
      <div class="content-head"><span class="content-title">Today</span></div>
      <form class="quickadd today-add"><input class="input" /></form>
      <div class="label section-label">Habits</div>
      <ul class="today-list"><li class="today-row"><span class="today-title">Water the plants</span></li></ul>
      <div class="empty">Nothing on today yet</div>
      <div class="empty today-quiet">Nothing on the calendar today.</div>
      <div class="today-more">3 more</div>
    </div></div>`

  it.each([undefined, 'workspace'])('under preset=%s', async (preset) => {
    await viewport(390)
    if (preset) document.documentElement.dataset.preset = preset
    const host = await mount(TODAY_TAB)

    const edges = new Map<string, number>()
    for (const sel of ['.content-head', '.quickadd', '.section-label', '.today-row',
      '.empty', '.today-quiet', '.today-more']) {
      edges.set(sel, parseFloat(getComputedStyle(host.querySelector(sel)!).paddingLeft))
    }
    expect([...new Set(edges.values())], 'the Today tab renders as a staircase: '
      + `${[...edges].map(([s, px]) => `${s} ${px}px`).join(', ')}`)
      .toHaveLength(1)
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
// button day nav, the date, the spacer, the count, and the three named actions.
// `today-head` and `today-count` are the two names the fix added; the component
// suite holds them to the JSX.
const TODAY_HEAD = `
  <div class="shell"><div class="main"><div class="content">
    <div class="content-head today-head">
      <span class="content-title">Today</span>
      <div class="today-nav">
        <button type="button" class="icon-btn" aria-label="Previous day">&#8249;</button>
        <button type="button" class="icon-btn" aria-label="Next day">&#8250;</button>
      </div>
      <span class="content-sub">Friday, August 28</span>
      <span class="spacer"></span>
      <span class="content-sub today-count">3 open &middot; 5 on the day</span>
      <button type="button" class="btn ghost today-review">Review</button>
      <button type="button" class="btn ghost today-focus" aria-label="Start working">
        <span class="today-focus__word">Start working</span>
        <span class="today-focus__glyph mono" aria-hidden="true">&#9654;</span></button>
      <button type="button" class="btn ghost today-shutdown">Shut down</button>
      <button type="button" class="btn ghost today-habits-open" aria-label="Habits">
        <span class="mono">&#8635;</span><span class="today-habits-open__word"> Habits</span></button>
    </div>
  </div></div></div>`

describe('the Today header keeps its actions together on a phone', () => {
  const actions = (host: Element) =>
    ['.today-review', '.today-shutdown', '.today-habits-open']
      .map((sel) => ({ sel, ...box(host.querySelector(sel)!) }))

  it('puts Review, Shut down and Habits on one row', async () => {
    // EVIDENCE. Measured in this harness at 390x844 before the fix: the header
    // was 147px over four lines, with `Habits` alone on the last one under
    // `Review` and `Shut down` — which is what "the top buttons are on
    // different rows" means. Two of those four lines were spent on nothing:
    // `.spacer` is `flex: 1` and claimed 81px of trailing space on the title
    // line, pushing everything after it down.
    //
    // After: three lines — title/nav/date, the count, then the three actions
    // together at 284px of the 362 available.
    //
    // Checked across the phone range rather than at one width. 320 is the
    // narrowest phone still in use and the only one where the header takes a
    // fourth line (a long date wraps too, at 154px) — the actions still share
    // theirs, which is the property, and it is the width a rule tuned to 390
    // would quietly break.
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
    // …and the last one ends inside the viewport. `.today-habits-open` is the
    // one that was orphaned, so it is the one that would overflow if the row
    // were forced instead of made to fit.
    expect(laid[2].right, 'the actions run past the right edge').toBeLessThanOrEqual(390)
  })

  it('and does not eat the screen doing it', async () => {
    // 147px before, 129.5px after, on an 844px phone. Not a target so much as a
    // ratchet: this is the one tab opened every morning, and a header that
    // grows again by another line is a regression whether or not it wraps
    // tidily.
    await viewport(390)
    const host = await mount(TODAY_HEAD)
    expect(box(host.querySelector('.content-head')!).h).toBeLessThanOrEqual(135)
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
