// The last controls that showed a bare glyph under Field notes, drawn with the
// pen's icons and the check (Marks.tsx), measured in a real browser.
//
// Each keeps its glyph as text, as every icon button does: under Field notes
// the glyph is set at no size and the icon is drawn at its row's size; under a
// preset the icon is not drawn and the glyph shows. The sizes are the rows':
// 24px in the phone bar, 18px in the phone's rows and the Focus float, 16px in
// a desktop's dense rows and the phone bar's trigger caret, and 14px in a
// task's fold, and an icon under 18px keeps the 18px icon's line. Raw markup
// in the shape the components render (test/browser-measure.ts);
// controls-ink.test.ts holds the JSX to carrying the icon, and the components'
// own suites the markup.
import { beforeEach, describe, expect, it } from 'vitest'
import { applyDesign } from './appearance'
import { box, mount, paint, settle, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const D: Record<string, string[]> = {
  right: ['M9.4 6.1C11.4 8.1 13.4 10.1 15 12C13.3 13.9 11.3 15.9 9.2 17.8'],
  close: ['M6.6 6.4C9.8 9.4 14.2 14 17.6 17.4', 'M17.4 6.5C14.3 9.6 9.9 14.2 6.5 17.5'],
  plus: ['M12 5.6C12.1 9.8 12 14.2 11.9 18.4', 'M5.6 12.1C9.8 11.9 14.2 12 18.4 11.9'],
  check: ['M5.6 12.9C7.2 14.4 8.7 16.1 9.9 17.8C12.3 13.3 15.3 9.4 18.6 6.1'],
  pause: ['M9.2 6.4C9.1 10.2 9.2 13.9 9.3 17.6', 'M14.8 6.5C14.9 10.2 14.8 13.9 14.7 17.5'],
  more: ['M6.2 12.1h.1', 'M12 12h.1', 'M17.8 11.9h.1'],
  reset: ['M6.1 14.8C6.9 17.4 9.3 19.1 12.1 19C15.9 18.9 18.9 15.8 18.8 12C18.7 8.2 15.6 5.2 11.8 5.3C9.4 5.4 7.5 6.6 6.3 8.5'],
  pin: ['M12 11.9C12.1 14.5 11.9 17.1 12 19.6'],
  caret: ['M7.4 10.1C8.9 11.6 10.4 13.1 12 14.6C13.6 13.1 15.1 11.6 16.6 10'],
  play: ['M8.4 5.9C8.2 9.9 8.2 14.1 8.4 18.1C11.7 16.1 15 14.1 18.2 12C15 9.9 11.7 7.9 8.4 5.9Z'],
  mail: ['M5.3 7.6C7.5 9.4 9.7 11.2 12 12.9C14.3 11.2 16.5 9.4 18.7 7.6'],
  edit: ['M13.6 7.4C14.6 8.4 15.6 9.4 16.6 10.4'],
}
/** IconInk's markup. */
const icon = (name: string) => `<svg class="icon-ink" data-icon="${name}" viewBox="0 0 24 24" aria-hidden="true">`
  + `${D[name].map((d) => `<path d="${d}"/>`).join('')}</svg>`
/** CheckInk's markup. */
const CHECK = '<svg class="check-ink" viewBox="0 0 28 28" aria-hidden="true">'
  + '<path class="check-frame" d="M5.2 4.6C10 4.1 18.4 4.3 23.1 5.2C23.8 10 23.6 18.3 22.9 23.2C18 23.7 9.8 23.9 4.9 23.1C4.3 18.4 4.4 9.6 5.2 4.6Z"/>'
  + '<path class="check-tick ink" pathLength="1" d="M8.6 14.6C10 15.8 11.4 17.6 12.4 19C14.6 14.4 18.6 9.2 23.8 5.8"/></svg>'

/** A list group's head and a list under it, as Sidebar renders them, and the
 *  Calendar's own Tasks group. */
const GROUPS = `
  <div class="side-group g-open"><div class="group-head">
    <button class="group-caret" aria-expanded="true"><span class="caret open">&#9656;${icon('right')}</span></button>
    <button class="group-name">Work</button><span class="count">3</span>
    <button class="group-eye" aria-pressed="true">&#9673;${CHECK}</button>
    <span class="group-actions"><button class="group-btn g-rename">&#9998;${icon('edit')}</button><button class="group-btn g-delete">&#10005;${icon('close')}</button></span>
  </div>
  <div class="side-item"><span class="swatch"></span><span class="name">Household</span><span class="count">4</span><button class="side-edit">&#8943;${icon('more')}</button></div></div>
  <div class="side-group g-shut"><div class="group-head">
    <button class="group-caret" aria-expanded="false"><span class="caret ">&#9656;${icon('right')}</span></button>
    <button class="group-name">Home</button><span class="count">2</span>
    <button class="group-eye" aria-pressed="false">&#9676;${CHECK}</button>
    <span class="group-actions"><button class="group-btn danger">delete?</button><button class="group-btn g-cancel">&#10005;${icon('close')}</button></span>
  </div></div>
  <div class="side-group cal-tasks"><div class="group-head">
    <button class="group-caret" aria-expanded="true"><span class="caret open">&#8250;${icon('right')}</span></button>
    <span class="group-name">Tasks</span>
    <button class="group-eye" aria-pressed="true">&#9673;${CHECK}</button>
  </div></div>`
const SIDE = `<div class="shell" data-layout="sidebar"><div class="frame"><nav class="appnav"><div class="appnav-slot">
  <div class="side"><div class="side-list">${GROUPS}</div></div></div></nav><div class="frame-main"><div class="content"></div></div></div></div>`
const DRAWER = `<div class="shell"><div class="overlay drawer-overlay"><div class="side drawer" role="dialog">
  <div class="side-list">${GROUPS}</div></div></div></div>`
const MB_CARET = `<span class="mb-caret" aria-hidden="true">&#9662;${icon('caret')}</span>`
const bar = (caret: string, summary = '4 of 6 shown') => `<div class="shell"><div class="work"><div class="side-mobilebar">
  <button class="side-mobiletrigger"><span class="mb-title">Lists</span><span class="mb-summary">${summary}</span>${caret}</button>
  <button class="side-mobile-completed active s-done" aria-pressed="true">&#10003;${icon('check')}</button>
  <button class="side-mobile-completed s-parked" aria-pressed="false">&#9208;${icon('pause')}</button>
  <button class="side-mobile-completed s-sug" aria-pressed="false">&#9993;${icon('mail')}<span class="side-badge">3</span></button>
  <button class="side-mobile-add">+${icon('plus')}</button></div><div class="content"></div></div></div>`
const BAR = bar(MB_CARET)
const TOKEN = `<div class="settings-menu"><div class="set-panel"><div class="appear-row"><label class="appear-label">Serif</label>
  <div class="appear-control"><input class="input" /><button class="appear-clear">&#8634;${icon('reset')}</button></div></div></div></div>`
const MODULE = `<div class="shell"><div class="work"><div class="content"><div class="scroll"><div class="dash-grid arranging">
  <section class="dash-mod" style="left:0;width:50%;top:0;height:200px"><header class="dash-mod-head"><span class="label">Today</span>
  <button class="dash-remove">&#10005;${icon('close')}</button></header><div class="dash-mod-body"></div></section></div></div></div></div></div>`
const TODAY = `<div class="shell"><div class="content today-pane"><div class="scroll"><ul class="today-list">
  <li class="today-row" data-tools=""><button class="check">&#10003;</button><span class="today-title">Water the plants</span>
  <span class="today-meta"><span class="today-due mono">Aug 28</span><button class="today-drop">&#10005;${icon('close')}</button></span></li></ul>
  <section><ul class="today-list"><li class="today-row today-sug"><button type="button" class="today-plus">+${icon('plus')}</button>
  <span class="today-title">Invoice Friday</span></li>
  <li class="today-row today-sug today-triage"><span class="today-plus today-plus-empty" aria-hidden="true">!</span>
  <span class="today-title">Call the bank</span></li></ul></section></div></div></div>`
const PLAN = `<div class="shell"><div class="overlay"><div class="modal plan-ritual" role="dialog"><div class="plan-body plan-scroll">
  <ul class="today-list"><li class="today-row today-sug"><button type="button" class="today-plus">+${icon('plus')}</button>
  <span class="today-title">Invoice Friday</span></li></ul></div></div></div></div>`
const TASKS = `<div class="shell"><div class="work"><div class="content" data-pane="list"><div class="scroll">
  <div class="task-drag"><div class="task t-open"><div class="pri-bar"></div><button class="twisty open" aria-expanded="true">&#8250;${icon('right')}</button>
  <button class="check">&#10003;</button><div class="task-body"><div class="task-title">Plan a trip</div></div></div></div>
  <div class="task-drag"><div class="task t-shut"><div class="pri-bar"></div><button class="twisty" aria-expanded="false">&#8250;${icon('right')}</button>
  <button class="check">&#10003;</button><div class="task-body"><div class="task-title">Book flights</div></div></div></div>
  <div class="task-drag"><div class="task t-leaf"><div class="pri-bar"></div><span class="twisty-gap"></span>
  <button class="check">&#10003;</button><div class="task-body"><div class="task-title">Pack</div></div></div></div></div></div></div></div>`
const FOCUS = (glyph: string) => `<div class="shell"><div class="content today-pane"><div class="content-head today-head">
  <span class="content-title">Today</span><div class="today-acts">
  <button type="button" class="btn ghost today-review">Review</button>
  <button type="button" class="btn ghost today-focus" aria-label="Start working"><span class="today-focus__word">Start working</span>
  <span class="today-focus__glyph mono" aria-hidden="true">${glyph}</span></button>
  <button type="button" class="btn ghost today-menu-btn mono" aria-label="More actions">&#183;&#183;&#183;</button></div></div></div></div>`
/** The phone's Field notes head as TodayView renders it with Start working the
 *  first tool and no Plan my day link; `glyph` is what the button holds. */
const FN_HEAD = (glyph: string) => `<div class="shell"><div class="content today-pane"><div class="fn-list-head" id="fn-head">
  <div class="fn-head-text"><span class="content-title">Today</span><span class="content-sub today-count">1 done \u00b7 7 on the day</span></div>
  <div class="fn-head-tools" id="fn-tools"><div class="today-acts">
  <button type="button" class="btn ghost today-focus" aria-label="Start working"><span class="today-focus__word">Start working</span>
  <span class="today-focus__glyph mono" aria-hidden="true">${glyph}</span></button>
  <button type="button" class="btn ghost today-menu-btn mono" aria-label="More actions">&#183;&#183;&#183;</button></div></div></div></div></div>`
const FLOAT = `<div class="focus" data-float="" data-state="running" data-phase="focus"><header class="focus-head">
  <span class="label">Focus</span><span class="spacer"></span>
  <button type="button" class="btn ghost focus-pin" aria-pressed="true">&#9679;${icon('pin')}</button>
  <button type="button" class="btn ghost focus-back">Dock</button></header></div>`

/** Each control: where it sits, the element that holds its glyph, what it
 *  draws and at what size. */
const CONTROLS: { name: string; html: string; width: number; sel: string; glyph?: string; draws: string; size: number }[] = [
  { name: 'a token\'s reset', html: TOKEN, width: 1440, sel: '.appear-clear', draws: 'reset', size: 16 },
  { name: 'a list group\'s caret', html: SIDE, width: 1440, sel: '.g-open .group-caret', glyph: '.caret', draws: 'right', size: 16 },
  { name: 'the Calendar\'s Tasks caret', html: SIDE, width: 1440, sel: '.cal-tasks .group-caret', glyph: '.caret', draws: 'right', size: 16 },
  { name: 'the Calendar\'s Tasks switch', html: SIDE, width: 1440, sel: '.cal-tasks .group-eye', draws: 'check', size: 16 },
  { name: 'a list group\'s switch', html: SIDE, width: 1440, sel: '.g-open .group-eye', draws: 'check', size: 16 },
  { name: 'a list group\'s rename', html: SIDE, width: 1440, sel: '.g-rename', draws: 'edit', size: 16 },
  { name: 'a list group\'s delete', html: SIDE, width: 1440, sel: '.g-delete', draws: 'close', size: 16 },
  { name: 'a list group\'s cancel', html: SIDE, width: 1440, sel: '.g-cancel', draws: 'close', size: 16 },
  { name: 'a list\'s edit', html: SIDE, width: 1440, sel: '.side-edit', draws: 'more', size: 16 },
  { name: 'a module\'s remove', html: MODULE, width: 1440, sel: '.dash-remove', draws: 'close', size: 16 },
  { name: 'Today\'s add', html: TODAY, width: 1440, sel: 'button.today-plus', draws: 'plus', size: 16 },
  { name: 'Today\'s remove', html: TODAY, width: 1440, sel: '.today-drop', draws: 'close', size: 16 },
  { name: 'the plan\'s add', html: PLAN, width: 1440, sel: '.today-plus', draws: 'plus', size: 16 },
  { name: 'a task\'s fold', html: TASKS, width: 1440, sel: '.t-shut .twisty', draws: 'right', size: 14 },
  { name: 'the drawer\'s caret', html: DRAWER, width: 390, sel: '.g-open .group-caret', glyph: '.caret', draws: 'right', size: 18 },
  { name: 'the drawer\'s Tasks caret', html: DRAWER, width: 390, sel: '.cal-tasks .group-caret', glyph: '.caret', draws: 'right', size: 18 },
  { name: 'the drawer\'s group switch', html: DRAWER, width: 390, sel: '.g-open .group-eye', draws: 'check', size: 18 },
  { name: 'the drawer\'s Tasks switch', html: DRAWER, width: 390, sel: '.cal-tasks .group-eye', draws: 'check', size: 18 },
  { name: 'the drawer\'s rename', html: DRAWER, width: 390, sel: '.g-rename', draws: 'edit', size: 18 },
  { name: 'the drawer\'s delete', html: DRAWER, width: 390, sel: '.g-delete', draws: 'close', size: 18 },
  { name: 'the drawer\'s cancel', html: DRAWER, width: 390, sel: '.g-cancel', draws: 'close', size: 18 },
  { name: 'the drawer\'s list edit', html: DRAWER, width: 390, sel: '.side-edit', draws: 'more', size: 18 },
  { name: 'the phone\'s Today add', html: TODAY, width: 390, sel: 'button.today-plus', draws: 'plus', size: 18 },
  { name: 'the phone\'s Today remove', html: TODAY, width: 390, sel: '.today-drop', draws: 'close', size: 18 },
  { name: 'the phone\'s plan add', html: PLAN, width: 390, sel: '.today-plus', draws: 'plus', size: 18 },
  { name: 'the float\'s pin', html: FLOAT, width: 408, sel: '.focus-pin', draws: 'pin', size: 18 },
  { name: 'the bar\'s caret', html: BAR, width: 390, sel: '.side-mobiletrigger', glyph: '.mb-caret', draws: 'caret', size: 16 },
  { name: 'the bar\'s caret on the narrowest phone', html: BAR, width: 320, sel: '.side-mobiletrigger', glyph: '.mb-caret', draws: 'caret', size: 16 },
  { name: 'Today\'s Start working', html: FOCUS(`&#9654;${icon('play')}`), width: 390, sel: '.today-focus', glyph: '.today-focus__glyph', draws: 'play', size: 18 },
  { name: 'Today\'s Start working on the narrowest phone', html: FOCUS(`&#9654;${icon('play')}`), width: 320, sel: '.today-focus', glyph: '.today-focus__glyph', draws: 'play', size: 18 },
  { name: 'the bar\'s completed', html: BAR, width: 390, sel: '.s-done', draws: 'check', size: 24 },
  { name: 'the bar\'s parked', html: BAR, width: 390, sel: '.s-parked', draws: 'pause', size: 24 },
  { name: 'the bar\'s suggested', html: BAR, width: 390, sel: '.s-sug', draws: 'mail', size: 24 },
  { name: 'the bar\'s add', html: BAR, width: 390, sel: '.side-mobile-add', draws: 'plus', size: 24 },
]

/** The control's mark: its IconInk, or the switch's CheckInk. */
const mark = (b: Element, glyph: Element, draws: string) =>
  glyph.querySelector(draws === 'check' && b.matches('.group-eye') ? ':scope > .check-ink' : `:scope > .icon-ink[data-icon="${draws}"]`)
/** The box the glyph's own text paints. */
const glyphBox = (glyph: Element) => {
  const text = [...glyph.childNodes].find((n) => n.nodeType === Node.TEXT_NODE && n.textContent!.trim())!
  const r = document.createRange()
  r.selectNodeContents(text)
  return r.getBoundingClientRect()
}
const height = (w: number) => (w === 408 ? 268 : 844)

describe('the last glyph controls under Field notes', () => {
  it.each(CONTROLS)('$name draws its mark at $size px and paints no glyph', async ({ html, width, sel, glyph, draws, size }) => {
    await viewport(width, height(width))
    const host = await mount(html)
    const b = host.querySelector(sel)!
    const g = glyph ? b.querySelector(glyph)! : b
    const m = mark(b, g, draws)
    expect(m, `${sel} carries no ${draws}`).not.toBeNull()
    expect(getComputedStyle(m!).display).toBe('block')
    // The un-rotated box: a turned caret's bounding box is the same square.
    expect(box(m!).w).toBeCloseTo(size, 0)
    expect(box(m!).h).toBeCloseTo(size, 0)
    const t = glyphBox(g)
    expect(t.width * t.height, `${sel}'s glyph paints a box`).toBe(0)
  })

  it.each(CONTROLS.filter((c) => c.draws !== 'check' && c.size < 18))(
    '$name keeps the 18px icon\'s line at $size px', async ({ html, width, sel, draws, size }) => {
      await viewport(width, height(width))
      // The three dots are drawn at --stroke-tick, everything else at the pen.
      const token = draws === 'more' ? '--stroke-tick' : '--stroke-pen'
      const host = await mount(`${html}<i class="pen" style="display:block; stroke-width: var(${token})"></i>`)
      const m = host.querySelector(`${sel} .icon-ink[data-icon="${draws}"]`)!
      const pen = parseFloat(getComputedStyle(host.querySelector('.pen')!).strokeWidth)
      // On screen, in px: the stroke in the icon's units, at its size.
      const onScreen = parseFloat(getComputedStyle(m).strokeWidth) * size / 24
      expect(onScreen).toBeCloseTo(pen * 18 / 24, 2)
    })

  it('turns the carets\' and the fold\'s icons with their open rotation', async () => {
    await viewport(1440)
    let host = await mount(SIDE)
    const quarter = (el: Element) => new DOMMatrix(getComputedStyle(el).transform)
    for (const sel of ['.g-open .caret', '.cal-tasks .caret']) {
      const caret = host.querySelector(sel)!
      expect(caret.querySelector(':scope > .icon-ink')).not.toBeNull()
      expect(quarter(caret).b).toBeCloseTo(1, 5)
    }
    expect(getComputedStyle(host.querySelector('.g-shut .caret')!).transform).toBe('none')
    host = await mount(TASKS)
    const fold = host.querySelector('.t-open .twisty')!
    expect(fold.querySelector(':scope > .icon-ink')).not.toBeNull()
    expect(quarter(fold).b).toBeCloseTo(1, 5)
  })

  it('keeps a task\'s fold column exactly 14px wide, so the titles do not move', async () => {
    await viewport(1440)
    const host = await mount(TASKS)
    const title = (sel: string) => box(host.querySelector(`${sel} .task-title`)!).left
    expect(host.querySelector<HTMLElement>('.t-shut .twisty')!.offsetWidth).toBe(14)
    expect(title('.t-shut')).toBe(title('.t-leaf'))
    expect(title('.t-open')).toBe(title('.t-leaf'))
  })

  it('sets the Calendar\'s Tasks caret further from its word, which stays where it was', async () => {
    // The caret's box is its icon's. The word is at 28px in either column, in
    // a head 32px tall (46px in the drawer); the icon's edge was 1px past the
    // word's (desktop) or on it (drawer), and now clears it.
    for (const [html, width, head, gap] of [[SIDE, 1440, 32.25, 0.5], [DRAWER, 390, 46, 1.5]] as const) {
      await viewport(width, height(width))
      const host = await mount(html)
      const word = box(host.querySelector('.cal-tasks .group-name')!)
      const caret = box(host.querySelector('.cal-tasks .group-caret .icon-ink')!)
      expect(Math.abs(word.left - 28), `the word at ${width}`).toBeLessThanOrEqual(0.5)
      expect(Math.abs(box(host.querySelector('.cal-tasks .group-head')!).h - head)).toBeLessThanOrEqual(0.5)
      expect(word.left - caret.right, `the gap at ${width}`).toBeCloseTo(gap, 1)
    }
  })

  it.each([0.8, 1, 1.2, 1.4])('centres a task\'s fold on the check beside it, and keeps the row\'s height, at --fs-scale %f', async (scale) => {
    // 42px in a desktop's row, 48px in a phone's at the default scale, as
    // before; at the others the row is the bare glyph's. The check sits at
    // --today-line / 2, which scales, and the fold's margin follows it.
    const BARE = TASKS.replace(/<svg class="icon-ink".*?<\/svg>/g, '')
    try {
      document.documentElement.style.setProperty('--fs-scale', String(scale))
      for (const [width, h] of [[1440, 42], [390, 48]] as const) {
        await viewport(width, height(width))
        const bare = await mount(BARE)
        const was = ['.t-open', '.t-shut'].map((sel) => box(bare.querySelector(sel)!).h)
        bare.remove()
        const host = await mount(TASKS)
        const mid = (el: Element) => (box(el).top + box(el).bottom) / 2
        ;['.t-open', '.t-shut'].forEach((sel, i) => {
          const off = mid(host.querySelector(`${sel} .twisty .icon-ink`)!) - mid(host.querySelector(`${sel} .check`)!)
          expect(Math.abs(off), `${sel} at ${width}: off by ${off}`).toBeLessThanOrEqual(1)
          expect(box(host.querySelector(sel)!).h, `${sel} at ${width}`).toBe(was[i])
          if (scale === 1) expect(was[i]).toBe(h)
        })
        host.remove()
      }
    } finally {
      document.documentElement.style.removeProperty('--fs-scale')
    }
  })

  it('draws the phone bar\'s caret without moving the trigger or squeezing the summary', async () => {
    // Against the same bar with the bare ▾, which a preset also shows: the
    // trigger is as tall, and the summary at most 1px narrower.
    for (const width of [390, 320]) {
      await viewport(width, height(width))
      for (const summary of ['4 of 6 shown', '12 of 12 shown']) {
        const glyph = await mount(bar('<span class="mb-caret" aria-hidden="true">&#9662;</span>', summary))
        const was = { trig: box(glyph.querySelector('.side-mobiletrigger')!), sum: box(glyph.querySelector('.mb-summary')!) }
        glyph.remove()
        const host = await mount(bar(MB_CARET, summary))
        const now = { trig: box(host.querySelector('.side-mobiletrigger')!), sum: box(host.querySelector('.mb-summary')!) }
        host.remove()
        expect(now.trig.h, `the trigger at ${width}`).toBeCloseTo(was.trig.h, 0)
        expect(now.sum.w, `the summary at ${width}`).toBeGreaterThanOrEqual(was.sum.w - 1)
      }
    }
  })

  it('keeps Start working as wide and as tall with its icon in place of the ▶', async () => {
    // 48.1 x 40px with the glyph, on any phone; the word is hidden.
    for (const width of [390, 320]) {
      await viewport(width, height(width))
      const host = await mount(FOCUS(`&#9654;${icon('play')}`))
      const b = box(host.querySelector('.today-focus')!)
      expect(Math.abs(b.w - 48.1), `the width at ${width}`).toBeLessThanOrEqual(1)
      expect(Math.abs(b.h - 40), `the height at ${width}`).toBeLessThanOrEqual(1)
      expect(getComputedStyle(host.querySelector('.today-focus__word')!).display).toBe('none')
    }
  })

  it.each([0.8, 1, 1.2, 1.4])('centres Start working\'s icon in its button, and keeps the head where it was, at --fs-scale %f', async (scale) => {
    // The button grows with the text scale; the 18px icon has to stay in the
    // middle of it, as the ▶ did, without moving the head or its tools.
    try {
      document.documentElement.style.setProperty('--fs-scale', String(scale))
      await viewport(390, height(390))
      const bare = await mount(FN_HEAD('&#9654;'))
      const was = { head: box(bare.querySelector('#fn-head')!).h, tools: box(bare.querySelector('#fn-tools')!).top }
      bare.remove()
      const host = await mount(FN_HEAD(`&#9654;${icon('play')}`))
      const btn = box(host.querySelector('.today-focus')!)
      const ink = box(host.querySelector('.today-focus .icon-ink')!)
      expect(ink.h, 'the icon is drawn').toBe(18)
      expect(Math.abs((ink.top + ink.h / 2) - (btn.top + btn.h / 2)), `the icon's centre at ${scale}`).toBeLessThanOrEqual(1)
      expect(Math.abs(box(host.querySelector('#fn-head')!).h - was.head), `the head's height at ${scale}`).toBeLessThanOrEqual(1)
      expect(Math.abs(box(host.querySelector('#fn-tools')!).top - was.tools), `the tools' top at ${scale}`).toBeLessThanOrEqual(1)
    } finally {
      document.documentElement.style.removeProperty('--fs-scale')
    }
  })

  it.each([390, 320])('keeps the Field notes head as tall, and its tools where they were, with the icon in place of the ▶ (%ipx)', async (width) => {
    // The head aligns by baseline, so a Start working with no line box of its
    // own would drop its baseline to its bottom edge and move the tools.
    await viewport(width, height(width))
    const bare = await mount(FN_HEAD('&#9654;'))
    const was = { head: box(bare.querySelector('#fn-head')!).h, tools: box(bare.querySelector('#fn-tools')!).top }
    bare.remove()
    const host = await mount(FN_HEAD(`&#9654;${icon('play')}`))
    const now = { head: box(host.querySelector('#fn-head')!).h, tools: box(host.querySelector('#fn-tools')!).top }
    expect(was.head, 'no layout').toBeGreaterThan(0)
    expect(now.head, `the head: ${now.head} against ${was.head}`).toBeCloseTo(was.head, 1)
    expect(now.tools, `the tools: ${now.tools} against ${was.tools}`).toBeCloseTo(was.tools, 1)
  })

  it('ticks a group\'s switch while it is pressed, and undraws it when not', async () => {
    await viewport(1440)
    const host = await mount(SIDE)
    await settle()
    const tick = (sel: string) => getComputedStyle(host.querySelector(`${sel} .check-tick`)!)
    expect(tick('.g-open .group-eye').opacity).toBe('1')
    expect(tick('.g-open .group-eye').strokeDashoffset).toBe('0px')
    expect(tick('.cal-tasks .group-eye').opacity).toBe('1')
    expect(tick('.g-shut .group-eye').opacity).toBe('0')
    // The box says off; the switch is not dimmed as the glyph was.
    expect(getComputedStyle(host.querySelector('.g-shut .group-eye')!).opacity).toBe('1')
  })

  it('puts the highlighter behind the pressed switches and the pressed pin', async () => {
    const on = (host: HTMLElement) => {
      const probe = document.createElement('span')
      probe.style.background = 'var(--ctl-on)'
      host.appendChild(probe)
      const c = paint(getComputedStyle(probe).backgroundColor)
      probe.remove()
      return c
    }
    await viewport(390)
    let host = await mount(BAR)
    expect(paint(getComputedStyle(host.querySelector('.s-done')!).backgroundColor)).toEqual(on(host))
    expect(paint(getComputedStyle(host.querySelector('.s-parked')!).backgroundColor)[3]).toBe(0)
    expect(getComputedStyle(host.querySelector('.s-done')!).color).toBe(getComputedStyle(host.querySelector('.side-mobiletrigger')!).color)
    await viewport(408, 268)
    host = await mount(FLOAT)
    const pin = host.querySelector('.focus-pin')!
    expect(paint(getComputedStyle(pin).backgroundColor)).toEqual(on(host))
    pin.setAttribute('aria-pressed', 'false')
    await settle()
    expect(paint(getComputedStyle(pin).backgroundColor)).not.toEqual(on(host))
  })

  it('keeps the suggested count\'s badge at its size with the glyph hidden', async () => {
    await viewport(390)
    const host = await mount(BAR)
    const badge = host.querySelector('.s-sug .side-badge')!
    expect(getComputedStyle(badge).fontSize).toBe('11px')
    expect(box(badge).w).toBeGreaterThanOrEqual(15)
    expect(box(badge).h).toBeGreaterThanOrEqual(15)
    const r = document.createRange()
    r.selectNodeContents(badge.firstChild!)
    expect(r.getBoundingClientRect().width).toBeGreaterThan(4)
    // Beside the icon, on its line, not under it.
    const i = box(host.querySelector('.s-sug .icon-ink')!)
    expect(box(badge).left).toBeGreaterThanOrEqual(i.right)
    expect(Math.abs((box(badge).top + box(badge).bottom) / 2 - (i.top + i.bottom) / 2)).toBeLessThanOrEqual(1)
  })
})

describe('the last glyph controls under a preset', () => {
  it.each(CONTROLS)('$name shows its glyph and no mark', async ({ html, width, sel, glyph, draws }) => {
    applyDesign(document.documentElement, 'refined')
    await viewport(width, height(width))
    const host = await mount(html)
    const b = host.querySelector(sel)!
    const g = glyph ? b.querySelector(glyph)! : b
    expect(getComputedStyle(mark(b, g, draws)!).display).toBe('none')
    const t = glyphBox(g)
    expect(t.width).toBeGreaterThan(0)
    expect(t.height).toBeGreaterThan(0)
  })
})
