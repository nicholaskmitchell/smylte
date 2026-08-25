// The layout facts no rendering test in this repo can see.
//
// vitest runs with `css: false` and jsdom applies no layout at all, so a broken
// stylesheet is invisible to all 1000-odd tests beside this file — three
// separate phone-only defects shipped green, and the only thing that found them
// was opening the app in Chromium at 390px and measuring. These are the
// structural halves of those fixes: not a substitute for looking, but enough
// that reverting one fails something.
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

/** One `@media (max-width: 720px) { ... }` block's body, by index. The
 *  stylesheet has several; the tab strip lives in the first. */
function mediaBlock(n: number): string {
  const marker = '@media (max-width: 720px)'
  let from = -1
  for (let i = 0; i <= n; i++) from = rules.indexOf(marker, from + 1)
  expect(from, `there is no ${n + 1}th max-width:720px block`).toBeGreaterThan(-1)
  // Brace-match from the block's opening `{`.
  let depth = 0
  const start = rules.indexOf('{', from)
  for (let i = start; i < rules.length; i++) {
    if (rules[i] === '{') depth++
    else if (rules[i] === '}' && --depth === 0) return rules.slice(start, i)
  }
  throw new Error('unbalanced braces in app.css')
}

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
