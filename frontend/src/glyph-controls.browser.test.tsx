// The last controls that showed a bare glyph under Field notes, drawn with the
// pen's icons and the check (Marks.tsx), measured in a real browser.
//
// Each keeps its glyph as text, as every icon button does: under Field notes
// the glyph is set at no size and the icon is drawn at its row's size; under a
// preset the icon is not drawn and the glyph shows. The sizes are the rows':
// 24px in the phone bar, 18px in the phone's rows and the Focus float, 16px in
// a desktop's dense rows and 14px in a task's fold, and an icon under 18px
// keeps the 18px icon's line. Raw markup in the shape the components render
// (test/browser-measure.ts); controls-ink.test.ts holds the JSX to carrying the
// icon, and the components' own suites the markup.
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
  pin: ['M12 11C12.1 13.7 11.9 16.5 12 19.2'],
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
const BAR = `<div class="shell"><div class="work"><div class="side-mobilebar">
  <button class="side-mobiletrigger"><span class="mb-title">Lists</span><span class="mb-summary">4 of 6 shown</span><span class="mb-caret">&#9662;</span></button>
  <button class="side-mobile-completed active s-done" aria-pressed="true">&#10003;${icon('check')}</button>
  <button class="side-mobile-completed s-parked" aria-pressed="false">&#9208;${icon('pause')}</button>
  <button class="side-mobile-completed s-sug" aria-pressed="false">&#9993;${icon('mail')}<span class="side-badge">3</span></button>
  <button class="side-mobile-add">+${icon('plus')}</button></div><div class="content"></div></div></div>`
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
