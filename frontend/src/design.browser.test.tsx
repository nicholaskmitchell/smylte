// The two designs, as the browser computes them.
//
// design-tokens.test.ts holds the lever arrangement as TEXT; this holds what it
// is for, as computed style: the shipped design is the September 2026
// refinement, and Classic is the design before it — not an approximation of it.
// The pins for the IDs that apply here name the change they guard by the
// design system's CHANGES.md ID; the ones about Classic name what they restore.
import { afterEach, describe, expect, it } from 'vitest'
import { mount, viewport } from './test/browser-measure'

const SINK = `
  <div class="shell">
    <header class="topbar">
      <span class="brand">Smylte<span class="dot">.</span></span>
      <nav class="tabs"><button class="tab active">Today</button><button class="tab">Home</button></nav>
      <span class="spacer"></span>
      <button class="icon-btn" aria-label="Settings">⚙</button>
      <div class="menu"><div class="menu-head">Settings</div>
        <div class="menu-row"><label>Theme</label><button class="menu-toggle">Light</button></div></div>
    </header>
    <div class="work">
      <aside class="side"><div class="side-list">
        <div class="side-item active"><span class="swatch swatch-all"></span><span class="name">All lists</span></div>
        <div class="side-item"><span class="swatch"></span><span class="name">Work</span></div>
      </div></aside>
      <main class="content">
        <div class="content-head"><span class="content-title">All lists</span>
          <div class="view-tabs" style="--n: 3; --i: 0">
            <button class="view-tab active">List</button><button class="view-tab">3-Day</button><button class="view-tab">Week</button>
          </div></div>
        <form class="quickadd"><input class="input" /><button class="btn">Add</button><button class="btn ghost">Cancel</button></form>
        <div class="task"><button class="check"></button><div class="task-body">
          <span class="task-title">Draft the review</span>
          <div class="task-meta"><span class="chip">#writing</span></div></div></div>
        <div class="label">Due</div>
        <div class="modal"><span class="modal-title">Task</span></div>
      </main>
    </div>
  </div>`

const cs = (host: HTMLElement, sel: string, pseudo?: string) =>
  getComputedStyle(host.querySelector(sel)!, pseudo)
const root = () => getComputedStyle(document.documentElement)

afterEach(() => { delete document.documentElement.dataset.preset })

describe('the shipped design is the refinement', () => {
  it('reads in Newsreader, controls in Hanken Grotesk, labels in JetBrains Mono (T0, T7)', async () => {
    await viewport(1200)
    const host = await mount(SINK)
    expect(cs(host, '.content-title').fontFamily).toMatch(/^"?Newsreader/)
    expect(cs(host, '.brand').fontFamily).toMatch(/^"?Newsreader/)
    for (const sel of ['.btn', '.tab', '.menu-toggle', '.view-tab', '.chip']) {
      expect(cs(host, sel).fontFamily, sel).toMatch(/^"?Hanken Grotesk/)
    }
    expect(cs(host, '.label').fontFamily).toMatch(/^"?JetBrains Mono/)
    // Loaded, not merely named: a family that never arrives would still pass
    // the checks above.
    expect(document.fonts.check('14px "Hanken Grotesk"')).toBe(true)
    expect(document.fonts.check('24px "Newsreader"')).toBe(true)
  })

  it('sets controls as words: 14px, 500, sentence case, no tracking (T7, T8)', async () => {
    await viewport(1200)
    const host = await mount(SINK)
    const btn = cs(host, '.btn')
    expect(btn.fontSize).toBe('14px')
    expect(btn.fontWeight).toBe('500')
    expect(btn.textTransform).toBe('none')
    expect(btn.letterSpacing).toMatch(/^(normal|0px)$/)
    expect(cs(host, '.label').textTransform).toBe('none')
    expect(parseFloat(btn.minHeight)).toBe(38)      // F4
  })

  it('rounds by the scale, and nothing is a perfect circle (S1, S3)', async () => {
    await viewport(1200)
    const host = await mount(SINK)
    expect(cs(host, '.btn').borderRadius).toBe('8px')
    expect(cs(host, '.input').borderRadius).toBe('8px')
    expect(cs(host, '.check').borderRadius).toBe('4px')
    expect(cs(host, '.menu').borderRadius).toBe('12px')
    expect(cs(host, '.modal').borderRadius).toBe('18px')
    expect(parseFloat(cs(host, '.chip').borderRadius)).toBeGreaterThan(100)  // a pill
    expect(cs(host, '.swatch-all').borderRadius).toBe('2px')
    const circles = [...host.querySelectorAll('*')]
      .filter((el) => getComputedStyle(el).borderRadius.includes('%'))
      .map((el) => el.className)
    expect(circles).toEqual([])
  })

  it('floats cast the ink-tinted shadow; rows drop their rule (E1, C3)', async () => {
    await viewport(1200)
    const host = await mount(SINK)
    expect(cs(host, '.menu').boxShadow).toContain('rgba(20, 19, 26')
    expect(cs(host, '.task').borderBottomColor).toBe('rgba(0, 0, 0, 0)')
    expect(parseFloat(cs(host, '.task').marginLeft)).toBe(6)
  })

  it('slides a thumb under the active segment (F5)', async () => {
    await viewport(1200)
    const host = await mount(SINK)
    const thumb = cs(host, '.view-tabs', '::before')
    expect(thumb.content).not.toBe('none')
    expect(cs(host, '.view-tabs > .view-tab.active').backgroundColor).toBe('rgba(0, 0, 0, 0)')
    // The thumb sits under segment --i: at --i 0 it starts where the first
    // segment does.
    const track = host.querySelector('.view-tabs')!.getBoundingClientRect()
    const first = host.querySelector('.view-tab')!.getBoundingClientRect()
    expect(Math.abs(track.left + 3 - first.left)).toBeLessThan(1)
  })

  it('animates enter, presses in, and eases (M1, M4, F2)', async () => {
    await viewport(1200)
    await mount(SINK)
    expect(root().getPropertyValue('--press-scale').trim()).toBe('0.98')
    expect(root().getPropertyValue('--ease').trim()).toBe('cubic-bezier(0.2, 0, 0, 1)')
    expect(root().getPropertyValue('--enter-float').trim()).toMatch(/^float-in /)
  })
})

describe('Classic is the design before it', () => {
  const classic = async () => {
    await viewport(1200)
    document.documentElement.dataset.preset = 'classic'
    return mount(SINK)
  }

  it('reads in Fraunces and Inter, with mono caps on every control', async () => {
    const host = await classic()
    expect(cs(host, '.content-title').fontFamily).toMatch(/^"?Fraunces/)
    expect(getComputedStyle(document.body).fontFamily).toMatch(/^"?Inter/)
    for (const sel of ['.btn', '.tab', '.menu-toggle', '.view-tab', '.chip']) {
      expect(cs(host, sel).fontFamily, sel).toMatch(/^"?JetBrains Mono/)
    }
    expect(cs(host, '.btn').textTransform).toBe('uppercase')
    expect(cs(host, '.btn').fontSize).toBe('11px')
    expect(parseFloat(cs(host, '.btn').letterSpacing)).toBeGreaterThan(0)
    expect(document.fonts.check('24px "Fraunces"')).toBe(true)
  })

  it('is square, bar the round "all" swatch it always had', async () => {
    const host = await classic()
    for (const sel of ['.btn', '.input', '.check', '.menu', '.modal', '.chip', '.task', '.view-tabs']) {
      expect(cs(host, sel).borderRadius, sel).toBe('0px')
    }
    expect(cs(host, '.swatch-all').borderRadius).toBe('50%')
  })

  it('keeps the hard black shadow, the row rules and the inverted segment', async () => {
    const host = await classic()
    expect(cs(host, '.menu').boxShadow).toBe('rgba(0, 0, 0, 0.2) 0px 10px 30px 0px')
    expect(cs(host, '.task').borderBottomColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(parseFloat(cs(host, '.task').marginLeft)).toBe(0)
    expect(cs(host, '.view-tabs', '::before').content).toBe('none')
    expect(cs(host, '.view-tab.active').backgroundColor).toBe(cs(host, '.content-title').color)
  })

  it('and neither presses nor rises', async () => {
    await classic()
    expect(root().getPropertyValue('--press-scale').trim()).toBe('1')
    expect(root().getPropertyValue('--enter-float').trim()).toBe('none')
    expect(parseFloat(getComputedStyle(document.querySelector('.btn')!).minHeight) || 0).toBe(0)
  })
})

describe('T9 · Hanken Grotesk, fitted to dense rows', () => {
  // The sans is x-height-normalised rather than resized: `font-size-adjust`
  // renders it at a 0.516em x-height of the size it is declared at, so every
  // size token and every line-height (both computed from font-size) is where
  // it was. Content text takes 460 and 14–15px of it tightens; UI text takes
  // 450; controls keep 500. The serif and the mono are never adjusted.
  const ROWS = `
    <div class="shell">
      <header class="topbar"><span class="brand">Smylte<span class="dot">.</span></span>
        <nav class="tabs"><button class="tab active">Today</button></nav></header>
      <div class="work">
        <aside class="side"><div class="side-list">
          <div class="side-item all-row"><span class="swatch swatch-all"></span><span class="name">All lists</span><span class="count">12</span></div>
          <div class="side-item"><span class="swatch"></span><span class="name">Household</span><span class="count">4</span></div>
          <div class="group-head"><button class="group-name">Work</button><span class="count">3</span></div>
        </div></aside>
        <main class="content">
          <div class="content-head"><span class="content-title">All lists</span><span class="content-sub">12 open</span></div>
          <div class="task"><button class="check">&#10003;</button><div class="task-body">
            <div class="task-title"><span class="list-dot"></span>Plan a trip</div>
            <div class="task-meta"><span class="due">&#9719; Sep 23</span><span class="was-due mono">was due Sep 20</span>
              <span class="child-progress">1/3</span><span class="chip">#home</span></div></div></div>
          <div class="task done"><button class="check on">&#10003;</button><div class="task-body">
            <div class="task-title">Book the flights</div></div></div>
          <div class="day-col-head"><span class="dow">Thu</span><span class="dnum">24</span><span class="count">3</span></div>
          <div class="cal-ev"><span class="t">9:30</span><bdi>Standup</bdi></div>
          <div class="label">Due</div>
          <form class="quickadd"><input class="input" placeholder="Add a task" /><button class="btn">Add</button></form>
          <p class="hintline">Counted as <span class="mono">5h</span> a day.</p>
          <div class="empty">Nothing here.</div>
          <code class="mono">https://example.org/display/x</code>
          <div class="modal"><span class="modal-title">Task</span></div>
        </main>
      </div>
    </div>`

  const SANS = ['.task-title', '.side-item .name', '.btn', '.tab', '.input', '.chip', '.empty', '.hintline', '.cal-ev bdi']
  const serifOrMono = () => [...document.querySelectorAll('*')]
    .filter((e) => /Newsreader|JetBrains/.test(getComputedStyle(e).fontFamily))
  const weight = (host: HTMLElement, sel: string, pseudo?: string) => cs(host, sel, pseudo).fontWeight
  const tracking = (host: HTMLElement, sel: string) => parseFloat(cs(host, sel).letterSpacing) || 0

  it('adjusts the sans, every control included, and never the serif or the mono', async () => {
    await viewport(1200)
    const host = await mount(ROWS)
    for (const sel of SANS) expect(cs(host, sel).fontSizeAdjust, sel).toMatch(/0\.516/)
    // The check the brief asks for, over the whole document: nothing set in
    // Newsreader or JetBrains Mono carries an adjust.
    const faces = serifOrMono()
    expect(faces.length, 'vacuity: the serif and the mono are on the page').toBeGreaterThan(12)
    expect(faces.filter((e) => getComputedStyle(e).fontSizeAdjust !== 'none')
      .map((e) => `${e.tagName.toLowerCase()}.${e.className}`)).toEqual([])
  })

  it('renders a 15px title at a 0.516em x-height, with the size tokens untouched', async () => {
    await viewport(1200)
    // Measured in `ex`, which resolves against the x-height the face is DRAWN
    // at. Not by comparing glyph widths or a canvas `measureText`: headless
    // Chromium on Linux snaps both to whole pixels at this size (forty x's
    // measured 320px adjusted and unadjusted alike), and a canvas font takes
    // no `font-size-adjust` at all.
    const host = await mount(`<div>
      <div class="task-title"><span id="fitted" style="display: inline-block; width: 100ex"></span></div>
      <div class="task-title" style="font-size-adjust: none"><span id="raw" style="display: inline-block; width: 100ex"></span></div></div>`)
    const x = (id: string) => host.querySelector(`#${id}`)!.getBoundingClientRect().width / 100
    // Declared size and line are what they were…
    expect(cs(host, '.task-title').fontSize).toBe('15px')
    expect(cs(host, '.task-title').lineHeight).toBe('22.5px')
    // …and the x is 15 × 0.516, where Hanken's own is 15 × 0.493.
    expect(Math.abs(x('fitted') - 15 * 0.516), `a 15px x is ${x('fitted').toFixed(3)}px tall`).toBeLessThan(0.05)
    expect(Math.abs(x('raw') - 15 * 0.493), `unadjusted, ${x('raw').toFixed(3)}px`).toBeLessThan(0.05)
  })

  it('sets content at 460, tightened; UI text at 450; controls at 500', async () => {
    await viewport(1200)
    const host = await mount(ROWS)
    expect(weight(host, '.task-title')).toBe('460')
    expect(tracking(host, '.task-title')).toBeCloseTo(15 * -0.006, 3)
    expect(weight(host, '.task.done .task-title'), 'a done title keeps its weight').toBe('460')
    expect(weight(host, '.side-item:not(.all-row) .name')).toBe('460')
    expect(tracking(host, '.side-item:not(.all-row) .name')).toBeCloseTo(14 * -0.006, 3)
    expect(weight(host, '.side-item.all-row .name'), 'the All row stays 500').toBe('500')
    expect(tracking(host, '.side-item.all-row .name')).toBe(0)
    for (const sel of ['.input', '.empty', '.hintline', '.cal-ev bdi']) expect(weight(host, sel), sel).toBe('450')
    expect(weight(host, '.input', '::placeholder')).toBe('450')
    // A figure beside UI text keeps the mono's weight.
    expect(weight(host, '.cal-ev .t')).toBe('400')
    expect(weight(host, '.hintline .mono')).toBe('400')
    for (const sel of ['.btn', '.tab', '.chip']) expect(weight(host, sel), sel).toBe('500')
  })

  it.each(['classic', 'workspace'])('leaves %s exactly as it was', async (preset) => {
    await viewport(1200)
    document.documentElement.dataset.preset = preset
    const host = await mount(ROWS)
    for (const sel of SANS) expect(cs(host, sel).fontSizeAdjust, sel).toBe('none')
    for (const sel of ['.task-title', '.side-item:not(.all-row) .name', '.input', '.empty', '.hintline', '.cal-ev bdi']) {
      expect(weight(host, sel), sel).toBe('400')
      expect(tracking(host, sel), sel).toBe(0)
    }
    expect(weight(host, '.side-item.all-row .name')).toBe('500')
  })

  it('and leaves the display, a poster in its own faces, unadjusted', async () => {
    await viewport(1200)
    const host = await mount(`<div class="display display--color">
      <span class="display-title">Thursday</span><span class="display-chip__text">Standup</span></div>`)
    expect(cs(host, '.display').fontSizeAdjust).toBe('none')
    expect(cs(host, '.display-chip__text').fontSizeAdjust).toBe('none')
    host.remove()
  })
})
