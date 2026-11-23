// The share page under Field notes, measured in a real browser: the 13px
// floor, the header, the flat sections, the chevron, and no sideways scroll at
// 320px. Fixture markup is class-for-class `SharePage.tsx` under Field notes,
// held to the real JSX by `PublicPages.fieldnotes.test.tsx`.
import { beforeEach, describe, expect, it } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const LONG = 'W'.repeat(200)

const MARK = `<span class="share-row__mark" aria-hidden="true"><svg class="check-ink" viewBox="0 0 28 28" aria-hidden="true" focusable="false"><path class="check-frame" d="M4 4L24 5L23 24L5 23Z"/><path class="check-tick ink" pathLength="1" d="M8.6 14.6C10 15.8 11.4 17.6 12.4 19C14.6 14.4 18.6 9.2 23.8 5.8"/></svg></span>`

const DOT = '<span class="share-live__dot" style="animation: none"></span>'
const LINE = 'M2 5.2C60 4.1 118 6 176 4.9C234 3.9 270 5.6 318 4.8'
const CHEV = '<svg class="icon-ink share-list__chev" data-icon="right" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9.4 6.1C11.4 8.1 13.4 10.1 15 12C13.3 13.9 11.3 15.9 9.2 17.8"/></svg>'
const HEAD = `
      <header class="share-head">
        <div class="share-head__text" id="head-text">
          <h1 class="share-head__title">Shared with you</h1>
          <div class="share-head__day"><span class="share-head__weekday">Wednesday</span> <span class="share-head__date" id="date">Sep 30</span></div>
          <div class="share-head__meta"><span class="share-live">${DOT}Live</span><span class="share-sep" aria-hidden="true">·</span><span class="share-readonly">Read-only</span></div>
        </div>
      </header>`
const FOCUS = `
      <section class="share-card share-presence" data-state="focusing" data-phase="focus">
        <div class="share-presence__eyebrow">Focusing</div>
        <div class="share-presence__clock" id="clock">1:02:03</div>
        <span class="share-sr">62 minutes left</span>
        <svg class="share-line" viewBox="0 0 320 10" preserveAspectRatio="none" aria-hidden="true"><path class="share-line__rule" d="${LINE}"/><path class="share-line__ink" pathLength="1" d="${LINE}" stroke-dashoffset="0.6"/></svg>
        <div class="share-now"><div class="share-now__label">Working on</div><h2 class="share-now__title" id="now"><span class="share-now__ink">${LONG}</span></h2></div>
        <p class="share-then"><span class="share-then__label">Then</span> <span class="share-then__text">Call the printer</span></p>
      </section>`
const REST = `
      <section class="share-today share-section">
        <div class="share-today__head"><span class="share-label">Today</span><span class="share-today__count">1 of 3 done</span></div>
        <ul class="share-rows">
          <li class="share-row is-now" id="open">${MARK}<span class="share-row__text" id="open-text"><span class="share-row__name">Draft the memo</span></span><span class="share-row__due">Today 3:00 PM</span></li>
          <li class="share-row is-done" id="done">${MARK}<span class="share-row__text"><span class="share-row__name">Email Sam</span><span class="share-sr"> done</span></span></li>
          <li class="share-row" id="long">${MARK}<span class="share-row__text" id="long-text"><span class="share-row__name">${LONG}</span></span><span class="share-row__due">Today 3:00 PM</span></li>
        </ul>
      </section>
      <section class="share-agenda share-section">
        <div class="share-label">Coming up</div>
        <div class="share-day"><h2 class="share-day__label">Today</h2><ul class="share-evs">
          <li class="share-ev is-past" id="past"><time class="share-ev__time">9:00 AM–9:30 AM</time><span class="share-ev__dot" aria-hidden="true"></span><span class="share-ev__title">Standup</span></li>
          <li class="share-ev is-now"><time class="share-ev__time">10:00 AM–11:30 AM</time><span class="share-ev__dot" aria-hidden="true"></span><span class="share-ev__title" id="ev">${LONG}</span><span class="share-ev__now">Now</span></li>
        </ul></div>
      </section>
      <details class="share-list share-section" open id="open-list">
        <summary class="share-list__sum"><span class="share-list__dot" aria-hidden="true"></span><span class="share-list__name" id="list">${LONG}</span><span class="share-list__count">12</span>${CHEV}</summary>
        <ul class="share-tasks"><li class="share-task" data-depth="3"><span class="share-task__text" id="task">${LONG}</span><span class="share-task__due is-late">Due Oct 20</span></li></ul>
        <p class="share-more">and 4 more</p>
      </details>
      <details class="share-list share-section" id="shut-list">
        <summary class="share-list__sum"><span class="share-list__dot" aria-hidden="true"></span><span class="share-list__name">Home</span><span class="share-list__count">2</span>${CHEV}</summary>
      </details>
      <footer class="share-foot"><button class="btn ghost" aria-pressed="false">Keep screen on</button></footer>`
const DRAWING = '<svg class="day-drawing share-drawing" id="drawing" viewBox="0 0 160 200" aria-hidden="true"></svg>'
const PAGE = `<div class="share-wrap share-wrap--board"><main class="share share--board">
  <div class="share-side">${HEAD.replace('<header class="share-head">', '<header class="share-head share-head--drawn">').replace('</header>', `${DRAWING}</header>`)}${FOCUS}</div>
  <div class="share-main">${REST}</div></main></div>`

describe('the share page’s rows under Field notes', () => {
  it('is a real browser with the app’s stylesheet and fonts loaded', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    expect(box(host.querySelector('#open-text')!).h, 'no layout — this is not a browser').toBeGreaterThan(0)
    expect(document.fonts.check('12px "Newsreader"'), 'Newsreader did not load').toBe(true)
  })

  it('hides the tick on an open row and shows it on a done one', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    const tick = (id: string) => host.querySelector(`#${id} .check-tick`)!
    expect(getComputedStyle(tick('open')).opacity).toBe('0')
    expect(getComputedStyle(tick('done')).opacity).toBe('1')
  })

  it('draws the mark with no border and no fill of its own', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    for (const id of ['open', 'done']) {
      const mark = getComputedStyle(host.querySelector(`#${id} .share-row__mark`)!)
      expect(mark.borderTopWidth, `#${id} mark has a border`).toBe('0px')
      expect(mark.backgroundColor, `#${id} mark has a fill`).toBe('rgba(0, 0, 0, 0)')
    }
  })

  it('sets the title in Newsreader at 20px, and a done one without a line-through', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    const text = getComputedStyle(host.querySelector('#open-text')!)
    expect(text.fontFamily.split(',')[0].replace(/["']/g, '').trim()).toBe('Newsreader')
    expect(text.fontSize).toBe('20px')
    expect(getComputedStyle(host.querySelector('#done .share-row__text')!).textDecorationLine).toBe('none')
  })

  it('sets nothing under the 13px floor', async () => {
    for (const width of [390, 320]) {
      await viewport(width)
      const host = await mount(PAGE)
      const offenders: string[] = []
      for (const el of host.querySelectorAll('main.share *')) {
        if (el.closest('.share-sr')) continue
        const own = [...el.childNodes].some((n) => n.nodeType === Node.TEXT_NODE && n.textContent!.trim() !== '')
        if (!own) continue
        const size = parseFloat(getComputedStyle(el).fontSize)
        if (size < 13) offenders.push(`${el.className || el.tagName} ${size}px at ${width}`)
      }
      expect(offenders).toEqual([])
      host.remove()
    }
  })

  it('sets the header as Today’s', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    const style = (sel: string) => getComputedStyle(host.querySelector(sel)!)
    expect(style('#date').fontSize).toBe('52px')
    expect(style('.share-head__weekday').fontSize).toBe('22px')
    expect(style('.share-head__weekday').fontStyle).toBe('italic')
    for (const sel of ['.share-sep', '.share-live', '.share-readonly']) {
      expect(style(sel).fontSize, sel).toBe('14px')
    }
    expect(style('.share-readonly').borderTopWidth).toBe('0px')
  })

  it('turns the chevron of an open list, and keeps the past in the muted tier', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    const style = (sel: string) => getComputedStyle(host.querySelector(sel)!)
    expect(style('#open-list .share-list__chev').rotate).toBe('90deg')
    expect(style('#shut-list .share-list__chev').rotate).toBe('none')
    expect(style('#past').opacity).toBe('1')
    const chev = box(host.querySelector('.share-list__chev')!)
    expect([chev.w, chev.h]).toEqual([24, 24])
  })

  it('lays Today, the agenda and the lists flat', async () => {
    await viewport(390)
    const host = await mount(PAGE)
    for (const sel of ['.share-today', '.share-agenda', '.share-list']) {
      const style = getComputedStyle(host.querySelector(sel)!)
      expect(style.borderTopWidth, sel).toBe('0px')
      expect(style.backgroundColor, sel).toBe('rgba(0, 0, 0, 0)')
    }
    const row = getComputedStyle(host.querySelector('.share-row')!)
    expect(row.borderBottomWidth).toBe('0px')
    expect(row.borderLeftWidth).toBe('0px')
  })

  describe.each([320, 390])('at %ipx', (width) => {
    it('does not scroll sideways, and wraps every long title in its own block', async () => {
      await viewport(width)
      const host = await mount(PAGE)
      const wrap = host.querySelector('.share-wrap')!
      expect(wrap.scrollWidth, `the page widened to ${wrap.scrollWidth}`).toBeLessThanOrEqual(wrap.clientWidth)
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth)
      for (const id of ['now', 'long-text', 'ev', 'list', 'task']) {
        const el = host.querySelector(`#${id}`)!
        const block = el.closest('.share-card, .share-section')!
        expect(box(el).right, `#${id} runs past its block`).toBeLessThanOrEqual(box(block).right + 0.5)
      }
    })
  })

  it('keeps the clock on one line inside its card past an hour', async () => {
    await viewport(320)
    const host = await mount(PAGE)
    const clock = host.querySelector('#clock')!
    const card = clock.closest('.share-card')!
    const size = parseFloat(getComputedStyle(clock).fontSize)
    // `line-height: 1`: one line is the font size tall, two would be double.
    expect(box(clock).h, 'the clock wrapped').toBeLessThan(size * 1.5)
    expect(clock.scrollWidth).toBeLessThanOrEqual(clock.clientWidth + 1)
    expect(box(clock).right).toBeLessThanOrEqual(box(card).right)
  })
})

describe('the share board', () => {
  const frame = () => new Promise(requestAnimationFrame)

  it('sets the drawing beside the date on a phone, and scrolls nothing sideways at 320', async () => {
    await viewport(390, 844)
    const host = await mount(PAGE)
    const drawing = box(host.querySelector('#drawing')!)
    expect([drawing.w, drawing.h]).toEqual([128, 160])
    expect(drawing.left).toBeGreaterThanOrEqual(box(host.querySelector('#head-text')!).right)
    host.remove()

    await viewport(320, 568)
    const narrow = await mount(PAGE)
    const wrap = narrow.querySelector('.share-wrap')!
    expect(wrap.scrollWidth, `the page widened to ${wrap.scrollWidth}`).toBeLessThanOrEqual(wrap.clientWidth)
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth)
  })

  it('draws the drawing larger from 721px, still in one column', async () => {
    await viewport(800, 900)
    const host = await mount(PAGE)
    const drawing = box(host.querySelector('#drawing')!)
    expect([drawing.w, drawing.h]).toEqual([192, 240])
    expect(getComputedStyle(host.querySelector('main.share--board')!).display).toBe('flex')
  })

  it('keeps one column at 1023px, the owner’s day over the rest', async () => {
    await viewport(1023, 900)
    const host = await mount(PAGE)
    expect(getComputedStyle(host.querySelector('main.share--board')!).display).toBe('flex')
    const side = box(host.querySelector('.share-side')!)
    const mainCol = box(host.querySelector('.share-main')!)
    expect(side.bottom).toBeLessThanOrEqual(mainCol.top + 0.5)
  })

  it('is a board of two columns at 1440px, the drawing standing over the date', async () => {
    await viewport(1440, 900)
    const host = await mount(PAGE)
    expect(getComputedStyle(host.querySelector('main.share--board')!).display).toBe('grid')
    const side = box(host.querySelector('.share-side')!)
    const mainCol = box(host.querySelector('.share-main')!)
    expect(side.w).toBe(400)
    expect(side.right).toBeLessThanOrEqual(mainCol.left)
    const drawing = box(host.querySelector('#drawing')!)
    expect([drawing.w, drawing.h]).toEqual([224, 280])
    expect(drawing.bottom).toBeLessThanOrEqual(box(host.querySelector('#head-text')!).top)

    const clock = host.querySelector('#clock')!
    const card = clock.closest('.share-card')!
    expect(getComputedStyle(clock).fontSize).toBe('96px')
    const size = parseFloat(getComputedStyle(clock).fontSize)
    // `line-height: 1`: one line is the font size tall, two would be double.
    expect(box(clock).h, 'the clock wrapped').toBeLessThan(size * 1.5)
    expect(clock.scrollWidth).toBeLessThanOrEqual(clock.clientWidth + 1)
    expect(box(clock).right).toBeLessThanOrEqual(box(card).right)

    const offenders: string[] = []
    for (const el of host.querySelectorAll('main.share *')) {
      if (el.closest('.share-sr')) continue
      const own = [...el.childNodes].some((n) => n.nodeType === Node.TEXT_NODE && n.textContent!.trim() !== '')
      if (!own) continue
      const px = parseFloat(getComputedStyle(el).fontSize)
      if (px < 13) offenders.push(`${el.className || el.tagName} ${px}px`)
    }
    expect(offenders).toEqual([])
  })

  it('holds the left column in view while the right one scrolls, on a window tall enough', async () => {
    await viewport(1440, 900)
    const host = await mount(PAGE)
    host.querySelector('.share-main')!.insertAdjacentHTML('beforeend', '<div style="height: 1600px"></div>')
    await frame()
    document.scrollingElement!.scrollTop = 300
    await frame()
    expect(document.scrollingElement!.scrollTop, 'the page did not scroll').toBe(300)
    expect(Math.abs(box(host.querySelector('.share-side')!).top - 28)).toBeLessThanOrEqual(1)
    expect(getComputedStyle(host.querySelector('.share-wrap')!).overflowY).toBe('visible')
    document.scrollingElement!.scrollTop = 0
  })

  it('lets the left column scroll away on a shorter window', async () => {
    await viewport(1440, 760)
    const host = await mount(PAGE)
    host.querySelector('.share-main')!.insertAdjacentHTML('beforeend', '<div style="height: 1600px"></div>')
    await frame()
    document.scrollingElement!.scrollTop = 300
    await frame()
    expect(document.scrollingElement!.scrollTop, 'the page did not scroll').toBe(300)
    const side = host.querySelector('.share-side')!
    expect(getComputedStyle(side).position).toBe('static')
    expect(box(side).top).toBeLessThan(0)
    document.scrollingElement!.scrollTop = 0
  })

  it('is Field notes only', async () => {
    await viewport(1440, 900)
    delete document.documentElement.dataset.surface
    const host = await mount(PAGE)
    expect(getComputedStyle(host.querySelector('main.share--board')!).display).not.toBe('grid')
  })
})

describe('Display mode under Field notes', () => {
  it('keeps a 44px tap height on the mode switch', async () => {
    // A tablet you tap to check things off: the presets' buttons are 44px
    // (app.css .dmode-bar .btn), and the segmented switch keeps that height.
    const host = await mount(`
      <div class="dmode-bar">
        <div class="view-tabs" style="--n: 3; --i: 0">
          <button type="button" class="view-tab active" aria-pressed="true">Today</button>
          <button type="button" class="view-tab" aria-pressed="false">Tasks</button>
          <button type="button" class="view-tab" aria-pressed="false">Calendar</button>
        </div>
      </div>`)
    for (const b of host.querySelectorAll<HTMLElement>('.view-tab')) {
      expect(b.getBoundingClientRect().height, b.textContent!).toBeGreaterThanOrEqual(44)
    }
  })
})
