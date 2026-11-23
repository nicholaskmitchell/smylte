// The pen's icons (Marks.tsx, IconInk), measured in a real browser: drawn at
// 24px with the pen under Field notes, and not drawn at all under a preset,
// which keeps the glyph beside it.
import { beforeEach, describe, expect, it } from 'vitest'
import { applyDesign } from './appearance'
import { box, mount } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const ICON = '<svg class="icon-ink" data-icon="close" viewBox="0 0 24 24" aria-hidden="true">'
  + '<path d="M6.6 6.4C9.8 9.4 14.2 14 17.6 17.4"/><path d="M17.4 6.5C14.3 9.6 9.9 14.2 6.5 17.5"/></svg>'
const HOME = '<svg class="day-home-ink" viewBox="0 0 21 14" aria-hidden="true">'
  + '<path d="M1.6 7.4c5.8-.5 11.9-.4 17.6.2"/><path d="M14.4 2.6c1.8 1.6 3.5 3.1 5 4.9-1.6 1.6-3.3 3.1-5.1 4.6"/></svg>'

describe('the pen\'s icons', () => {
  it('are drawn at 24px in the pen, in the colour of what carries them, under Field notes', async () => {
    const host = await mount(`<div class="shell" style="color: var(--accent)">${ICON}${HOME}
      <i class="pen" style="display:block; stroke-width: var(--stroke-pen); color: var(--accent)"></i></div>`)
    const icon = host.querySelector('.icon-ink')!
    expect(box(icon).w).toBe(24)
    expect(box(icon).h).toBe(24)
    const s = getComputedStyle(icon)
    const pen = getComputedStyle(host.querySelector('.pen')!)
    expect(s.strokeWidth).toBe(pen.strokeWidth)
    expect(s.stroke).toBe(pen.color)
    expect(s.fill).toBe('none')
    expect(s.strokeLinecap).toBe('round')
    expect(box(host.querySelector('.day-home-ink')!).w).toBe(21)
  })

  it('are not drawn under a preset', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(`<div class="shell">${ICON}${HOME}</div>`)
    expect(getComputedStyle(host.querySelector('.icon-ink')!).display).toBe('none')
    expect(getComputedStyle(host.querySelector('.day-home-ink')!).display).toBe('none')
  })
})

const CLOSE = '&#10005;' + ICON
/** A row, as every icon button sits in one: a block parent would stretch it. */
const row = (html: string) => `<div class="shell"><div style="display: flex">${html}</div></div>`

describe('an icon button that carries its icon', () => {
  it('shows the icon in a --control-h square and paints no glyph', async () => {
    const host = await mount(row(`<button class="icon-btn" aria-label="Close">${CLOSE}</button>`))
    const b = host.querySelector('.icon-btn')!
    expect(getComputedStyle(b).fontSize).toBe('0px')
    expect(box(b).w).toBeCloseTo(40, 0)
    expect(box(b).h).toBeCloseTo(40, 0)
    const i = box(b.querySelector('.icon-ink')!)
    expect(i.w).toBe(24)
    expect(Math.abs(i.top + i.h / 2 - (box(b).top + box(b).h / 2))).toBeLessThanOrEqual(0.5)
  })

  it.each(['bulk-row', 'sched-range', 'day-pop-head'])('keeps a 32px square and an 18px icon in a .%s', async (row) => {
    const host = await mount(`<div class="shell"><div class="${row}"><button class="icon-btn" aria-label="Remove">${CLOSE}</button></div></div>`)
    const b = host.querySelector('.icon-btn')!
    expect(box(b).w).toBeCloseTo(32, 0)
    expect(box(b.querySelector('.icon-ink')!).w).toBe(18)
  })

  it('sits centred on a dialog\'s head, which aligns on the baseline', async () => {
    const host = await mount('<div class="overlay"><div class="modal"><div class="modal-head">'
      + `<span class="modal-title">Edit task</span><button class="icon-btn" aria-label="Close">${CLOSE}</button>`
      + '</div></div></div>')
    const head = box(host.querySelector('.modal-head')!)
    const b = box(host.querySelector('.modal-head > .icon-btn')!)
    expect(Math.abs(b.top + b.h / 2 - (head.top + head.h / 2))).toBeLessThanOrEqual(1)
  })

  it('makes the Today line\'s ⋯ an icon square with no face', async () => {
    const host = await mount(row('<button type="button" class="btn ghost today-menu-btn mono" aria-label="More actions">'
      + '&#183;&#183;&#183;<svg class="icon-ink" data-icon="more" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.2 12.1h.1"/></svg></button>'))
    const b = host.querySelector<HTMLElement>('.today-menu-btn')!
    const s = getComputedStyle(b)
    expect(s.fontSize).toBe('0px')
    expect(s.backgroundColor).toBe('rgba(0, 0, 0, 0)')
    expect(box(b).w).toBeCloseTo(40, 0)
  })

  it('shows its glyph and no icon under a preset', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(row(`<button class="icon-btn" aria-label="Close">${CLOSE}</button>`))
    const b = host.querySelector('.icon-btn')!
    expect(parseFloat(getComputedStyle(b).fontSize)).toBeGreaterThan(0)
    expect(getComputedStyle(b.querySelector('.icon-ink')!).display).toBe('none')
  })
})
