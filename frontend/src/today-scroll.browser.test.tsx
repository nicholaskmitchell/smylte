// Today scrolls as one page under Field notes, measured in a real browser.
//
// The owner, 22 Nov: "Today page only scrolls the list and not the whole page,
// so on something like a phone only the bottom third scrolls." The date, the
// day's drawing, the focus card and the Today line stood over `.scroll`, the
// pane's only scroller, which got what they left: 376px of an 844px phone
// (303px with the composer open), its own 42px of padding at 320x568, and 351px
// of a 1440x900 window. Measured in the running app before the fix.
//
// Raw markup in the shape TodayView renders under the sidebar layout, class for
// class (held to the JSX by `mobile-layout.test.ts`). The scroller is FOUND
// rather than named: the nearest ancestor of a row whose overflow-y scrolls, so
// the test asks what a finger would move and not which element a rule names.

import { beforeEach, describe, expect, it } from 'vitest'
import { applyDesign } from './appearance'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => {
  document.body.innerHTML = ''
  document.documentElement.dataset.surface = 'app'
})

const ROW = (i: number) => `
  <li class="today-row"><button class="check">&#10003;</button><span class="today-title">Task ${i}</span></li>`
const AGENDA = `<div class="label section-label">On the calendar</div>
  <div class="today-agenda"><div class="agenda-ev"><span class="t">9:00</span><span>Standup</span></div></div>`
const MENU = `<div class="today-menu"><button type="button" class="today-menu-item">Review</button>
  <button type="button" class="today-menu-item">Shut down</button>
  <button type="button" class="today-menu-item">Habits</button></div>`

/** Today's pane: the head with the date and the drawing, the focus card, the
 *  Today line, the list (and the calendar section under it, or beside it in
 *  two columns), and the composer. */
const pane = ({ rows = 18, open = false, menu = false, two = false } = {}) => `
  <div class="content today-pane"${two ? ' data-cols="two"' : ''}>
    <div class="content-head today-head fn-head">
      <div class="fn-date">
        <span class="fn-weekday">Sunday</span><span class="fn-day">Nov 22</span>
        <div class="today-nav"><button type="button" class="icon-btn" aria-label="Previous day">&#8249;</button><button type="button" class="icon-btn" aria-label="Next day">&#8250;</button></div>
      </div>
      <svg class="day-drawing fn-drawing" viewBox="0 0 160 200"></svg>
    </div>
    <section class="focus-card">
      <button type="button" class="focus-card__title"><span class="focus-card__mark"></span><span class="focus-card__text">Reply to Soren</span></button>
      <div class="focus-card__foot"><span class="focus-card__meta">Errands</span><button type="button" class="btn focus-card__go">Start working</button></div>
    </section>
    <div class="fn-list-head">
      <div class="fn-head-text"><span class="content-title">Today</span><span class="content-sub today-count">1 done &middot; ${rows} on the day</span></div>
      <div class="fn-head-tools"><button type="button" class="today-linkish fn-plan">Plan my day</button>
        <div class="today-acts"><button type="button" class="btn ghost today-menu-btn mono" aria-label="More actions">&#183;&#183;&#183;</button>${menu ? MENU : ''}</div></div>
    </div>
    <div class="scroll"><div class="today-cols"><div class="today-main">
      <section class="today-day"><ul class="today-list">${Array.from({ length: rows }, (_, i) => ROW(i + 1)).join('')}</ul></section>
      ${two ? '' : AGENDA}
    </div>${two ? `<aside class="today-side">${AGENDA}</aside>` : ''}</div></div>
    <div class="composer-foot"${open ? ' data-open=""' : ''}><form class="quickadd today-add">
      <input class="input" placeholder="Add to today" /><button type="button" class="btn">Add</button></form></div>
  </div>`

/** The phone frame: the view's column, then the tab bar under it. */
const phone = (main: string) => `
  <div class="shell" data-layout="sidebar"><div class="frame">
    <div class="frame-main">${main}</div>
    <nav class="tabbar" aria-label="Views"><button class="tab active">Today</button><button class="tab">Home</button>
      <button class="tab">Tasks</button><button class="tab">Calendar</button><button class="icon-btn"><svg width="15" height="15"></svg></button></nav>
  </div></div>`

/** The desktop frame: the sidebar column, then the view's column. */
const desk = (main: string) => `
  <div class="shell" data-layout="sidebar"><div class="frame">
    <nav class="appnav" aria-label="Views"><div class="appnav-head"><span class="brand">Smylte</span></div>
      <div class="tabs appnav-tabs"><button class="tab active">Today</button><button class="tab">Home</button></div>
      <div class="appnav-slot"></div><div class="appnav-foot"><button class="appnav-settings">Settings</button></div></nav>
    <div class="frame-main">${main}</div>
  </div></div>`

/** The element a finger on a row would move. */
function scrollerOf(el: Element): HTMLElement {
  let s = el.parentElement
  while (s && !/auto|scroll/.test(getComputedStyle(s).overflowY)) s = s.parentElement
  expect(s, 'nothing around the rows scrolls').not.toBeNull()
  return s!
}
async function toEnd(s: HTMLElement) {
  s.scrollTop = s.scrollHeight
  await new Promise(requestAnimationFrame)
}
const lastRow = (host: HTMLElement) => [...host.querySelectorAll('.today-row')].pop()!

describe('Today scrolls as one page on a phone', () => {
  it.each([[390, 844], [375, 667], [320, 568], [430, 932]])(
    'takes the date, the drawing and the focus card with it at %ix%i', async (w, h) => {
      await viewport(w, h)
      const host = await mount(phone(pane()))
      const date = host.querySelector('.fn-date')!
      const tab = host.querySelector('.tabbar')!
      // Vacuity: the header is on screen at rest, the drawing has a size, and
      // there is more than a screen of page to scroll.
      expect(box(date).top).toBeGreaterThanOrEqual(0)
      expect(box(host.querySelector('.fn-drawing')!).h).toBeGreaterThan(0)
      const s = scrollerOf(host.querySelector('.today-row')!)
      expect(s.scrollHeight, 'vacuity: the page fits; add rows').toBeGreaterThan(s.clientHeight + 100)

      expect(s.contains(date), `only ${s.className} scrolls, under the date`).toBe(true)
      expect(s.clientHeight, 'the scroller is not the whole pane above the bar')
        .toBeGreaterThanOrEqual(box(tab).top - 1)

      const dateTop = box(date).top
      const tabBox = box(tab)
      await toEnd(s)
      expect(Math.abs(box(date).top - (dateTop - s.scrollTop)), 'the date did not move with the list')
        .toBeLessThanOrEqual(1)
      for (const sel of ['.fn-date', '.fn-drawing', '.focus-card']) {
        expect(box(host.querySelector(sel)!).bottom, `${sel} is still on screen`).toBeLessThanOrEqual(0)
      }
      // What must stay put: the bar, and the page around the pane.
      expect(box(tab).top).toBe(tabBox.top)
      expect(Math.abs(box(tab).bottom - h)).toBeLessThanOrEqual(1)
      expect(document.scrollingElement!.scrollTop).toBe(0)
      expect(host.querySelector('.shell')!.scrollTop).toBe(0)
      expect(box(lastRow(host)).bottom, 'the last row cannot be reached').toBeLessThanOrEqual(box(tab).top + 1)
    })

  it.each([[390, 844], [320, 568]])('keeps the open composer on the bar while it does, at %ix%i', async (w, h) => {
    await viewport(w, h)
    const host = await mount(phone(pane({ open: true })))
    const c = host.querySelector('.composer-foot')!
    const tab = box(host.querySelector('.tabbar')!)
    expect(Math.abs(box(c).bottom - tab.top), 'the composer is not on the bar').toBeLessThanOrEqual(1)
    const s = scrollerOf(host.querySelector('.today-row')!)
    await toEnd(s)
    expect(Math.abs(box(c).bottom - tab.top), 'the composer left the bar').toBeLessThanOrEqual(1)
    expect(box(host.querySelector('.fn-date')!).bottom).toBeLessThanOrEqual(0)
    expect(box(lastRow(host)).bottom, 'the last row is under the composer').toBeLessThanOrEqual(box(c).top + 1)
    // Opaque, in the page's own colour, so rows passing under it do not show through.
    expect(getComputedStyle(c).backgroundColor).toBe(getComputedStyle(document.body).backgroundColor)
    const hit = document.elementFromPoint(w / 2, box(c).top + 2)
    expect(hit && c.contains(hit), 'a row paints over the composer').toBe(true)
  })

  it.each([[390, 844], [320, 568]])('hangs the ··· menu from its button at %ix%i', async (w, h) => {
    await viewport(w, h)
    const host = await mount(phone(pane({ menu: true })))
    // What TodayView does as the menu opens.
    host.querySelector('.today-menu')!.scrollIntoView({ block: 'nearest' })
    const btn = box(host.querySelector('.today-menu-btn')!)
    const menu = box(host.querySelector('.today-menu')!)
    const tab = box(host.querySelector('.tabbar')!)
    expect(Math.abs(menu.right - btn.right), 'the menu is not under its button').toBeLessThanOrEqual(1)
    expect(menu.top).toBeGreaterThanOrEqual(btn.bottom)
    expect(menu.top - btn.bottom).toBeLessThanOrEqual(10)
    expect(menu.bottom, 'the menu opened off screen').toBeLessThanOrEqual(h)
    expect(menu.bottom, 'the menu opened under the tab bar').toBeLessThanOrEqual(tab.top)
  })
})

describe('Today scrolls as one page on a desktop', () => {
  it.each([[1440, 900], [1100, 800]])(
    'with the calendar column held at the top and the composer at the foot, at %ix%i', async (w, h) => {
      await viewport(w, h)
      const host = await mount(desk(pane({ rows: 24, two: true })))
      expect(getComputedStyle(host.querySelector('.today-cols')!).display, 'vacuity: one column').toBe('grid')
      const date = host.querySelector('.fn-date')!
      const side = host.querySelector('.today-side')!
      const c = host.querySelector('.composer-foot')!
      const nav = host.querySelector('.appnav')!
      const s = scrollerOf(host.querySelector('.today-row')!)
      expect(s.contains(date), `only ${s.className} scrolls, under the date`).toBe(true)
      expect(s.contains(nav), 'the sidebar scrolls with the day').toBe(false)
      const dateTop = box(date).top
      const navBox = box(nav)
      await toEnd(s)
      expect(s.scrollTop, 'vacuity: not scrolled past the head')
        .toBeGreaterThan(box(host.querySelector('.fn-head')!).h + 150)
      expect(Math.abs(box(date).top - (dateTop - s.scrollTop))).toBeLessThanOrEqual(1)
      expect(box(date).bottom).toBeLessThanOrEqual(0)
      expect(box(side).top, 'the calendar column scrolled away').toBeGreaterThanOrEqual(0)
      expect(box(side).top).toBeLessThanOrEqual(4)
      expect(Math.abs(box(c).bottom - h), 'the composer left the foot').toBeLessThanOrEqual(1)
      expect(box(lastRow(host)).bottom).toBeLessThanOrEqual(box(c).top + 1)
      expect(box(nav)).toEqual(navBox)
    })
})

describe('the composer never hides the row that has focus', () => {
  // A guard rather than a failing-first test: before the change the composer
  // sat below the scroller and could not cover a row. Sticky, it can, and a
  // row reached with Tab was left under it (four of them in this fixture at
  // each size) until the pane took a bottom scroll padding.
  it.each([[1440, 900, false], [390, 844, true]] as const)('at %ix%i', async (w, h, isPhone) => {
    await viewport(w, h)
    const host = await mount(isPhone ? phone(pane({ open: true })) : desk(pane({ rows: 24, two: true })))
    const c = host.querySelector('.composer-foot')!
    for (const check of host.querySelectorAll<HTMLElement>('.today-row .check')) {
      check.focus()
      await new Promise(requestAnimationFrame)
      expect(box(check).bottom, `${check.nextElementSibling?.textContent} is under the composer`)
        .toBeLessThanOrEqual(box(c).top + 1)
    }
  })
})

describe('the presets keep the scroller they had', () => {
  it.each(['classic', 'workspace', 'refined'])('%s scrolls the list, not the page', async (slug) => {
    applyDesign(document.documentElement, slug)
    await viewport(390, 844)
    const host = await mount(phone(pane()))
    expect(scrollerOf(host.querySelector('.today-row')!).classList.contains('scroll')).toBe(true)
  })
})
