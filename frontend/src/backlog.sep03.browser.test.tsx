/**
 * The 2026-09-03 sweep: the stylesheet findings only a real cascade can see.
 *
 * Six findings, all in `app.css`, and every one of them a question about a
 * computed value rather than about text in a file: a contrast ratio after the
 * browser has composited an `opacity` over a translucent token; a `.modal`'s
 * height against a viewport that is wider than the phone breakpoint but shorter
 * than the form; a `.scroll` whose scrollWidth a 200-character token widens; the
 * Focus surface at a landscape phone's height; a `<select>`'s computed font-size
 * at 390px. `layout.browser.test.tsx`'s header is the argument for measuring
 * these here rather than reading for them: this repo has shipped four mobile
 * rules dead, each one green in every text-level test beside it.
 *
 * Same harness as the two files before it — raw markup class-for-class from the
 * JSX, the real stylesheets in `main.tsx`'s order, real media queries, real
 * fonts, real `getBoundingClientRect()`. The one addition is `declaring()`, which
 * asks the CSSOM (not a regex) which rules currently match an element and set a
 * property. `env(safe-area-inset-*)` is 0 in headless Chromium, so an inset
 * cannot be measured as a box; it CAN be measured as "the only padding-bottom
 * declaration this element matches carries the inset", which is a cascade fact
 * the browser answers and a regex cannot.
 *
 * Every assertion carries the number it measured red, against the commit before
 * the fix, in the comment above it.
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

// ── helpers ─────────────────────────────────────────────────────────────────

/** Every currently-matching rule that declares `prop` (or its shorthand) for
 *  `el`, as `selector { prop: value }`. Media rules are walked only when the
 *  viewport matches them, so this is the set the cascade is choosing from right
 *  now. An empty list means no rule sets the property at all. */
function declaring(el: Element, prop: string): string[] {
  const short = prop.split('-')[0]
  const out: string[] = []
  const walk = (list: CSSRuleList) => {
    for (const r of Array.from(list)) {
      if (r instanceof CSSMediaRule) {
        if (matchMedia(r.conditionText).matches) walk(r.cssRules)
        continue
      }
      if (r instanceof CSSSupportsRule) { walk(r.cssRules); continue }
      if (!(r instanceof CSSStyleRule)) continue
      let hit = false
      try { hit = el.matches(r.selectorText) } catch { continue }
      if (!hit) continue
      const v = r.style.getPropertyValue(prop) || r.style.getPropertyValue(short)
      if (v) out.push(`${r.selectorText} { ${prop}: ${v} }`)
    }
  }
  for (const s of Array.from(document.styleSheets)) {
    try { walk(s.cssRules) } catch { /* a cross-origin sheet; none here */ }
  }
  return out
}

type RGBA = { r: number; g: number; b: number; a: number }
const rgba = (s: string): RGBA => {
  const m = /rgba?\(([^)]+)\)/.exec(s)
  if (!m) throw new Error(`not an rgb() colour: ${s}`)
  const [r, g, b, a = '1'] = m[1].split(/[\s,/]+/).filter(Boolean)
  return { r: +r, g: +g, b: +b, a: +a }
}
/** `fg` over `bg`, sRGB source-over. */
const over = (fg: RGBA, bg: RGBA): RGBA => ({
  r: fg.r * fg.a + bg.r * (1 - fg.a),
  g: fg.g * fg.a + bg.g * (1 - fg.a),
  b: fg.b * fg.a + bg.b * (1 - fg.a),
  a: 1,
})
const lin = (c: number) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }
const luminance = (c: RGBA) => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b)
const ratio = (a: RGBA, b: RGBA) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** `a` blended over `b` at group opacity `o` — what `opacity: o` on an element
 *  does to everything it paints, its own background included. */
const mix = (a: RGBA, b: RGBA, o: number): RGBA => ({
  r: a.r * o + b.r * (1 - o), g: a.g * o + b.g * (1 - o), b: a.b * o + b.b * (1 - o), a: 1,
})

/** The WCAG contrast of `el`'s text as it is actually painted. `opacity` is a
 *  GROUP operation: an element's background and its descendants are rendered
 *  together and then blended over what is behind the element. So this walks
 *  down from the canvas laying each ancestor's background inside its parent's
 *  group, paints the text at the bottom, and blends each group back out on the
 *  way up — text and backdrop through the same multipliers, which is exactly
 *  how a `.sched-card.off { opacity: 0.6 }` drags its own toggle to 1.9:1
 *  while every token in it still reads 3:1 on paper. */
function paintedContrast(el: Element): number {
  const chain: Element[] = []
  for (let n: Element | null = el; n; n = n.parentElement) chain.push(n)
  const canvas: RGBA = { r: 255, g: 255, b: 255, a: 1 }
  // inner[i]: the colour el's content at level i is painted over, before any
  // group blending at that level or above.
  const inner: RGBA[] = new Array(chain.length + 1)
  inner[chain.length] = canvas
  for (let i = chain.length - 1; i >= 0; i--) {
    inner[i] = over(rgba(getComputedStyle(chain[i]).backgroundColor), inner[i + 1])
  }
  let text = over(rgba(getComputedStyle(el).color), inner[0])
  let bg = inner[0]
  for (let i = 0; i < chain.length; i++) {
    const o = parseFloat(getComputedStyle(chain[i]).opacity)
    if (o < 1) { text = mix(text, inner[i + 1], o); bg = mix(bg, inner[i + 1], o) }
  }
  return +ratio(text, bg).toFixed(2)
}

const midpoint = (el: Element) => {
  const r = el.getBoundingClientRect()
  return [r.left + r.width / 2, r.top + r.height / 2] as const
}
const hits = (el: Element) => {
  const [x, y] = midpoint(el)
  const at = document.elementFromPoint(x, y)
  return !!at && (at === el || el.contains(at))
}

// ── #4 opacity multipliers on translucent tokens ────────────────────────────

// Each fixture is the surface class-for-class from the JSX, down to the element
// that paints the opaque backdrop the token was measured against: a booking
// link's card on `.sched-list` (SchedulingView.tsx:172), the display editor's
// picks inside the desktop `.menu.settings-menu` (DisplaysSection.tsx:356 in
// SettingsMenu.tsx:444), a hidden calendar's row on the `--paper` rail
// (Sidebar.tsx:290), and the Home mini calendar's day button (HomeView.tsx:692)
// in its `.dash-mod`.
const DIMMED_CONTROLS = `
  <div class="shell">
    <div class="topbar"><div class="menu settings-menu" data-view="panel">
      <div class="set-body"><div class="set-panels"><div class="set-panel">
        <div class="disp-picks">
          <button type="button" class="chip" aria-pressed="false">Family</button>
          <button type="button" class="chip is-on" aria-pressed="true">Work</button>
        </div>
      </div></div></div>
    </div></div>
    <div class="work">
      <div class="side"><div class="side-list">
        <div class="side-item cal-hidden" role="checkbox" aria-checked="false" tabindex="0">
          <span class="swatch"></span><span class="name">Family</span><span class="count">4</span>
        </div>
      </div></div>
      <div class="content"><div class="scroll">
        <div class="sched-list">
          <div class="sched-card off">
            <div class="sched-card-head">
              <span class="sched-card-title">Intro call</span>
              <label class="sched-toggle"><input type="checkbox" /><span>Off</span></label>
            </div>
            <div class="sched-card-meta">30 min · Work · Europe/Berlin</div>
            <div class="sched-card-meta">3 booked · <span class="mono">/book/abc</span></div>
            <div class="sched-card-actions">
              <button class="btn ghost">Copy link</button>
              <button class="btn ghost">Edit</button>
            </div>
          </div>
        </div>
        <div class="dash-grid"><div class="dash-mod" style="position: static"><div class="mini-cal">
          <div class="mini-cal-grid">
            <button type="button" class="mini-day dim busy" aria-haspopup="dialog">31</button>
            <button type="button" class="mini-day">1</button>
          </div>
        </div></div></div>
      </div></div>
    </div>
  </div>`

describe('2026-09-03 — a dimmed subtree still clears 3:1 where it is a control', () => {
  // ── AUDIT: app.css:1065 — opacity multipliers stacked on already-translucent
  //    tokens put live controls at 1.7–3.0:1 ─────────────────────────────────
  //
  // EVIDENCE. `--fg-faint` was raised to 0.48 "to clear WCAG's 3:1 minimum for
  // non-text UI components" and measures 3.2:1 alone. Four rules then put an
  // `opacity` on the subtree around it: `.sched-card.off { opacity: 0.6 }`,
  // `.disp-picks .chip { opacity: 0.45 }`, `.side-item.cal-hidden .name,
  // .count { opacity: .45 }`, `.mini-day.dim { opacity: 0.5 }`. Measured
  // before the fix, light theme: the off card's toggle 1.92, its meta and Edit
  // button 2.33, an off chip 1.82, the hidden calendar's name 2.92 and count
  // 1.59, the dim mini-day 1.69. Every one of those is a live control — the
  // toggle is what turns the link back on, the chip is an enabled
  // `aria-pressed` button, the row IS the checkbox, the dim day opens the
  // popover when it has events. The closed finding at AUDIT.md:2781 already
  // prescribed dropping the mini-calendar's multiplier; only the token moved.
  //
  // Measuring it found one more thing the finding did not: the display chips
  // are <button>s and `.chip` sets no background, so each carried the user
  // agent's grey ButtonFace — under the dark theme a light box around light
  // faint text, 1.02:1 with the opacity and 1.01:1 without it. Hence the
  // `background: none` a pressable chip needs (the shape `.habit-day` already
  // has), and hence the dark rows in THEMES.
  const CONTROLS: [string, string][] = [
    ['.sched-card.off .sched-toggle span', "the off link's toggle"],
    ['.sched-card.off .sched-card-meta', "the off link's meta line"],
    ['.sched-card.off .sched-card-actions .btn', "the off link's Edit button"],
    ['.disp-picks .chip:not(.is-on)', 'an unselected display chip'],
    ['.side-item.cal-hidden .name', "a hidden calendar's name"],
    ['.side-item.cal-hidden .count', "a hidden calendar's count"],
    ['.mini-day.dim', 'an adjacent-month mini-calendar day'],
  ]
  const THEMES: { theme?: string; preset?: string }[] = [
    {}, { theme: 'dark' }, { preset: 'workspace' }, { preset: 'workspace', theme: 'dark' },
  ]

  it('every dimmed control composites to at least 3:1 in every theme', async () => {
    await viewport(1200)
    const under: string[] = []
    for (const t of THEMES) {
      document.body.innerHTML = ''
      const root = document.documentElement
      delete root.dataset.theme; delete root.dataset.preset
      if (t.theme) root.dataset.theme = t.theme
      if (t.preset) root.dataset.preset = t.preset
      const host = await mount(DIMMED_CONTROLS)
      for (const [sel, what] of CONTROLS) {
        const el = host.querySelector(sel)
        expect(el, `${sel} is not in the fixture`).not.toBeNull()
        const c = paintedContrast(el!)
        if (c < 3) under.push(`${what} (${sel}) at ${c}:1 in ${JSON.stringify(t)}`)
      }
    }
    expect(under, `below the 3:1 the tokens were raised to meet:\n  ${under.join('\n  ')}`)
      .toEqual([])
  })

  it('and the dimming is done with tokens, not with a subtree opacity', async () => {
    // The mechanism, not just the number: a token can be re-measured when the
    // palette moves, a multiplier on top of it cannot. Opacity 1 on every
    // element from the control up to its backdrop.
    await viewport(1200)
    const host = await mount(DIMMED_CONTROLS)
    const faded: string[] = []
    for (const [sel] of CONTROLS) {
      let node: Element | null = host.querySelector(sel)
      for (; node && node !== host; node = node.parentElement) {
        const o = parseFloat(getComputedStyle(node).opacity)
        if (o < 1) faded.push(`${sel}: ${node.className} at opacity ${o}`)
      }
    }
    expect(faded).toEqual([])
    // And no user-agent button face under the off chip: `rgb(239, 239, 239)`
    // before the fix, in both themes.
    expect(getComputedStyle(host.querySelector('.disp-picks .chip:not(.is-on)')!).backgroundColor)
      .toBe('rgba(0, 0, 0, 0)')
  })

  it('still tells an off state from an on one without the opacity', async () => {
    // The control test. Losing the multiplier must not lose the state: an off
    // link and an on link, an off chip and an on chip, a hidden calendar and a
    // shown one have to paint differently.
    await viewport(1200)
    const host = await mount(DIMMED_CONTROLS
      + '<div class="shell"><div class="work"><div class="side">'
      + '<div class="side-item" role="checkbox"><span class="name">Work</span></div></div>'
      + '<div class="content"><div class="sched-list"><div class="sched-card">'
      + '<span class="sched-card-title">Live</span></div></div></div></div></div>')
    const paint = (sel: string) => {
      const s = getComputedStyle(host.querySelector(sel)!)
      return [s.color, s.borderTopColor, s.borderTopStyle].join(' ')
    }
    expect(paint('.disp-picks .chip:not(.is-on)')).not.toBe(paint('.disp-picks .chip.is-on'))
    expect(paint('.side-item.cal-hidden .name')).not.toBe(paint('.side-item:not(.cal-hidden) .name'))
    expect(paint('.sched-card.off .sched-card-title') + paint('.sched-card.off'))
      .not.toBe(paint('.sched-card:not(.off) .sched-card-title') + paint('.sched-card:not(.off)'))
  })
})

// ── #2 a .modal at a short viewport ─────────────────────────────────────────

// The event editor's default field set, class for class from CalendarView.tsx:
// 1245-1367 — the SHORT version (no repeat-until, one calendar), which is the
// least a real editor ever renders.
const EVENT_EDITOR = `
  <div class="shell"><div class="overlay">
    <div class="modal" role="dialog" aria-modal="true" aria-label="Edit event">
      <div class="modal-head">
        <span class="modal-title">Edit event</span>
        <button class="icon-btn" aria-label="Close">&#10005;</button>
      </div>
      <div class="field"><label class="label" for="ev-title">Title</label><input class="input" id="ev-title" value="Standup" /></div>
      <label class="chip" style="align-self: flex-start"><input type="checkbox" /> All day</label>
      <div class="field-row">
        <div class="field"><label class="label" for="ev-start">Start</label><input class="input" id="ev-start" type="datetime-local" /></div>
        <div class="field"><label class="label" for="ev-end">End</label><input class="input" id="ev-end" type="datetime-local" /></div>
      </div>
      <div class="field"><label class="label" for="ev-repeat">Repeat</label>
        <select class="input" id="ev-repeat"><option>Does not repeat</option></select></div>
      <div class="field reminder-row"><label class="label" for="ev-reminder">Reminder</label>
        <select class="menu-toggle reminder-field" id="ev-reminder"><option>None</option></select></div>
      <div class="field"><label class="label" for="ev-busy">Show as</label>
        <select class="input" id="ev-busy"><option>Busy</option></select></div>
      <div class="field"><label class="label" for="ev-location">Location</label><input class="input" id="ev-location" /></div>
      <div class="field"><label class="label" for="ev-notes">Notes</label><textarea class="input" id="ev-notes" rows="2"></textarea></div>
      <div class="field"><label class="label">Tags</label><input class="input" /></div>
      <div class="modal-actions">
        <button class="btn ghost">Delete</button>
        <span class="spacer"></span>
        <button class="btn" id="save">Save</button>
      </div>
    </div>
  </div></div>`

describe('2026-09-03 — the event editor at a viewport wider than 720px but shorter than the form', () => {
  // ── AUDIT: app.css:660 — outside max-width:720px a .modal has no max-height
  //    and no scroller ───────────────────────────────────────────────────────
  //
  // EVIDENCE. `.overlay` is `position: fixed; inset: 0; align-items: center`
  // and the base `.modal` sets width only; the `max-height: 92dvh; overflow-y:
  // auto` that makes it a sheet lives inside `@media (max-width: 720px)`. A
  // phone on its side is 844 CSS px wide, so it takes the desktop branch.
  // Measured before the fix at 844x390: modal 717px tall at top -163, the title
  // at -143 (above the screen), Save's bottom at 534 in a 390px viewport,
  // `.modal` overflow-y visible, nothing anywhere scrolls. Same at an
  // un-maximised 1280x600 laptop window (title -33, Save 634).
  it.each([[844, 390], [1280, 600]])('keeps the title and Save on screen at %ix%i', async (w, h) => {
    await viewport(w, h)
    const host = await mount(EVENT_EDITOR)
    const modal = host.querySelector<HTMLElement>('.modal')!
    const title = host.querySelector('.modal-title')!
    const save = host.querySelector('#save')!

    expect(getComputedStyle(modal).overflowY, 'the modal is not a scroller').toBe('auto')
    expect(box(modal).top, 'the modal starts above the viewport').toBeGreaterThanOrEqual(0)
    expect(box(modal).bottom, 'the modal runs past the viewport').toBeLessThanOrEqual(h)
    expect(box(title).top, 'the title is off the top of the screen').toBeGreaterThanOrEqual(0)
    expect(hits(title), 'the title is covered').toBe(true)

    modal.scrollTop = modal.scrollHeight
    await new Promise(requestAnimationFrame)
    expect(box(save).bottom, 'Save cannot be scrolled into view').toBeLessThanOrEqual(h)
    expect(hits(save), 'Save is covered by something else').toBe(true)
  })

  it('does not clip an editor that already fits', async () => {
    // Control. At a laptop's full height the form is shorter than the viewport
    // and nothing may change: the box is its content's height and does not
    // scroll.
    await viewport(1200)
    const host = await mount(EVENT_EDITOR)
    const modal = host.querySelector<HTMLElement>('.modal')!
    expect(modal.scrollHeight).toBeLessThanOrEqual(modal.clientHeight + 1)
    expect(box(modal).h).toBeLessThan(844 - 40)
  })

  it('leaves the phone sheet exactly as it was', async () => {
    // The rules at app.css:1014-1019 must keep winning below 720px: a sheet
    // anchored to the bottom edge, capped at 92dvh.
    await viewport(390)
    const host = await mount(EVENT_EDITOR)
    const modal = host.querySelector<HTMLElement>('.modal')!
    expect(getComputedStyle(modal).maxHeight).toBe(`${(0.92 * 844).toFixed(2)}px`)
    expect(box(modal).bottom).toBe(844)
  })
})

// ── #3 a spaceless visitor name in the Scheduling pane ──────────────────────

const X200 = 'x'.repeat(200)

// SchedulingView.tsx:150-227, the tree the pane's `.scroll` sits in.
const SCHEDULING = (name: string, notes: string) => `
  <div class="shell"><div class="work"><div class="content">
    <div class="content-head"><span class="content-title">Scheduling</span><span class="spacer"></span>
      <button class="btn">New link</button></div>
    <div class="scroll">
      <div class="sched-list"></div>
      <div class="section-label label">Upcoming</div>
      <div class="sched-bookings">
        <div class="sched-booking">
          <span class="when mono">Mon 7 Sep, 10:00</span>
          <span class="who">${name} <span class="email">a@b.c</span></span>
          <span class="via">Intro call</span>
          <span class="notes">${notes}</span>
        </div>
      </div>
    </div>
  </div></div></div>`

describe('2026-09-03 — a booking visitor cannot scroll the Scheduling pane sideways', () => {
  // ── AUDIT: app.css:1084 — a visitor's name or notes with no spaces widen
  //    the owner's Scheduling pane ─────────────────────────────────────────
  //
  // EVIDENCE. The closed finding at AUDIT.md:2222 added `overflow-wrap:
  // anywhere` to `.task-title`, `.today-title` and `.agenda-ev` and pinned
  // those three; `.sched-booking .who` and `.notes` render the visitor's
  // `name`/`notes` from the anonymous booking POST (up to 200 and 2000 chars,
  // no space required) with no wrap guard, inside `.scroll`, whose
  // `overflow-y: auto` makes `overflow-x` auto too. Measured before the fix at
  // 390px: a 200-char name gives `.scroll` scrollWidth 1414 in clientWidth 390.
  it.each([390, 360])('a 200-character token in the name or notes wraps at %ipx', async (w) => {
    await viewport(w)
    let host = await mount(SCHEDULING(X200, 'fine'))
    let scroll = host.querySelector('.scroll')!
    expect(scroll.scrollWidth, `the name widened .scroll to ${scroll.scrollWidth}`)
      .toBeLessThanOrEqual(scroll.clientWidth)
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(innerWidth)

    document.body.innerHTML = ''
    host = await mount(SCHEDULING('Jane Doe', X200))
    scroll = host.querySelector('.scroll')!
    expect(scroll.scrollWidth, `the notes widened .scroll to ${scroll.scrollWidth}`)
      .toBeLessThanOrEqual(scroll.clientWidth)
  })

  it("nor can a link's description on the public page, or a connected app's name", async () => {
    // The other two sinks the finding names. Both are owner-approved text
    // rather than anonymous, and the connections list is its own scroller so
    // the sheet does not drift — but the guard is one declaration and the
    // clipped-and-sideways failure is the same shape.
    await viewport(390)
    let host = await mount(`<div class="booking-wrap"><div class="booking-card">
      <h1 class="booking-title">Intro call</h1><p class="booking-desc">${X200}</p></div></div>`)
    const wrap = host.querySelector('.booking-wrap')!
    expect(wrap.scrollWidth).toBeLessThanOrEqual(wrap.clientWidth)

    document.body.innerHTML = ''
    host = await mount(`<div class="shell"><div class="topbar"><div class="menu settings-menu">
      <div class="set-body"><div class="set-panels"><div class="set-panel">
        <div class="conn-list"><div class="conn"><div class="conn-main">
          <div class="conn-name">${X200}</div>
          <div class="conn-meta"><span class="chip">read</span></div>
        </div></div></div>
      </div></div></div></div></div></div>`)
    const list = host.querySelector('.conn-list')!
    expect(list.scrollWidth).toBeLessThanOrEqual(list.clientWidth)
  })
})

// ── #1 / #6 the Focus surface at a landscape phone ──────────────────────────

// The browser face, class for class from FocusView.tsx:404-544 with a live
// running session, a current row and a next row — the state that renders the
// footer. NOT the `data-float` variant `layout.browser.test.tsx` measures: that
// one already has height concessions, this one had none.
const FULL_FACE = `
  <div class="shell">
    <div class="focus" data-state="running" data-phase="focus">
      <header class="focus-head">
        <span class="label">Focus</span>
        <span class="focus-head__interval">Interval 3</span>
        <span class="spacer"></span>
        <span class="focus-head__tally">2 / 8 done</span>
        <button type="button" class="btn ghost focus-back">Back</button>
      </header>
      <main class="focus-main">
        <div class="focus-phase" role="status">Focus</div>
        <div class="focus-clock">24:59</div>
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
            <button type="button" class="btn ghost">Pause</button>
          </div>
        </div>
        <div class="focus-next">
          <div class="focus-now__eyebrow">Next</div>
          <div class="focus-next__text"><button type="button" class="focus-pick">Invoice Friday</button></div>
          <div class="focus-next__more">+6 behind that</div>
        </div>
      </main>
      <footer class="focus-foot">
        <span class="spacer"></span>
        <button type="button" class="btn ghost" id="end">End session</button>
      </footer>
    </div>
  </div>`

describe('2026-09-03 — the Focus surface in a short viewport', () => {
  // ── AUDIT: app.css:2361 — the Focus surface ignores the safe-area insets
  //    and in a short viewport its centred content overflows under the header
  //    and footer with no way to scroll ──────────────────────────────────────
  //
  // EVIDENCE. `.focus-main` is `flex: 1; min-height: 0; justify-content:
  // center` with `overflow-y` visible, inside a `.focus` that is `position:
  // fixed; inset: 0; overflow: hidden`. Measured before the fix at 844x390:
  // `.focus-main` scrollHeight 340 in clientHeight 268; `.focus-phase` top
  // -9.1 (off the screen, over the 0-63 header row); `.focus-next` bottom 403
  // in a 390 viewport, under the footer; and `elementFromPoint` at the Next
  // picker's centre returned `.focus-foot`. The only recovery rule in the file
  // (`justify-content: flex-start; overflow-y: auto`, app.css:2530) is gated on
  // `[data-float]`.
  it.each([[844, 390], [667, 375]])('scrolls rather than painting the face under the header and footer at %ix%i', async (w, h) => {
    await viewport(w, h)
    const host = await mount(FULL_FACE)
    const main = host.querySelector<HTMLElement>('.focus-main')!
    const head = box(host.querySelector('.focus-head')!)
    const foot = box(host.querySelector('.focus-foot')!)

    expect(main.scrollHeight, 'the face fits; this viewport no longer exercises the overflow')
      .toBeGreaterThan(main.clientHeight)
    expect(getComputedStyle(main).overflowY).toBe('auto')
    expect(box(host.querySelector('.focus-phase')!).top, 'the phase label is under the header')
      .toBeGreaterThanOrEqual(head.bottom - 0.5)

    main.scrollTop = main.scrollHeight
    await new Promise(requestAnimationFrame)
    const pick = host.querySelector('.focus-pick')!
    expect(box(host.querySelector('.focus-next')!).bottom, 'NEXT is under the footer')
      .toBeLessThanOrEqual(foot.top + 0.5)
    expect(hits(pick), 'the Next picker is painted over and unclickable').toBe(true)
  })

  it('still centres the face where it fits', async () => {
    // Control: portrait. `safe center` is `center` until something overflows,
    // so the clock stays where it was — well clear of both bars.
    await viewport(390, 844)
    const host = await mount(FULL_FACE)
    const main = host.querySelector<HTMLElement>('.focus-main')!
    expect(main.scrollHeight).toBeLessThanOrEqual(main.clientHeight + 1)
    const phase = box(host.querySelector('.focus-phase')!)
    expect(phase.top - box(host.querySelector('.focus-head')!).bottom).toBeGreaterThan(40)
  })

  // ── AUDIT: app.css:2434 — the footer ('End session') ignores
  //    env(safe-area-inset-bottom) ─────────────────────────────────────────
  //
  // EVIDENCE. `.focus-foot { padding: 12px var(--gutter) }` is the only
  // padding declaration that reaches it, and `.focus` escapes `.shell`'s
  // horizontal insets by being `position: fixed`. index.html opts into
  // `viewport-fit=cover`; `.day-agenda`, `.scroll`, `.modal`, `.toast`,
  // `.dash-stack` and the settings sheet all read the bottom inset. Headless
  // Chromium reports every inset as 0, so the box cannot show it — what the
  // browser CAN say is which declarations currently match, and before the fix
  // none of them mentioned an inset.
  it('reads the safe-area insets, and no other rule sets those paddings', async () => {
    await viewport(844, 390)
    const host = await mount(FULL_FACE)
    const focus = host.querySelector('.focus')!
    const head = host.querySelector('.focus-head')!
    const foot = host.querySelector('.focus-foot')!

    const carrying = (el: Element, prop: string, inset: string) => {
      const rules = declaring(el, prop)
      expect(rules, `no rule sets ${prop} on ${el.className}`).not.toEqual([])
      const without = rules.filter((r) => !r.includes(`env(safe-area-inset-${inset})`))
      expect(without, `${prop} on ${el.className} can be won by a rule without the inset`).toEqual([])
    }
    carrying(foot, 'padding-bottom', 'bottom')
    carrying(head, 'padding-top', 'top')
    carrying(focus, 'padding-left', 'left')
    carrying(focus, 'padding-right', 'right')

    // And the measurable half: with the inset at 0 the footer, and its one
    // button, sit inside the viewport.
    expect(box(foot).bottom).toBeLessThanOrEqual(390)
    expect(box(host.querySelector('#end')!).bottom).toBeLessThanOrEqual(390 - 12)
    expect(hits(host.querySelector('#end')!)).toBe(true)
  })

  it('leaves the floating window its own, tighter header', async () => {
    // Control: `.focus[data-float] .focus-head { padding: 6px 10px }` is later
    // and more specific, so the inset padding-top must not reach the window
    // that has no inset. Same for its hidden footer.
    await viewport(408, 268)
    const host = await mount(FULL_FACE.replace('class="focus"', 'class="focus" data-float=""'))
    expect(getComputedStyle(host.querySelector('.focus-head')!).paddingTop).toBe('6px')
    expect(getComputedStyle(host.querySelector('.focus-foot')!).display).toBe('none')
  })
})

// ── #5 the .menu-toggle selects on a phone ──────────────────────────────────

describe('2026-09-03 — a <select class="menu-toggle"> clears the iOS 16px floor', () => {
  // ── AUDIT: SettingsMenu.tsx:216 — the Language picker renders at 11px on
  //    phones, re-arming iOS Safari's zoom-on-focus ──────────────────────────
  //
  // EVIDENCE. `.menu-toggle` is `font-size: calc(11px * var(--fs-scale))` and
  // the phone block's only `.menu-toggle` rule changes padding; every `max(16px,
  // …)` floor in the sheet is qualified by `.input`. Measured before the fix at
  // 390px: `#set-language` 11px, `#ev-reminder` (ReminderField.tsx:42, in the
  // task and event modals) 11px, beside `select.input` siblings at 16px. iOS
  // zooms on a focused control under 16px and does not zoom back. The fix is
  // CSS, not a class on the JSX: `select.menu-toggle` at (0,1,1) outranks
  // `.menu-toggle` wherever the next fence lands.
  it('computes to at least 16px at 390px, and only scales up', async () => {
    await viewport(390)
    const host = await mount(`<div class="shell">
      <div class="menu-row"><label for="set-language">Language</label>
        <select class="menu-toggle" id="set-language"><option>English</option></select></div>
      <div class="field reminder-row">
        <select class="menu-toggle reminder-field" id="ev-reminder"><option>None</option></select></div>
      <div style="--fs-scale: 0.8"><select class="menu-toggle" id="scaled"><option>x</option></select></div>
      <button class="menu-toggle" id="btn">Dark</button>
    </div>`)
    const under: string[] = []
    for (const el of host.querySelectorAll<HTMLElement>('select.menu-toggle')) {
      const px = parseFloat(getComputedStyle(el).fontSize)
      if (px < 16) under.push(`#${el.id} at ${px}px`)
    }
    expect(under, `${under.join(', ')} — Safari zooms on focus below 16px`).toEqual([])
    // Control: the BUTTON toggles beside it are not form controls iOS zooms
    // for, and keep the sheet's 11px label size.
    expect(parseFloat(getComputedStyle(host.querySelector('#btn')!).fontSize)).toBe(11)
  })

  it('and keeps the desktop size where there is no zoom to arm', async () => {
    await viewport(1200)
    const host = await mount('<div class="shell"><select class="menu-toggle"><option>x</option></select></div>')
    expect(parseFloat(getComputedStyle(host.querySelector('select')!).fontSize)).toBe(11)
  })
})

// ── AUDIT: App.tsx:1089 — the tab strip and the settings gear keep ~29px tap
//    targets on the phone (the ARIA half of the finding lives in App.tsx) ──────
//
// EVIDENCE. `.tab` is 11px mono with `padding: 6px 8px 8px` and a 2px border,
// so its box is ~29px tall at 390px, and the gear beside it is 30px — both under
// the 44px this repo set for the Today row's controls, and both the first thing
// every session taps. Measured before the fix at 390x844: a point 20px above
// the tab's centre hit the `.topbar`, not the tab.
//
// The repair is the Today row's: a centred 44px `::after` that costs no width,
// so the bar's height does not change. Hit-tested rather than measured as a box,
// because a pseudo-element has no box to read — the browser answers what a
// finger 20px off the label would land on.
const TOPBAR = `
  <header class="topbar">
    <span class="brand">Smylte<span class="dot">.</span></span>
    <div class="tabs">
      <button class="tab active" aria-current="page">Today</button>
      <button class="tab">Tasks</button>
      <button class="tab">Calendar</button>
    </div>
    <span class="spacer"></span>
    <button class="icon-btn" aria-label="Settings">⚙</button>
  </header>`

describe('2026-09-03 — the tab strip and the settings gear on a phone', () => {
  it('catch a touch 20px off the label, and the bar does not grow for it', async () => {
    await viewport(390, 844)
    const host = await mount(TOPBAR)
    const bar = host.querySelector('.topbar')!
    const tab = host.querySelectorAll('.tab')[1]
    const gear = host.querySelector('.icon-btn')!
    for (const el of [tab, gear]) {
      const [x, y] = midpoint(el)
      // 20px above and below the centre: inside a 44px area, outside a 30px box.
      for (const dy of [-20, 20]) {
        const at = document.elementFromPoint(x, y + dy)
        expect(el.contains(at) || at === el, `${el.className} does not catch a touch ${dy}px off its centre`).toBe(true)
      }
    }
    // The box itself is unchanged, so the bar stays the height the strip's
    // scroll rule was measured against.
    expect(box(tab).h, 'the tab grew its own box').toBeLessThan(36)
    expect(box(bar).h, 'the topbar grew').toBeLessThan(56)
  })
})
