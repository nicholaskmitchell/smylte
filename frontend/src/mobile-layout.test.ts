// The stylesheet, read as text — the half of the layout story that is cheap.
//
// The `unit` project runs with `css: false` and jsdom applies no layout at all,
// so a broken stylesheet is invisible to all 1100-odd tests beside this file.
// Several phone-only defects shipped green, and the only thing that ever found
// one was opening the app in Chromium at 390px and measuring.
//
// **That measuring is automated now**, in `src/layout.browser.test.tsx` — a
// second vitest project running real Chromium with the real stylesheets in the
// cascade. This file is not obsolete and is not a substitute for it; they answer
// different questions and both are needed:
//
//   * THIS file sweeps the WHOLE sheet cheaply and structurally. Its
//     cascade-shadow check at the foot — nothing declared in a mobile block may
//     be overwritten by a later unconditional rule at the same-or-higher
//     specificity — names all seven dead declarations in one pass, over every
//     selector in 2000 lines, in 50ms and with no browser.
//   * THAT file measures a HANDFUL of load-bearing boxes and is the only thing
//     that can tell you a rule actually won. A model of the cascade is not the
//     cascade: the `.set-panels` percentage-height bug applied the whole time
//     and no amount of reading found it.
//
// So: structural breadth here, measured depth there. Anything asserted here that
// could be measured instead is the weaker of the two — prefer moving it.
//
// Asserted against the FILES on disk rather than through a render, for the
// reason `TodayView.test.tsx`'s stylesheet block gives: jsdom evaluates no
// media query, so the only thing a render could check is the desktop case,
// which was never the broken one.

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8')
const css = read('src/styles/app.css')

/** The stylesheet with comments stripped, so prose describing a rule is never
 *  mistaken for the rule. Every assertion below runs against this. */
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '')

/** The body of the nth block introduced by `marker`, brace-matched.
 *
 *  Brace-matching and not "up to the next `}`" — an at-rule's body is full of
 *  rules with braces of their own, so the naive version returns the first rule
 *  inside the block and every assertion after it is a false negative. */
function blockAfter(marker: string, n = 0): string {
  let from = -1
  for (let i = 0; i <= n; i++) from = rules.indexOf(marker, from + 1)
  expect(from, `there is no block ${n + 1} for \`${marker}\``).toBeGreaterThan(-1)
  let depth = 0
  const start = rules.indexOf('{', from)
  for (let i = start; i < rules.length; i++) {
    if (rules[i] === '{') depth++
    else if (rules[i] === '}' && --depth === 0) return rules.slice(start, i)
  }
  throw new Error('unbalanced braces in app.css')
}

/** One `@media (max-width: 720px)` block's body, by index. The stylesheet has
 *  four; the tab strip lives in the first. */
const mediaBlock = (n: number) => blockAfter('@media (max-width: 720px)', n)

/** The body of the first rule whose selector matches, or ''. */
function ruleFor(selector: string, hay: string = rules): string {
  const re = new RegExp(
    `(^|[,{}])\\s*${selector.replace(/[.[\]()*+?^$|\\]/g, '\\$&')}\\s*\\{([^{}]*)\\}`, 'm')
  return re.exec(hay)?.[2] ?? ''
}

describe('the stylesheet is where these tests think it is', () => {
  it('parses, and the selectors these tests pin still exist', () => {
    // Every assertion below reads a slice of a file. If a selector is renamed
    // the slice comes back empty and the test passes vacuously, which is worse
    // than no test — so the shape is checked once, here.
    expect(css.length).toBeGreaterThan(1000)
    expect(rules).not.toContain('/*')
    for (const sel of ['.topbar', '.tabs', '.tab', '.ev-dot', '.dash-stack', '.task']) {
      expect(rules, `${sel} is gone from app.css`).toContain(sel)
    }
    expect(mediaBlock(0)).toContain('.topbar')
  })
})

describe('the tab strip on a phone', () => {
  // Five tabs plus the brand and the settings button come to 497px against a
  // 390px bar. Nothing scrolled sideways, so the last tab — Scheduling — was
  // clipped off the right edge and could not be reached on a phone at all.
  const block = mediaBlock(0)

  it('scrolls rather than overflowing the bar', () => {
    const tabs = ruleFor('.tabs', block)
    expect(tabs, '.tabs has no mobile rule').not.toBe('')
    expect(tabs).toMatch(/overflow-x:\s*auto/)
  })

  it('lets the strip shrink below its content, which is what makes that work', () => {
    // The load-bearing half. A flex child will not shrink past its content
    // without `min-width: 0`, so without this the strip refuses to narrow and
    // pushes the overflow onto the bar instead — the scroll never engages.
    expect(ruleFor('.tabs', block)).toMatch(/min-width:\s*0/)
  })

  it('gives the slack to the tabs rather than to the spacer beside them', () => {
    // `.spacer { flex: 1 }` globally; if it keeps stretching on a phone it eats
    // the room the strip needs and the scroll is over a nearly-zero width.
    expect(ruleFor('.topbar .spacer', block)).toMatch(/flex:\s*none/)
  })
})

describe("Home's module stack on a phone", () => {
  it('does not let modules shrink to fit the viewport', () => {
    // `.dash-stack` is a flex column inside `.scroll`, which is a FIXED-HEIGHT
    // scroller. A flex child defaults to `flex-shrink: 1`, so five modules
    // taller than the phone were squashed into it rather than overflowing and
    // letting the container scroll — and because a module is `overflow: hidden`
    // over an `overflow-y: auto` body, the squashing read as every module's
    // content being quietly cut off. Measured at 390x844 before the fix: the
    // mini calendar rendered 138px of a 175px body.
    const mod = ruleFor('.dash-stack .dash-mod')
    expect(mod, '.dash-stack .dash-mod is gone').not.toBe('')
    expect(mod).toMatch(/flex:\s*none|flex-shrink:\s*0/)
  })

  it('still caps a single very tall module', () => {
    // Not shrinking is not the same as growing without limit: one enormous
    // module should not push everything else off the screen.
    expect(ruleFor('.dash-stack .dash-mod')).toMatch(/max-height:/)
  })
})

describe('the calendar month grid', () => {
  it('floors its columns at zero so one long chip cannot widen a weekday', () => {
    // `1fr` is `minmax(auto, 1fr)`, and `auto` will not shrink a track below its
    // content's min-content width. A chip is `white-space: nowrap`, so a single
    // long title widened its weekday for the whole month and squeezed the rest:
    // measured on the shipped default at 721px, the seven columns ran 37.4 to
    // 157.7 and the grid scrolled 208px sideways.
    //
    // The rule existed already — under `.cal-scroll.fixed`, which needs
    // `fit === 'fixed'` while the shipped default is `dynamic`, so it reached
    // almost nobody. This pins it on the BASE rule, where every month grid gets
    // it.
    const grid = ruleFor('.cal-grid')
    expect(grid, '.cal-grid is gone from app.css').not.toBe('')
    expect(grid, 'a bare 1fr track floors at min-content and overflows')
      .toMatch(/grid-template-columns:\s*repeat\(7,\s*minmax\(0,\s*1fr\)\)/)
  })

  it('does not leave the floor only on the fitted variant', () => {
    // The vacuity guard for the test above: if the declaration moved back under
    // `.cal-scroll.fixed` the base rule would fail, but a copy left in both
    // would pass while the base one was deleted. This says the base rule is the
    // one carrying it.
    const fixed = ruleFor('.cal-scroll.fixed .cal-grid')
    expect(fixed, '.cal-scroll.fixed .cal-grid is gone').not.toBe('')
    expect(fixed, 'the column floor drifted back onto the fitted variant only')
      .not.toMatch(/grid-template-columns:/)
  })
})

describe('the multi-day task columns', () => {
  it('floors a day column at a width a title can wrap in', () => {
    // `1fr` alone let seven columns divide whatever was there: at 721px a Week
    // column was 69px, and after the body's padding, the card's padding, the
    // priority bar and the checkbox, `.day-card-title` was left 2px — so
    // `overflow-wrap: break-word` broke the title ONE CHARACTER PER LINE, 16
    // lines tall. It was still four lines at 1000px.
    for (const sel of ['.day-cols.cols-3', '.day-cols.cols-7']) {
      const body = ruleFor(sel)
      expect(body, `${sel} is gone from app.css`).not.toBe('')
      expect(body, `${sel} lets a column shrink to nothing`)
        .toMatch(/grid-template-columns:\s*repeat\(\d,\s*minmax\(\d+px,\s*1fr\)\)/)
    }
  })

  it('scrolls the row rather than squeezing past the floor', () => {
    // A floor without a scroller just moves the overflow somewhere else. The
    // phone rule one block down already answers this the same way.
    expect(ruleFor('.day-cols.cols-3, .day-cols.cols-7')).toMatch(/overflow-x:\s*auto/)
  })

  it('does not wrap a second vertical scroller around the seven that have one', () => {
    // `.day-col-body` is the vertical scroller. Setting only `overflow-x`
    // computes `overflow-y` to `auto` as well, which would nest one.
    expect(ruleFor('.day-cols.cols-3, .day-cols.cols-7')).toMatch(/overflow-y:\s*hidden/)
  })
})

describe('classes the JSX writes that the stylesheet must answer', () => {
  // The defect family `.today-shutdown` belonged to: a class name invented in a
  // component that `app.css` never defines, so the element silently renders
  // with no styling at all. There is exactly one stylesheet, so this is always
  // a silent failure rather than a build error.

  it('styles the scheduling availability error as an error', () => {
    // It had no rule, so an inline error rendered as ordinary 15px body prose —
    // indistinguishable from the label beside it.
    const err = ruleFor('.sched-err')
    expect(err, '.sched-err is written into SchedulingView but has no rule').not.toBe('')
    expect(err, 'an error that is not warn-coloured does not read as one')
      .toMatch(/color:\s*var\(--warn\)/)
    expect(read('src/components/SchedulingView.tsx')).toContain('sched-err')
  })

  it('lets a time range give way instead of pushing the sheet sideways', () => {
    // A flex item defaults to `min-width: auto` and will not shrink below its
    // content. These hold two `input[type=time]` floored at 16px on mobile to
    // stop iOS zooming on focus, so at 360px the pair came to 275px inside a
    // 248px row and the whole modal scrolled sideways.
    expect(ruleFor('.sched-range')).toMatch(/min-width:\s*0/)
    expect(ruleFor('.sched-range .input')).toMatch(/min-width:\s*0/)
  })
})

describe('hover-revealed controls on a touch device', () => {
  it('restores all three clusters, not two of them', () => {
    // `.group-actions` is `opacity: 0` until `.group-head:hover`, which never
    // arrives on a finger — so renaming or deleting a list group was unreachable
    // on any touch device wide enough not to get the sidebar drawer. Its two
    // siblings were already restored here; it was not.
    const block = blockAfter('@media (hover: none)')
    expect(block, 'the hover:none block parsed empty').not.toBe('')
    for (const sel of ['.task-actions', '.side-item .side-edit', '.group-actions']) {
      expect(block, `${sel} is not restored on touch`).toContain(sel)
    }
  })
})

describe('the Settings sheet on a phone', () => {
  const block = mediaBlock(0)

  it('scrolls at the level that actually has a constrained height', () => {
    // `.set-panels` carried `height: 100%; overflow-y: auto`, which looks like
    // it should do this and does not: `.set-body` has no SPECIFIED height — its
    // 500px comes out of flex layout — so the percentage had nothing definite to
    // resolve against and fell back to `auto`, the content height. The panel
    // sized itself to 1084px inside a 500px `overflow: hidden` parent and 584
    // PIXELS OF SETTINGS WERE UNREACHABLE: "Working day" (the whole day-capacity
    // section) and "Time zone" sat below the fold with nothing to scroll them.
    const body = ruleFor('.set-sheet .set-body', block)
    expect(body, '.set-sheet .set-body has no mobile rule').not.toBe('')
    expect(body, 'the sheet body clips its content again').toMatch(/overflow-y:\s*auto/)
    expect(body, 'overflow:hidden is exactly what made the sections unreachable')
      .not.toMatch(/overflow:\s*hidden/)
  })

  it('does not nest a second scroller inside that one', () => {
    // A scroller inside a scroller traps the gesture at the inner one and leaves
    // the same sections unreachable by a different route.
    const panels = ruleFor('.set-sheet .set-panels', block)
    expect(panels).not.toMatch(/overflow-y:\s*auto/)
    expect(panels, 'the percentage height that never resolved is back')
      .not.toMatch(/height:\s*100%/)
  })

  it('leaves the desktop sheet scrolling where it always did', () => {
    // The base rule is untouched: on a wide screen `.set-body` is a flex row of
    // nav + panels and the PANEL is the scroller. Only the phone sheet moves it.
    expect(ruleFor('.set-panels')).toMatch(/overflow-y:\s*auto/)
  })
})

describe('the word-bearing buttons in the Today header', () => {
  // `.content-head` aligns its children on the BASELINE, so a button holding a
  // word hangs off the title's baseline and sits proud of everything beside it
  // unless it opts out — which is why two of these three carry a rule saying so
  // in as many words. The third, `.today-shutdown`, shipped with no rule at all
  // and sat 2.5px low (top 77 against 74.5) with a shrinkable flex.
  //
  // Pinned as a SET rather than one by one: the failure mode is adding a fourth
  // button and not knowing this rule exists, and a test naming only the three
  // that exist today would not catch that either — but it does catch a rule
  // being dropped, and it puts the reason somewhere a grep will find it.
  const HEADER_BUTTONS = ['.today-review', '.today-habits-open', '.today-shutdown']

  it('all opt out of baseline alignment and of shrinking', () => {
    for (const sel of HEADER_BUTTONS) {
      const body = ruleFor(sel)
      expect(body, `${sel} has no rule in app.css`).not.toBe('')
      expect(body, `${sel} would sit proud of its siblings`).toMatch(/align-self:\s*center/)
      expect(body, `${sel} can be shrunk by its neighbours`).toMatch(/flex:\s*none/)
    }
  })

  it('and none of them adds its own margin, so the row spaces them evenly', () => {
    // `.content-head` sets `gap: 12px`. `.today-habits-open` also carried
    // `margin-left: 10px` — correct when it was added, where it was an
    // `.icon-btn` holding a bare glyph and the ONLY button in this header, and
    // the margin held it off the counts text. Review and Shut down were added in
    // front of it later without one, so the row read 12px, 12px, 22px: two
    // buttons at the container's gap and the third pushed out past both.
    //
    // Below 720px `.content-head` wraps, and there the same 10px indented the
    // Habits row 10px right of every other left edge in the header — measured in
    // Chromium at 390px, its wrapped row started at x=24 against a 14px gutter.
    for (const sel of HEADER_BUTTONS) {
      expect(ruleFor(sel), `${sel} adds its own margin; the container's gap is `
        + 'what makes these three read as one group').not.toMatch(/margin(-left|-right|-inline[a-z-]*)?:/)
    }
  })

  it('is the full set of them that TodayView renders', () => {
    // The vacuity guard: if a button is renamed the loop above still passes
    // against two stale selectors. This checks the header actually renders each
    // one, so a rename fails here instead of quietly narrowing the test.
    const src = read('src/components/TodayView.tsx')
    for (const sel of HEADER_BUTTONS) {
      expect(src, `${sel} is no longer rendered`).toContain(sel.slice(1))
    }
  })
})

describe('the calendar day-dot does not wear the tasks pane\'s row rule', () => {
  // `.task` is a GLOBAL rule — the Tasks pane's row: `display: flex`, a border,
  // and `padding: var(--row-y) var(--gutter)`. A 5px dot given `task` as a
  // modifier inherited 11px/14px of padding and rendered as a 28x23 SLAB beside
  // the day number. This has now shipped TWICE: once on `TodayView`'s kind mark
  // and once here, which is why it is pinned rather than just fixed.

  it('styles the task dot by data attribute, not by a bare class', () => {
    expect(rules).toMatch(/\.ev-dot\[data-kind="task"\]/)
    expect(rules, 'the colliding `.ev-dot.task` selector is back')
      .not.toMatch(/\.ev-dot\.task\b/)
  })

  it('renders it with the attribute and without the class', () => {
    const src = read('src/components/CalendarView.tsx')
    expect(src).toMatch(/data-kind="task"/)
    expect(src, 'the calendar dot is wearing a bare `task` class again')
      .not.toMatch(/className="ev-dot task"/)
  })

  it('leaves `task` as a class to the Tasks pane alone', () => {
    // The generalisation, and the thing that would have caught the calendar
    // regression before it shipped: `.task` carries layout, so any OTHER
    // component using it as a modifier silently inherits a table row's padding.
    // Scans real className values, literal tokens only — an interpolated
    // `${kind}` is the shape that caused both incidents, and there is currently
    // none that can resolve to "task" (checked: `priClass` is pri-*, and
    // DayPopover's is `agenda-task`, which is scoped).
    const files = ['src/App.tsx', 'src/components/CalendarView.tsx',
      'src/components/TodayView.tsx', 'src/components/HomeView.tsx',
      'src/components/DayPopover.tsx', 'src/components/Sidebar.tsx',
      'src/components/SchedulingView.tsx']
    for (const f of files) {
      let src: string
      try { src = read(f) } catch { continue }
      const classAttrs = [...src.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)]
        .map((m) => (m[1] ?? m[2] ?? '').replace(/\$\{[^}]*\}/g, ' \u2022 '))
      for (const attr of classAttrs) {
        expect(attr.split(/\s+/), `${f} puts a bare \`task\` class on an element`)
          .not.toContain('task')
      }
    }
  })
})

// ── the four phone defects the 2026-08-25 sweep found ──────────────────────

/** EVERY `@media (max-width: 720px)` body, joined. The stylesheet has four and
 *  the rules below live in more than one of them, so pinning against a single
 *  index would pass or fail on where a rule happens to sit rather than on
 *  whether it exists. */
const allMobile = (() => {
  const parts: string[] = []
  for (let i = 0; ; i++) {
    try { parts.push(mediaBlock(i)) } catch { break }
    if (parts.length > 12) break
  }
  return parts.join('\n')
})()

describe('the iOS 16px floor covers every control that carries .input', () => {
  it('no later rule sets a sub-16px font-size on an .input consumer', () => {
    // `.input`'s mobile floor exists to stop Safari zooming when a control under
    // 16px takes focus — and once it zooms it does not zoom back, so every later
    // tap lands offset from what the user sees. Three later rules beat it on
    // source order at equal specificity, which is the THIRD time this exact
    // regression has shipped: `.bulk-row .input`, `.sched-range .input` and
    // `.appear-text` each carry a restoring rule and a comment saying why.
    //
    // `.today-est-input` was the worst of the three: it is `autoFocus`, so
    // tapping a row's `est` cell zoomed the page with no tap on the field.
    for (const sel of ['.shut-date', '.shut-reflect', '.today-est-input']) {
      // Matched inside the joined mobile bodies rather than by exact selector,
      // because the restoring rule groups all three.
      const re = new RegExp(`${sel.replace('.', '\\.')}[^{}]*\\{[^{}]*max\\(\\s*16px`)
      expect(allMobile, `${sel} has no mobile font-size floor`).toMatch(re)
    }
  })
})

describe('a foreign-authored title cannot scroll the pane sideways', () => {
  it('every title that renders a foreign SUMMARY can break a long token', () => {
    // A pasted URL is one token with no soft wrap opportunity. Both scrollers
    // these land in declare only `overflow-y: auto`, and per CSS Overflow that
    // computes `overflow-x` to `auto` too — so the overflow becomes sideways
    // scrolling of the whole pane, dragging the month grid off screen with it.
    for (const sel of ['.task-title', '.today-title', '.agenda-ev']) {
      expect(ruleFor(sel), `${sel} has no wrap guard`).toMatch(/overflow-wrap:\s*(anywhere|break-word)/)
    }
  })
})

describe('the Home stack keeps its home-indicator inset', () => {
  it('.dash-stack carries safe-area-inset-bottom itself', () => {
    // It is phone-only, and its `padding` shorthand outranks the mobile
    // `.scroll` rule on source order — so it has to carry the inset rather than
    // defer to a rule it beats. Home was the one tab whose last module sat under
    // the pill with no further scroll to lift it.
    expect(ruleFor('.dash-stack')).toMatch(/padding:[^;]*env\(safe-area-inset-bottom\)/)
  })
})

describe('the phone-primary controls meet the touch standard this file set', () => {
  it('Today rows, the settings toggles and the mini calendar are grown on mobile', () => {
    // The mobile block already grows `.task-actions button` and the drawer's
    // group buttons for exactly this reason. These were left at mouse sizes:
    // the Today row controls at ~18x16 (and `.today-drop` has its own
    // `@media (hover: none)` rule making it permanently visible on touch, i.e.
    // it is meant to be tapped), `.menu-toggle` — every settings control on the
    // phone sheet — at ~27px tall, and the mini calendar's day button at ~21px.
    const padY = (body: string) => {
      const m = /padding:\s*(\d+)px/.exec(body)
      return m ? Number(m[1]) : 0
    }
    //
    // The Today three are QUALIFIED — `button.today-drop`, `.today-est.mono` —
    // and that is not incidental: at a bare `.today-drop` this test passed while
    // the rule it checks never applied, because the Today fence re-declares the
    // same property 250 lines later at the same specificity. Measured in
    // Chromium at 390px, the box was 15x16 with this test green. The cascade
    // describe block at the end of this file is what closes that gap; these
    // selectors are written the way they are so it stays closed.
    for (const sel of ['button.today-drop, button.today-plus', '.today-est.mono',
      '.menu-toggle', '.mini-day']) {
      const body = ruleFor(sel, allMobile)
      expect(body, `${sel} has no mobile touch rule`).not.toBe('')
      expect(padY(body), `${sel} is still mouse-sized on a phone`).toBeGreaterThanOrEqual(8)
    }
    // The rename and delete-group controls were one pixel apart.
    // Two rules share this selector inside the mobile bodies (one restores
    // opacity on touch), so match the declaration rather than the first rule.
    expect(allMobile).toMatch(/\.side\.drawer \.group-actions\s*\{[^{}]*gap:\s*(?:[4-9]|\d\d)px/)
  })
})

describe('every custom property a rule reads is actually defined', () => {
  it('no rule references a var() no token file declares', () => {
    // `.cal-partial` said `border-bottom: 1px solid var(--line)`, and `--line` is
    // declared in no theme, no token file, and not in appearance.ts's token
    // table — so the declaration was invalid at computed-value time, the
    // shorthand's longhands fell back to `unset`, `border-bottom-style` became
    // `none`, and the partial-month banner had no bottom rule at all. Nothing
    // could ever have supplied it.
    const tokens = read('src/styles/tokens.css')
    const declared = new Set<string>()
    for (const m of (tokens + css).matchAll(/(--[a-z0-9-]+)\s*:/gi)) declared.add(m[1])
    // Locally-scoped fallbacks a rule sets on itself count as declared above.
    const missing = new Set<string>()
    for (const m of rules.matchAll(/var\(\s*(--[a-z0-9-]+)\s*([,)])/gi)) {
      // `var(--x, fallback)` is fine undeclared — the fallback is the value.
      if (m[2] === ')' && !declared.has(m[1])) missing.add(m[1])
    }
    expect([...missing].sort(),
      'these custom properties are read but never declared').toEqual([])
  })
})

describe('the phone gets the whole unsafe area accounted for', () => {
  it('the horizontal safe-area insets are read somewhere', () => {
    // index.html opts into `viewport-fit=cover`, and the VERTICAL insets are
    // honoured in several places — but the horizontal ones were read nowhere.
    // In landscape on a notched iPhone the notch is on the left or the right,
    // so the sidebar rail, the tab strip and every row's first column sat under
    // it. `env()` is 0 without an inset, so honouring it costs nothing else.
    expect(read('../frontend/index.html') || read('index.html')).toMatch(/viewport-fit=cover/)
    expect(rules).toMatch(/env\(safe-area-inset-left\)/)
    expect(rules).toMatch(/env\(safe-area-inset-right\)/)
  })

  it('the toast clears the home indicator', () => {
    // `.shell` is 100dvh under viewport-fit=cover, so a flat `bottom: 24px` put
    // the app's only error channel inside the home-indicator band.
    expect(ruleFor('.toast')).toMatch(/bottom:\s*calc\([^)]*env\(safe-area-inset-bottom\)/)
  })

  it('the content gutter is a token the mobile block re-declares', () => {
    // The mobile block used to narrow the gutter by naming selectors one at a
    // time, so the Today-tab fence — added later, and resolving var(--gutter)
    // everywhere — kept the 26px desktop value on a phone. The result was a 12px
    // stair-step between every section label and the rows under it. The token is
    // re-declared now, the way `--check-size` in this same block already is, so
    // a tab added tomorrow inherits it.
    expect(allMobile).toMatch(/:root[^{}]*\{[^{}]*--gutter:\s*14px/)
  })

  it('and the re-declaration outranks a preset, which is more specific than :root', () => {
    // The half a bare `:root { --gutter: 14px }` gets wrong. A preset is a whole
    // alternative design and declares its own gutter as
    // `:root[data-preset="workspace"]` — (0,2,0), against a bare `:root`'s
    // (0,1,0) — so the mobile re-declaration LOSES to it and every preset user
    // stays on the desktop gutter, which is the whole finding again for them.
    // Matching the attribute selector ties the specificity, and app.css is
    // imported after tokens.css, so source order settles it.
    const decl = allMobile.match(/([^{}]*)\{[^{}]*--gutter:\s*14px/)
    expect(decl, 'the mobile gutter re-declaration is gone').not.toBeNull()
    expect(decl![1], 'a preset declares --gutter with an attribute selector, so a '
      + 'bare :root here is outranked and every preset user keeps the desktop gutter')
      .toMatch(/:root\[data-preset\]/)
    expect(read('src/styles/tokens.css'),
      'no preset declares --gutter any more — if that is deliberate, this test '
      + 'and the selector it guards can both be simplified')
      .toMatch(/:root\[data-preset[^\]]*\][^{}]*\{[\s\S]*?--gutter:/)
  })

  it('no longer narrows the gutter selector by selector as well', () => {
    // Keeping the old hand-maintained list beside the token is not belt and
    // braces, it is the stair-step pointing the other way: a user who sets a
    // 40px gutter in the Appearance editor writes it as an INLINE property on
    // <html>, which beats every stylesheet rule — so `.today-row` would honour
    // their 40px while a literal `.task { padding-left: 14px }` forced 14px on
    // the row above it.
    expect(allMobile, 'the hand-maintained gutter list is back beside the token')
      .not.toMatch(/\.task,\s*\.quickadd[^{}]*\{[^{}]*padding-left:\s*14px/)
  })
})

// ── the cascade, which is how three of these fixes died ────────────────────
//
// Every assertion above this point checks that a DECLARATION EXISTS in a mobile
// block. None of them checks that it WINS, and four times now it has not: the
// iOS 16px floor (twice), the Appearance editor's colour field, and — measured
// in Chromium at 390px on the commit before this one — the Today tab's touch
// targets AND the floor's own third attempt. `.shut-date` computed to 11px,
// `.today-est-input` to 11px, `.shut-reflect` to 14px and `.today-drop` to a
// 15x16 box, each with the rule meant to fix it sitting in the sheet.
//
// The mechanism is always the same. A mobile block declares `.x { p: v }` at
// (0,1,0); a fence added later in the file declares `.x { p: w }` at the same
// specificity; later wins at equal specificity regardless of the media query.
// The comment above the floor says exactly this, about the rules it was written
// to beat, and then loses to them in the same way.
//
// So this is the check that generalises: nothing declared inside a
// `max-width: 720px` block may be shadowed by a later unconditional rule for the
// same selector at the same-or-higher specificity.

/** Every declaration in the sheet as {selector, property, offset, media}. */
function declarations(src: string) {
  const out: { sel: string; prop: string; at: number; media: string | null }[] = []
  let i = 0, media: string | null = null, mediaEnd = -1
  while (i < src.length) {
    const at = src.indexOf('@media', i)
    const brace = src.indexOf('{', i)
    if (brace === -1) break
    if (at !== -1 && at < brace) {
      // Descend into the at-rule rather than treating its body as one rule.
      const open = src.indexOf('{', at)
      let d = 0, j = open
      for (; j < src.length; j++) {
        if (src[j] === '{') d++
        else if (src[j] === '}' && --d === 0) break
      }
      media = src.slice(at, open).trim()
      mediaEnd = j
      i = open + 1
      continue
    }
    if (media && brace > mediaEnd) media = null
    const sel = src.slice(i, brace).split('}').pop()!.trim()
    const close = src.indexOf('}', brace)
    if (close === -1) break
    if (sel && !sel.startsWith('@')) {
      for (const one of sel.split(',').map((x) => x.trim()).filter(Boolean)) {
        for (const d of src.slice(brace + 1, close).split(';')) {
          const prop = d.split(':')[0].trim()
          if (prop) out.push({ sel: one, prop, at: brace, media: brace < mediaEnd ? media : null })
        }
      }
    }
    i = close + 1
  }
  return out
}

/** Specificity as a single comparable number. Good enough for this sheet, which
 *  uses no ids and no `:where()`. */
function specificity(sel: string): number {
  const cls = (sel.match(/\.[\w-]+|\[[^\]]+\]|:[a-z-]+(\([^)]*\))?/g) || []).length
  const el = (sel.replace(/[.#:[][^\s>+~]*/g, '').match(/\b[a-z]+\b/g) || []).length
  return cls * 100 + el
}

/** Does a declaration of `a` get overwritten by one of `b`? Shorthands count. */
const SHORTHAND: Record<string, string[]> = {
  padding: ['padding-left', 'padding-right', 'padding-top', 'padding-bottom'],
  margin: ['margin-left', 'margin-right', 'margin-top', 'margin-bottom'],
  font: ['font-size', 'font-family', 'font-weight', 'line-height'],
  inset: ['top', 'right', 'bottom', 'left'],
}
const overwrites = (a: string, b: string) =>
  a === b || (SHORTHAND[a] || []).includes(b) || (SHORTHAND[b] || []).includes(a)

describe('a mobile rule that loses the cascade is the same as no rule', () => {
  const decls = declarations(rules)

  it('finds the declarations it is about to judge', () => {
    // The vacuity guard. A parser that returns nothing passes the next test
    // whatever the stylesheet says.
    const mobile = decls.filter((d) => d.media && /max-width:\s*720px/.test(d.media))
    expect(mobile.length, 'no declarations found inside a mobile block').toBeGreaterThan(60)
    expect(decls.length).toBeGreaterThan(400)
  })

  it('nothing in a mobile block is overwritten by a later unconditional rule', () => {
    const dead: string[] = []
    for (const m of decls.filter((d) => d.media && /max-width:\s*720px/.test(d.media))) {
      const killer = decls.find((l) =>
        !l.media && l.at > m.at && l.sel === m.sel
        && overwrites(m.prop, l.prop) && specificity(l.sel) >= specificity(m.sel))
      if (killer) dead.push(`${m.sel} { ${m.prop} } — beaten by the later \`${killer.prop}\``)
    }
    expect(dead, `these mobile declarations never apply:\n  ${dead.join('\n  ')}\n`
      + 'A later rule at the same specificity wins whatever the media query says. '
      + 'Qualify the mobile selector (`.input.shut-date`, `button.today-drop`) so it '
      + 'outranks the fence, rather than relying on which block comes last.')
      .toEqual([])
  })
})

// ── a bordered variant and an unbordered base are two different boxes ───────

describe('a solid button boxes the same as the ghost beside it', () => {
  const tokens = read('src/styles/tokens.css').replace(/\/\*[\s\S]*?\*\//g, '')
  const btn = ruleFor('.btn', tokens)
  const ghost = ruleFor('.btn.ghost', tokens)

  it('reads both rules', () => {
    expect(btn, '.btn is gone from tokens.css').not.toBe('')
    expect(ghost, '.btn.ghost is gone from tokens.css').not.toBe('')
    expect(ghost).toMatch(/border:\s*1px/)
  })

  it('.btn reserves the border width its variants add', () => {
    // `.btn { border: 0 }` with `.btn.ghost { border: 1px solid … }` and the same
    // padding on both makes the ghost 2px taller and 2px wider. In a row of one
    // of each — every modal in this app: Cancel/Save, Back/Shut down — the flex
    // centring then put the SOLID one 1px lower with its cap-height 1px off its
    // neighbour. Measured in Chromium before the fix: Back 57.1x33 at y=4,
    // Shut down 91.5x31 at y=5, adjacent in the shutdown ritual's action row.
    //
    // `box-sizing: border-box` in this same file does not cover it — that
    // governs elements with a specified width or height, and a button has
    // neither, so auto height is content + padding + border either way. The
    // border has to be RESERVED, transparent, so both boxes agree.
    expect(btn, '.btn declares `border: 0`, so every .btn.ghost beside it is 2px '
      + 'taller and 2px wider and the solid one sits 1px low')
      .not.toMatch(/border:\s*0/)
    expect(btn, '.btn must reserve a 1px border for .ghost and .danger to colour')
      .toMatch(/border:\s*1px solid transparent/)
  })

  it('and .btn.danger therefore has a border to colour', () => {
    // `.btn.danger { border-color: var(--warn) }` sets a colour for a border
    // that, over `border: 0`, had no width — so Settings → Account's Disconnect,
    // the only control that revokes a live MCP OAuth grant, rendered as bare red
    // text with no outline and no background in a row of bordered controls.
    const danger = ruleFor('.btn.danger', rules)
    expect(danger, '.btn.danger is gone from app.css').not.toBe('')
    expect(danger, 'this rule sets border-color only, so it depends on .btn '
      + 'supplying the width').toMatch(/border-color:/)
    expect(danger, 'if .btn.danger declares its own border-width this test is '
      + 'no longer the thing keeping it visible').not.toMatch(/border(-width)?:\s*\d/)
  })
})
