/**
 * The 2026-08-25 sweep, stage 4: the three findings only a real cascade can see.
 *
 * Three of the stage's thirteen are here because jsdom cannot answer them: a
 * block whose negative margins are sized for the wrong parent, a `:hover` rule
 * that only exists inside the phone-only media block, and three tap targets
 * measured against the 44px guideline. The other ten are in
 * `backlog.aug25.stage4.test.tsx`; one gets no pin at all (docs/STAGES.md says
 * why).
 *
 * `layout.browser.test.tsx` is the sibling and its header is the argument for
 * this whole project. Same harness, same rule: raw markup, real stylesheets in
 * `main.tsx`'s order, real media queries, real `getBoundingClientRect()`.
 *
 * **These findings are CLOSED**, and every test here is now an ordinary
 * regression test that must stay green. Each pin was written first as
 * `it.fails` and its marker was dropped in the commit that fixed it. Each carries the
 * number it measures TODAY, taken in this harness rather than reasoned about —
 * a layout assertion nobody has seen red proves nothing, and this repo has four
 * dead mobile rules in its history that shipped green.
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

// ── the archived-calendar agenda ────────────────────────────────────────────

// The mount point, class for class: `SettingsMenu` renders
// `<ArchivedCalendarsSection>` inside `.set-panel` > `.set-panels` > `.set-body`
// of `.settings-menu.set-sheet` — a settings SHEET, never a `.modal`.
const ARCHIVED_IN_SETTINGS = `
  <div class="shell"><div class="set-overlay"><div class="settings-menu set-sheet">
    <div class="set-head">Settings</div>
    <div class="set-body"><div class="set-panels"><div class="set-panel">
      <div class="arch-caption">Showing events Mar – Apr</div>
      <div class="arch-events">
        <div class="arch-day">
          <div class="arch-day-head">Monday 9 March</div>
          <div class="agenda-ev" style="--ev-c: #1971C2">
            <span class="agenda-time mono">09:00</span><span class="agenda-title">Standup</span>
          </div>
        </div>
      </div>
    </div></div></div>
  </div></div></div>`

describe('2026-08-25 — the archived-calendar agenda on a phone', () => {
  // ── AUDIT (open): app.css:662 — the archived-calendar agenda's negative
  //    margins are sized for a .modal but it renders inside the settings panel,
  //    clipping its colour rules and giving the sheet a sideways scroll ──────
  it('stays inside the sheet that actually contains it', async () => {
    // EVIDENCE. `.arch-events { margin: 0 -18px -18px }` cancels a `.modal`'s
    // 18px padding so its rows can run edge to edge. But the component that
    // renders `.arch-events` is `ArchivedCalendarsSection`, which SettingsMenu
    // mounts inside `.set-panels` — and the settings container (`.menu` on
    // desktop, `.settings-menu.set-sheet` on a phone) is padded 14px, not 18px.
    // The block ends up 36px wider than its parent's content box: 18px past the
    // right edge, which becomes scrollable overflow because the ancestor
    // scroller declares only `overflow-y: auto` (so `overflow-x` computes to
    // `auto`), and 18px past the left, which is unreachable in LTR and simply
    // clipped — taking each row's 2px `--ev-c` calendar-colour rule with it.
    //
    // Measured in THIS harness at 390x844, which is the whole reason it is here:
    //   .set-sheet          390px wide, left edge x = 0
    //   .set-body           clientWidth 362, scrollWidth 380   <- 18px of scroll
    //   .arch-events        398px wide, left edge x = -4
    //   .agenda-ev          left edge x = -4, border-left 2px  <- outside the sheet
    // The colour rule that says which calendar the preview belongs to is the one
    // thing painted at that edge, and it is 4px outside the sheet's own border
    // box. Nothing that reads app.css as text can see any of this.
    //
    // ASSERTED AS THE OUTCOME: the settings sheet does not scroll sideways, and
    // the agenda row starts inside it. Re-sizing the margins to 14px, dropping
    // them, or scoping them to `.modal .arch-events` all satisfy it.
    await viewport(390)
    const host = await mount(ARCHIVED_IN_SETTINGS)
    const sheet = box(host.querySelector('.set-sheet')!)
    const body = host.querySelector<HTMLElement>('.set-body')!
    const arch = host.querySelector<HTMLElement>('.arch-events')!
    const row = box(host.querySelector('.agenda-ev')!)

    // Vacuity guard: everything below is a comparison between two numbers off a
    // box, and under a stylesheet that failed to load they are all 0 and all
    // equal. `.arch-events` has a `max-height: 55vh` of its own, so a rendered
    // one is never zero-height.
    expect(box(arch).h, 'the stylesheet did not load; nothing here is measurable')
      .toBeGreaterThan(0)
    expect(sheet.w, 'the viewport did not take').toBe(390)

    expect({
      sidewaysScroll: body.scrollWidth > body.clientWidth + 1,
      rowStartsOutsideTheSheet: row.left < sheet.left,
    }, `the settings sheet scrolls ${body.scrollWidth - body.clientWidth}px sideways `
      + `and the agenda row starts at x=${row.left} against a sheet edge at `
      + `x=${sheet.left}, so its --ev-c colour rule is clipped away`)
      .toEqual({ sidewaysScroll: false, rowStartsOutsideTheSheet: false })
  })

  // CONTROL (passes today, must keep passing). Inside a `.modal` — the parent
  // the margins were written for — the agenda still runs edge to edge. The
  // cheap over-correction is to delete the negative margins outright, which
  // would satisfy the pin and inset the rows in the one place they are supposed
  // to bleed.
  it('still runs edge to edge inside a modal', async () => {
    await viewport(1200)
    const host = await mount(`
      <div class="shell"><div class="modal">
        <div class="arch-events"><div class="arch-day"><div class="agenda-ev">
          <span class="agenda-title">Standup</span>
        </div></div></div>
      </div></div>`)
    const el = host.querySelector<HTMLElement>('.modal')!
    const modal = box(el)
    const arch = box(host.querySelector('.arch-events')!)
    const css = getComputedStyle(el)
    const pad = parseFloat(css.paddingLeft)
    // The PADDING box, not the border box: `.modal` carries a 1px border, so
    // "bleeds to the edge" means the agenda starts where the padding starts —
    // measured, modal border-box left 0, border 1px, `.arch-events` left 1.
    const inside = +(modal.left + parseFloat(css.borderLeftWidth)).toFixed(1)

    expect(pad, 'the modal lost its padding, so this control proves nothing')
      .toBeGreaterThan(0)
    expect(arch.left, 'the agenda no longer bleeds to the modal edge').toBe(inside)
  })
})

// ── the phone-only hover rules ──────────────────────────────────────────────

/** Every `:hover` rule in the loaded stylesheets, with the media conditions it
 *  is nested under.
 *
 *  Read off the CSSOM rather than the file, which is the point of doing it
 *  here: this is the rule set a browser actually built, `@import`s resolved and
 *  nesting flattened, not a regex over source text. */
function hoverRules(): { selector: string; conditions: string[] }[] {
  const out: { selector: string; conditions: string[] }[] = []
  const walk = (rules: CSSRuleList, conditions: string[]) => {
    for (const rule of rules) {
      if (rule instanceof CSSMediaRule) {
        walk(rule.cssRules, [...conditions, rule.conditionText])
        continue
      }
      if (rule instanceof CSSStyleRule && rule.selectorText.includes(':hover')) {
        out.push({ selector: rule.selectorText, conditions })
      }
      if ('cssRules' in rule) walk((rule as CSSGroupingRule).cssRules, conditions)
    }
  }
  for (const sheet of document.styleSheets) {
    try { walk(sheet.cssRules, []) } catch { /* a cross-origin sheet has no rules */ }
  }
  return out
}

describe('2026-08-25 — the phone-only hover rules', () => {
  // ── AUDIT (open): app.css:809 — the mobile-only hover rules on the sidebar
  //    bar leave the "View completed" toggle stuck in its active colour after a
  //    tap ────────────────────────────────────────────────────────────────────
  it('are all guarded by a hover-capability query', async () => {
    // EVIDENCE. `.side-mobile-completed` and `.side-mobile-add` are declared
    // INSIDE `@media (max-width: 720px)` — they exist ONLY on a phone — yet
    // their `:hover` rule is not wrapped in `@media (hover: hover)` and has no
    // `:active` twin. tokens.css:196 states the rule explicitly and applies it
    // to `.btn`/`.icon-btn`; app.css repeats the reasoning at 634 and 1840. On a
    // touchscreen `:hover` LATCHES on tap and persists until something else is
    // tapped — and here the hover colour is byte-identical to the toggle's only
    // active-state marker.
    //
    //   Tap ✓ -> completedActive true, glyph turns --accent (correct).
    //   Tap ✓ again to go back -> `.active` is removed, but `:hover` is still
    //   latched from the tap and paints the identical --accent.
    // The glyph is the button's ONLY visible state (`aria-pressed` is not
    // visual), so the bar says you are still in the completed pane while the
    // list behind it shows open tasks. Same latch on the `+` beside it, where it
    // advertises a New-collection form that is not open.
    //
    // NOT A MEASUREMENT, and deliberately so — this is the one pin in this file
    // that reads the rule set rather than a box, because the defect is a
    // property of a device this harness cannot be: headless Chromium reports
    // `hover: hover` and `pointer: fine`, so `:hover` behaves correctly here and
    // no amount of hovering would reproduce a latch. What CAN be checked, and is
    // exactly what the fix changes, is whether the declaration is fenced off
    // from devices that have no hover. It is checked off the CSSOM — the rules a
    // browser really built — rather than by grepping app.css.
    //
    // SWEPT, not enumerated: any `:hover` inside the phone-only block, not the
    // two selectors the finding names. app.css carries 43 unguarded `:hover`
    // rules against 8 `@media (hover: …)` blocks, and the ones that matter are
    // precisely those that exist only where hover does not. Measured now, the
    // sweep finds exactly ONE and it is the finding's own:
    //   `.side-mobile-add:hover, .side-mobile-completed:hover @ (max-width: 720px)`
    const all = hoverRules()
    // Vacuity guard: an empty sweep passes this pin for the wrong reason, and a
    // stylesheet that failed to load is an empty sweep.
    expect(all.length, 'no :hover rule was found at all — the stylesheets did not load')
      .toBeGreaterThan(20)

    const unguarded = all
      .filter((r) => r.conditions.some((c) => /max-width/.test(c)))
      .filter((r) => !r.conditions.some((c) => /hover/.test(c)))
      .map((r) => `${r.selector} @ ${r.conditions.join(' and ')}`)

    expect(unguarded, 'these rules exist only on a phone, where :hover latches on '
      + 'tap and does not clear until something else is tapped')
      .toEqual([])
  })
})

// ── the Today row's tap targets ─────────────────────────────────────────────

// One ordinary day row and one suggestion row, carrying every button the real
// component puts in a `.today-row`: the tick, the estimate cell, the ✕, and the
// suggestion's +.
const TODAY_ROWS = `
  <div class="shell"><div class="content"><ul class="today-list">
    <li class="today-row">
      <button type="button" class="check" aria-label="Check Water the plants">&#10003;</button>
      <span class="today-title">Water the plants</span>
      <button type="button" class="today-est mono unset" aria-label="Estimate">est</button>
      <button type="button" class="today-drop" aria-label="Remove from today">&#10005;</button>
    </li>
    <li class="today-row today-sug">
      <button type="button" class="today-plus" aria-label="Add to today">+</button>
      <span class="today-title">Send the invoice</span>
    </li>
  </ul></div></div>`

describe('2026-08-25 — the Today row on a phone', () => {
  const TARGET = 44

  /**
   * The size of a control's real TAP TARGET, by hit-testing outward from its
   * centre until the point stops belonging to it.
   *
   * This replaced `box(el)`, and the swap is the point rather than an
   * implementation detail. A border box was only ever a PROXY for the target,
   * and it is the proxy that made the first fix cost what it did: satisfying it
   * meant growing the elements, which grew `.check` — the one control here that
   * paints its box — to a 44px bordered square against the Tasks tab's 21px,
   * and took 145px of a 362px row for four controls, leaving an ordinary task
   * summary 115px to wrap onto three lines in. The guideline never asked for
   * either. It asks for somewhere you can put a thumb.
   *
   * So the tap area is now a transparent, centred `::after`, and this measures
   * what a thumb would actually land on. `elementFromPoint` returns the
   * ORIGINATING element for a point inside its pseudo-element, which is the
   * whole mechanism.
   */
  const hit = (el: HTMLElement) => {
    const b = box(el)
    const cx = b.left + b.w / 2
    const cy = b.top + b.h / 2
    const owns = (x: number, y: number) => document.elementFromPoint(x, y) === el
    // Bounded, so a stylesheet that made something cover the viewport cannot
    // walk this to the edge of the page one pixel at a time.
    let l = cx; let r = cx; let t = cy; let bot = cy
    while (cx - l < 200 && owns(l - 1, cy)) l -= 1
    while (r - cx < 200 && owns(r + 1, cy)) r += 1
    while (cy - t < 200 && owns(cx, t - 1)) t -= 1
    while (bot - cy < 200 && owns(cx, bot + 1)) bot += 1
    return { w: r - l + 1, h: bot - t + 1, left: l, right: r, top: t, bottom: bot }
  }

  // ── AUDIT (open): app.css:1587 — the Today row's ✕, estimate and + are
  //    ~16–19px tap targets on the phone-primary surface ────────────────────
  it(`gives every control a ${TARGET}px tap box`, async () => {
    // EVIDENCE. `.today-drop` (the only way to take a row off the day),
    // `.today-plus` (the only way to accept a suggestion) and `.today-est` are
    // bare glyph buttons at 11–12px with 2px/4px padding and `line-height: 1`.
    // The block directly above them already reasons about touch for this control
    // — `@media (hover: none) { .today-drop { opacity: 1 } }` exists precisely
    // because a hover-revealed ✕ is unreachable on a phone — but only its
    // VISIBILITY was fixed, not its size, and there is no swipe or long-press
    // alternative anywhere on this screen.
    //
    // A sibling finding (closed) got the phone-only rules for these three
    // APPLYING at all: the Today fence declares `padding: 2px 4px` at (0,1,0)
    // some 250 lines below the media block, so their bare form never won, and
    // qualifying them (`button.today-drop`, `.today-est.mono`) is what made
    // `padding: 8px 10px` and `min-height: 34px` real. This finding is what is
    // left after that, and the numbers are no longer the audit's ~16x16.
    // Measured in THIS harness at 390x844, with those rules live:
    //   .check       21   x 21
    //   .today-est   42   x 34
    //   .today-drop  27.2 x 28
    //   .today-plus  29   x 31
    // Every one still short of the guideline, and the tick is the worst of them.
    //
    // 44px is the accessibility guideline rather than the finding's own
    // suggested 40px — a deliberate choice, with an accepted cost: a Today row
    // goes from ~53px to ~62px, so roughly 13 rows fit an 844px phone instead of
    // 16. STAGES.md records the decision.
    //
    // SWEPT over `.today-row button`, not over the three selectors the finding
    // names. The recurring failure in this stylesheet is a guard only as wide as
    // the set it enumerates — the sibling finding above was itself a rule that
    // named three classes and reached none of them — so the tick is included
    // even though the finding does not name it, and a button added to this row
    // later is covered without anyone remembering to add it here.
    //
    // MEASURED BY HIT-TESTING as of the mobile-layout fix — see `hit`. The
    // property is unchanged and the number is unchanged; what changed is that
    // the assertion is now about the target rather than about the border box
    // that used to stand in for it.
    await viewport(390)
    const host = await mount(TODAY_ROWS)
    const buttons = [...host.querySelectorAll<HTMLElement>('.today-row button')]

    // Vacuity guard, two ways: a sweep that matches nothing passes, and so does
    // one over boxes a failed stylesheet left at zero.
    expect(buttons.length, 'the sweep matched no buttons').toBe(4)
    expect(Math.min(...buttons.map((b) => box(b).h)),
      'every box is zero — the stylesheet did not load').toBeGreaterThan(0)

    const small = buttons
      .map((b) => ({ cls: b.className, ...hit(b) }))
      .filter((b) => b.w < TARGET || b.h < TARGET)
      .map((b) => `${b.cls} ${b.w}x${b.h}`)

    expect(small, `under the ${TARGET}px touch guideline on the phone-primary `
      + `surface: ${small.join(', ')}`).toEqual([])
  })

  // The hazard the technique brings, and the one the old measurement could not
  // have caught: a tap area wider than its control can reach across a gap into
  // the next one, and a target you cannot hit without hitting its neighbour is
  // not a 44px target. Measured at 390px, the two adjacent controls with the
  // least room between them — the estimate cell and the ✕ — leave 62px of clear
  // space, and the tick is alone at the left edge.
  it('without any two of those areas overlapping', async () => {
    await viewport(390)
    const host = await mount(TODAY_ROWS)
    const rows = [...host.querySelectorAll('.today-row')]

    const clashes: string[] = []
    for (const row of rows) {
      const areas = [...row.querySelectorAll<HTMLElement>('button')]
        .map((b) => ({ cls: b.className, ...hit(b) }))
        .sort((a, b) => a.left - b.left)
      for (let i = 1; i < areas.length; i++) {
        if (areas[i].left <= areas[i - 1].right) {
          clashes.push(`${areas[i - 1].cls} / ${areas[i].cls}`)
        }
      }
    }
    expect(clashes, 'these tap areas overlap — a thumb aimed at one lands on '
      + `both: ${clashes.join(', ')}`).toEqual([])
  })

  // …and the other half of the same fix: the CONTROLS went back to the size
  // they are drawn at, which is what "the buttons are huge" meant. Measured at
  // 390px before it: `.check` 44x44, the same tick the Tasks tab renders at
  // 21px. After: 21x21, with the 44px target still there and asserted above.
  it('while the tick stays the size the rest of the app draws it', async () => {
    await viewport(390)
    const host = await mount(TODAY_ROWS)
    const check = host.querySelector<HTMLElement>('.check')!
    const size = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--check-size'))

    expect(size, '--check-size did not resolve').toBeGreaterThan(0)
    expect(box(check).w, 'the tick is drawn bigger than --check-size').toBe(size)
    expect(box(check).h, 'the tick is drawn bigger than --check-size').toBe(size)
  })

  // CONTROL (passes today, must keep passing). The glyphs stay small even as
  // their boxes grow: the fix is a tap BOX, not bigger type, and a row of 44px
  // glyphs would be a different screen. Also holds the row's own text at its
  // designed size, which is what a naive `font-size` bump would break.
  it('without growing the glyphs themselves', async () => {
    await viewport(390)
    const host = await mount(TODAY_ROWS)
    const px = (sel: string) => parseFloat(getComputedStyle(host.querySelector(sel)!).fontSize)

    expect(px('.today-drop'), 'the ✕ glyph grew instead of its box')
      .toBeLessThanOrEqual(16)
    expect(px('.today-est'), 'the estimate text grew instead of its box')
      .toBeLessThanOrEqual(16)
    expect(px('.today-title'), 'the row title changed size').toBeLessThanOrEqual(16)
  })
})
