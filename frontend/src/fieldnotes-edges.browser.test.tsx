// Field notes' controls and fields, measured in a real browser.
//
// A secondary control (a ghost button, a settings toggle, the lone view tab, a
// pick, an add, a destructive button) is a FACE: --ctl-face, the ink at 8%
// over whatever ground it sits on, with no edge at rest. Its 3:1 edge
// (--edge-control, which is --rule-strong under Field notes) shows under the
// pointer. Until 22 Nov these controls carried that edge at rest; the owner
// chose the face instead, accepting that the control is then found by its
// face and its word (WCAG 1.4.11 asks for no boundary where the label
// identifies the control). So what this file holds is: the word reads at
// 4.5:1 on its face, the face is visible on its ground, the edge under the
// pointer is 3:1, and a FIELD keeps its 3:1 edge at rest. Every one of those
// is a computed colour, which only a browser reads.

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { userEvent } from 'vitest/browser'
import { mount, over, paint, ratio, settle, viewport, type Paint } from './test/browser-measure'
import { applyDesign } from './appearance'

beforeEach(() => { document.body.innerHTML = '' })
afterEach(() => { applyDesign(document.documentElement, null) })

const THEMES = ['light', 'dark'] as const
const setTheme = (t: (typeof THEMES)[number]) => { document.documentElement.dataset.theme = t }

/** Each control, in the markup it has, with the selector that finds it. */
const CONTROLS: { name: string; html: string; sel: string }[] = [
  { name: '.btn.ghost', html: '<button class="btn ghost">Copy link</button>', sel: '.btn' },
  { name: '.btn.danger', html: '<button class="btn danger">Disconnect</button>', sel: '.btn' },
  { name: '.btn.ghost.danger', html: '<button class="btn ghost danger">Discard</button>', sel: '.btn' },
  { name: '.menu-toggle', html: '<button class="menu-toggle">Light</button>', sel: '.menu-toggle' },
  { name: '.menu-toggle, off', html: '<button class="menu-toggle" aria-pressed="false">Off</button>', sel: '.menu-toggle' },
  { name: '.content-head > .view-tab', html: '<div class="content-head"><button class="view-tab">Arrange</button></div>', sel: '.view-tab' },
  { name: '.col-add', html: '<button class="col-add">+ Add</button>', sel: '.col-add' },
  { name: '.sched-add-range', html: '<button class="sched-add-range">Add range</button>', sel: '.sched-add-range' },
  { name: '.bulk-add-row', html: '<button class="bulk-add-row">Add row</button>', sel: '.bulk-add-row' },
  { name: '.booking-day', html: '<button class="booking-day"><span class="dow">Mon</span><span class="dnum">3</span></button>', sel: '.booking-day' },
  { name: '.slot-btn', html: '<button class="slot-btn">09:00</button>', sel: '.slot-btn' },
  { name: '.habit-day', html: '<button class="habit-day chip">M</button>', sel: '.habit-day' },
]

/** The page, a menu and a modal: the three grounds a control sits on. */
const GROUNDS = [
  { name: 'on the page', wrap: (h: string) => `<div class="shell ground" style="background: var(--bg)">${h}</div>` },
  { name: 'in a .menu', wrap: (h: string) => `<div class="menu ground">${h}</div>` },
  { name: 'in a .modal', wrap: (h: string) => `<div class="modal ground">${h}</div>` },
]

const ground = (host: Element): Paint => {
  const p = paint(getComputedStyle(host.querySelector('.ground')!).backgroundColor)
  // An unpainted holder would pass every comparison against a transparent ground.
  expect(p[3], 'the ground is not painted').toBe(1)
  return p
}

describe('a secondary control under Field notes is a face with no edge at rest', () => {
  for (const theme of THEMES) {
    for (const g of GROUNDS) {
      for (const c of CONTROLS) {
        it(`${c.name} ${g.name}, ${theme}`, async () => {
          setTheme(theme)
          const host = await mount(g.wrap(c.html))
          const el = host.querySelector<HTMLElement>(c.sel)!
          expect(el).toBeInTheDocument()
          const bg = ground(host)
          const s = getComputedStyle(el)

          // No edge at rest: the owner's call of 22 Nov.
          expect(paint(s.borderTopColor)[3], 'an edge at rest').toBe(0)
          // A face, and one you can see on its ground (1.16:1 light, 1.25:1
          // dark when this was written).
          const face = paint(s.backgroundColor)
          expect(face[3], 'no face').toBeGreaterThan(0)
          const onGround = over(face, bg)
          expect(ratio(onGround, bg), 'the face vanishes on its ground').toBeGreaterThanOrEqual(1.1)
          // The word on the face is text: 4.5:1.
          expect(ratio(over(paint(s.color), onGround), onGround), 'the label on its face')
            .toBeGreaterThanOrEqual(4.5)

          // Under the pointer the edge appears, at 3:1 against the ground.
          await userEvent.hover(el)
          await settle()
          const hovered = getComputedStyle(el)
          expect(ratio(over(paint(hovered.borderTopColor), bg), bg), 'the edge under the pointer')
            .toBeGreaterThanOrEqual(3)
          await userEvent.unhover(el)
        })
      }
    }
  }
})

describe('what is on or chosen wears the highlighter, behind ink', () => {
  for (const theme of THEMES) {
    it(`a toggle that is on, ${theme}`, async () => {
      setTheme(theme)
      const host = await mount('<div class="shell ground" style="background: var(--bg)">'
        + '<button class="menu-toggle" aria-pressed="true">On</button>'
        + '<i class="hl" style="display:block; background: var(--highlight)"></i></div>')
      const el = host.querySelector('.menu-toggle')!
      const mark = paint(getComputedStyle(el, '::before').backgroundColor)
      expect(mark).toEqual(paint(getComputedStyle(host.querySelector('.hl')!).backgroundColor))
      expect(ratio(over(paint(getComputedStyle(el).color), mark), mark)).toBeGreaterThanOrEqual(4.5)
    })

    it(`a chosen booking day, ${theme}`, async () => {
      setTheme(theme)
      const host = await mount('<div class="shell ground" style="background: var(--bg)">'
        + '<button class="booking-day active"><span class="dow">Mon</span><span class="dnum">3</span></button>'
        + '<i class="hl" style="display:block; background: var(--highlight)"></i></div>')
      const s = getComputedStyle(host.querySelector('.booking-day')!)
      const fill = paint(s.backgroundColor)
      expect(fill).toEqual(paint(getComputedStyle(host.querySelector('.hl')!).backgroundColor))
      expect(ratio(over(paint(s.color), fill), fill)).toBeGreaterThanOrEqual(4.5)
      // The weekday above the date is quiet text elsewhere; on the highlighter it is ink.
      const dow = getComputedStyle(host.querySelector('.booking-day .dow')!)
      expect(ratio(over(paint(dow.color), fill), fill)).toBeGreaterThanOrEqual(4.5)
    })

    // The general hover rule (a face and an edge) is (0,5,0); a chosen pick's own
    // hover rule has to be that and later, or the pointer takes the highlighter off.
    it.each([
      ['a hovered chosen booking day', '<button class="booking-day active"><span class="dow">Mon</span><span class="dnum">3</span></button>', '.booking-day'],
      ['a hovered ticked habit day', '<button class="habit-day chip on">M</button>', '.habit-day'],
    ])(`%s keeps the highlighter and has no edge, ${theme}`, async (_name, html, sel) => {
      setTheme(theme)
      const host = await mount('<div class="shell ground" style="background: var(--bg)">' + html
        + '<i class="hl" style="display:block; background: var(--ctl-on)"></i></div>')
      const el = host.querySelector<HTMLElement>(sel)!
      const on = paint(getComputedStyle(host.querySelector('.hl')!).backgroundColor)
      expect(on[3], 'the highlighter is painted').toBeGreaterThan(0)
      await userEvent.hover(el)
      await settle()
      const s = getComputedStyle(el)
      expect(paint(s.backgroundColor), 'the highlighter under the pointer').toEqual(on)
      expect(paint(s.borderTopColor)[3], 'an edge under the pointer').toBe(0)
      await userEvent.unhover(el)
    })
  }
})

describe('a field keeps its 3:1 edge at rest', () => {
  const FIELDS = [
    { name: '.input', html: '<input class="input" />', sel: '.input' },
    { name: 'select.input', html: '<select class="input"><option>Work</option></select>', sel: 'select' },
    { name: '.tag-input', html: '<div class="tag-input"><input class="input" /></div>', sel: '.tag-input' },
  ]
  for (const theme of THEMES) {
    for (const g of GROUNDS) {
      for (const f of FIELDS) {
        it(`${f.name} ${g.name}, ${theme}`, async () => {
          setTheme(theme)
          const host = await mount(g.wrap(f.html))
          const bg = ground(host)
          const edge = paint(getComputedStyle(host.querySelector(f.sel)!).borderTopColor)
          expect(ratio(over(edge, bg), bg)).toBeGreaterThanOrEqual(3)
        })
      }
    }
  }
})

describe('the face stays out of the presets', () => {
  it('.menu-toggle keeps the --rule hairline under refined', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(
      '<button class="menu-toggle">Light</button>'
      + '<i class="probe" style="display:block; border: 1px solid var(--rule)"></i>')
    const edge = getComputedStyle(host.querySelector('.menu-toggle')!).borderTopColor
    const rule = getComputedStyle(host.querySelector('.probe')!).borderTopColor
    expect(edge).toBe(rule)
  })

  it('.btn.ghost has no face under refined', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount('<button class="btn ghost">Copy link</button>')
    expect(paint(getComputedStyle(host.querySelector('.btn')!).backgroundColor)[3]).toBe(0)
  })

  it('and under Field notes it has one', async () => {
    const host = await mount('<button class="btn ghost">Copy link</button>')
    expect(paint(getComputedStyle(host.querySelector('.btn')!).backgroundColor)[3]).toBeGreaterThan(0)
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

describe('an icon button', () => {
  it('is a --control-h square beside a view\'s Today, and a 32px one on a phone', async () => {
    // Under 721px a 32px square with a 44px tap box (calendar-head.browser.test.tsx),
    // so the month title fits at 320px.
    for (const [w, side] of [[1280, 40], [390, 32]]) {
      document.body.innerHTML = ''
      await viewport(w)
      const host = await mount(
        '<div class="cal-head"><button class="icon-btn">&#8249;</button><button class="icon-btn">&#8250;</button></div>')
      const r = host.querySelector('.cal-head > .icon-btn')!.getBoundingClientRect()
      if (w > 720) {
        expect(r.width, `${w}px`).toBeGreaterThanOrEqual(side)
        expect(r.height, `${w}px`).toBeGreaterThanOrEqual(side)
      } else {
        expect(r.width, `${w}px`).toBe(side)
        expect(r.height, `${w}px`).toBe(side)
      }
    }
  })

  it('has no edge at rest', async () => {
    const host = await mount('<div class="shell"><button class="icon-btn" aria-label="Close">&#10005;</button></div>')
    expect(paint(getComputedStyle(host.querySelector('.icon-btn')!).borderTopColor)[3]).toBe(0)
  })

  it('looks disabled when it is, and takes no hover', async () => {
    const host = await mount('<div class="shell">'
      + '<button class="icon-btn" aria-label="Next day" disabled>&#8250;</button>'
      + '<i class="faint" style="color: var(--fg-faint)"></i></div>')
    const el = host.querySelector<HTMLElement>('.icon-btn')!
    const faint = getComputedStyle(host.querySelector('.faint')!).color
    expect(getComputedStyle(el).color).toBe(faint)
    await userEvent.hover(el, { force: true })
    await settle()
    expect(paint(getComputedStyle(el).backgroundColor)[3], 'a disabled button filled under the pointer').toBe(0)
    await userEvent.unhover(el, { force: true })
  })
})

describe('the sign-in card', () => {
  for (const theme of THEMES) {
    it(`has an input whose edge is at least 3:1, ${theme}`, async () => {
      setTheme(theme)
      const host = await mount('<div class="login-card"><input class="input" /></div>')
      const bg = paint(getComputedStyle(host.querySelector('.login-card')!).backgroundColor)
      const edge = paint(getComputedStyle(host.querySelector('.login-card .input')!).borderTopColor)
      expect(ratio(over(edge, bg), bg)).toBeGreaterThanOrEqual(3)
    })
  }
})
