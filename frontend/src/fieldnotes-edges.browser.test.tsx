// Field notes' shared control edges, measured in a real browser.
//
// --rule is a 1.3:1 hairline: right for a divider, too faint for the edge of a
// control, which has to be found by eye. tokens.css points --edge-control at
// --rule-strong under Field notes, and the controls here named their border by
// --rule, so they keep the hairline until fieldnotes.css says otherwise. What
// that rule changes is a computed colour, which only a browser reads.

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mount, viewport } from './test/browser-measure'
import { applyDesign } from './appearance'
import { contrast } from './contrast'

beforeEach(() => { document.body.innerHTML = '' })
afterEach(() => { applyDesign(document.documentElement, null) })

const THEMES = ['light', 'dark'] as const
const setTheme = (t: (typeof THEMES)[number]) => { document.documentElement.dataset.theme = t }

/** Each control, in the markup it has, with the selector that finds it. */
const CONTROLS: { name: string; html: string; sel: string }[] = [
  { name: '.menu-toggle', html: '<button class="menu-toggle">Light</button>', sel: '.menu-toggle' },
  { name: '.content-head > .view-tab', html: '<div class="content-head"><button class="view-tab">Arrange</button></div>', sel: '.view-tab' },
  { name: '.col-add', html: '<button class="col-add">+ Add</button>', sel: '.col-add' },
  { name: '.sched-add-range', html: '<button class="sched-add-range">Add range</button>', sel: '.sched-add-range' },
  { name: '.bulk-add-row', html: '<button class="bulk-add-row">Add row</button>', sel: '.bulk-add-row' },
  { name: '.booking-day', html: '<button class="booking-day"><span class="dow">Mon</span><span class="dnum">3</span></button>', sel: '.booking-day' },
  { name: '.slot-btn', html: '<button class="slot-btn">09:00</button>', sel: '.slot-btn' },
  { name: '.habit-day', html: '<button class="habit-day">M</button>', sel: '.habit-day' },
]

/** The edge of `el` and the colour of the ground it sits on, as the browser
 *  computed them. */
const edgeAndGround = (el: Element, ground: Element) => ({
  edge: getComputedStyle(el).borderTopColor,
  ground: getComputedStyle(ground).backgroundColor,
})

describe('control edges under Field notes are at least 3:1', () => {
  for (const theme of THEMES) {
    for (const c of CONTROLS) {
      it(`${c.name} on the page, ${theme}`, async () => {
        setTheme(theme)
        const host = await mount(`<div class="shell" style="background: var(--bg)">${c.html}</div>`)
        const el = host.querySelector(c.sel)!
        expect(el).toBeInTheDocument()
        const { edge, ground } = edgeAndGround(el, host.querySelector('.shell')!)
        expect(contrast(edge, ground)).toBeGreaterThanOrEqual(3)
      })
      for (const holder of ['menu', 'modal']) {
        it(`${c.name} in a .${holder}, ${theme}`, async () => {
          setTheme(theme)
          const host = await mount(`<div class="${holder}">${c.html}</div>`)
          const el = host.querySelector(c.sel)!
          expect(el).toBeInTheDocument()
          const ground = host.querySelector(`.${holder}`)!
          const { edge, ground: bg } = edgeAndGround(el, ground)
          // The ground is the float colour, not the page's: an unpainted
          // holder would pass every comparison against a transparent ground.
          const float = host.appendChild(document.createElement('i'))
          float.style.background = 'var(--bg-float)'
          expect(bg).toBe(getComputedStyle(float).backgroundColor)
          expect(contrast(edge, bg)).toBeGreaterThanOrEqual(3)
        })
      }
    }
  }
})

describe('the shared edges stay out of the presets', () => {
  it('.menu-toggle keeps the --rule hairline under refined', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(
      '<button class="menu-toggle">Light</button>'
      + '<i class="probe" style="display:block; border: 1px solid var(--rule)"></i>')
    const edge = getComputedStyle(host.querySelector('.menu-toggle')!).borderTopColor
    const rule = getComputedStyle(host.querySelector('.probe')!).borderTopColor
    expect(edge).toBe(rule)
  })

  it('and under Field notes it does not', async () => {
    const host = await mount(
      '<button class="menu-toggle">Light</button>'
      + '<i class="probe" style="display:block; border: 1px solid var(--rule)"></i>')
    const edge = getComputedStyle(host.querySelector('.menu-toggle')!).borderTopColor
    const rule = getComputedStyle(host.querySelector('.probe')!).borderTopColor
    expect(edge).not.toBe(rule)
  })
})

describe("a view header's count", () => {
  const HEAD = '<div class="content-head"><h1 class="content-title">Tasks</h1><span class="content-sub">12 open</span></div>'

  it('is an italic margin note in Newsreader under Field notes', async () => {
    const host = await mount(HEAD)
    const s = getComputedStyle(host.querySelector('.content-sub')!)
    expect(s.fontStyle).toBe('italic')
    expect(s.fontFamily).toMatch(/Newsreader/)
  })

  it('is not italic under refined', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(HEAD)
    const s = getComputedStyle(host.querySelector('.content-sub')!)
    expect(s.fontStyle).not.toBe('italic')
  })
})

describe('‹ › beside a view\'s Today', () => {
  it('is a square button on a desktop width', async () => {
    await viewport(1280)
    const host = await mount(
      '<div class="cal-head"><button class="icon-btn">&#8249;</button><button class="icon-btn">&#8250;</button></div>')
    const w = host.querySelector('.cal-head > .icon-btn')!.getBoundingClientRect().width
    expect(w).toBeGreaterThanOrEqual(40)
  })
})

describe('the sign-in card', () => {
  for (const theme of THEMES) {
    it(`has an input whose edge is at least 3:1, ${theme}`, async () => {
      setTheme(theme)
      const host = await mount('<div class="login-card"><input class="input" /></div>')
      const { edge, ground } = edgeAndGround(
        host.querySelector('.login-card .input')!, host.querySelector('.login-card')!)
      expect(contrast(edge, ground)).toBeGreaterThanOrEqual(3)
    })
  }
})
