// The sidebar layout's frame (layout.ts, styles/layout.css), measured in a real
// browser. `layout-shell.test.tsx` pins which tree mounts; this pins what the
// stylesheet does with it — which is the half jsdom cannot see.
//
// Raw markup in the shape AppNav, TabBar and the views render (see
// test/browser-measure.ts on why markup rather than components): the class
// names are the real ones, and `layout-shell.test.tsx` holds them to the JSX.
import { beforeEach, describe, expect, it } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const VIEWS_EN = ['Today', 'Home', 'Tasks', 'Calendar', 'Scheduling']
const VIEWS_DE = ['Heute', 'Start', 'Aufgaben', 'Kalender', 'Buchungen']

const desk = (menu = '') => `
  <div class="shell" data-layout="sidebar"><div class="frame">
    <nav class="appnav" aria-label="Views">
      <div class="appnav-head"><span class="brand">Smylte<span class="dot">.</span></span>
        <button class="icon-btn appnav-fold">«</button></div>
      <div class="tabs appnav-tabs">
        ${VIEWS_EN.map((v, i) => `<button class="tab ${i === 1 ? 'active' : ''}">${v}</button>`).join('')}
      </div>
      <div class="appnav-slot"></div>
      <div class="appnav-foot"><button class="appnav-settings"><svg width="15" height="15"></svg>
        <span class="appnav-settings-word">Settings</span></button></div>
      ${menu}
    </nav>
    <div class="frame-main"><div class="content">
      <div class="content-head"><span class="content-title">Home</span><span class="content-sub">5 modules</span></div>
    </div></div>
  </div></div>`

const phone = (labels: string[]) => `
  <div class="shell" data-layout="sidebar"><div class="frame">
    <div class="frame-main"><div class="content"></div></div>
    <nav class="tabbar" aria-label="Views">
      ${labels.map((v, i) => `<button class="tab ${i === 0 ? 'active' : ''}">${v}</button>`).join('')}
      <button class="icon-btn"><svg width="15" height="15"></svg></button>
    </nav>
  </div></div>`

describe('on a desktop', () => {
  it('is one column down the left, the full height, with the view beside it', async () => {
    await viewport(1280, 800)
    const host = await mount(desk())
    const nav = box(host.querySelector('.appnav')!)
    const main = box(host.querySelector('.frame-main')!)
    expect(nav.left).toBe(0)
    expect(nav.w).toBe(236)
    expect(nav.h).toBe(800)
    expect(main.left).toBe(nav.right)
    expect(main.right).toBe(1280)
    // Settings is at the foot, whatever the column above it holds.
    expect(box(host.querySelector('.appnav-settings')!).bottom).toBeGreaterThan(760)
  })

  it('draws the views as C3 rows: no rule, the open one filled with an accent bar', async () => {
    await viewport(1280, 800)
    const host = await mount(desk())
    const [today, home] = host.querySelectorAll('.appnav .tab')
    const cs = getComputedStyle(today)
    expect(cs.borderBottomWidth, 'the strip underline is gone').toBe('0px')
    expect(box(today).h, 'under the 38px control floor (F4)').toBeGreaterThanOrEqual(38)
    expect(box(today).w, 'a row spans the column, less its inset').toBeGreaterThan(200)
    const on = getComputedStyle(home)
    expect(on.boxShadow).toMatch(/inset/)
    expect(on.backgroundColor).not.toBe(cs.backgroundColor)
  })

  it('opens the settings menu beside the column, inside the window', async () => {
    await viewport(1024, 768)
    const host = await mount(desk('<div class="menu settings-menu" data-view="panel" style="height: 400px"></div>'))
    const nav = box(host.querySelector('.appnav')!)
    const menu = box(host.querySelector('.menu')!)
    expect(menu.left).toBeGreaterThan(nav.right)
    expect(menu.right).toBeLessThanOrEqual(1024)
    expect(menu.bottom).toBeLessThanOrEqual(768)
    expect(menu.top).toBeGreaterThanOrEqual(0)
  })

  it('drops the rule under a view header, which is the page\'s only one now', async () => {
    await viewport(1280, 800)
    const host = await mount(desk())
    const head = getComputedStyle(host.querySelector('.content-head')!)
    expect(head.borderBottomColor).toBe('rgba(0, 0, 0, 0)')
  })
})

describe('on a phone', () => {
  it.each([['en', VIEWS_EN], ['de', VIEWS_DE]] as const)(
    'fits every view along the bottom, untruncated, at 390px (%s)', async (_, labels) => {
      await viewport(390, 844)
      const host = await mount(phone([...labels]))
      const bar = host.querySelector('.tabbar')!
      expect(box(bar).bottom).toBe(844)
      expect(bar.scrollWidth, 'the bar scrolls sideways').toBeLessThanOrEqual(bar.clientWidth)
      for (const tab of bar.querySelectorAll('.tab')) {
        expect(box(tab).h, `${tab.textContent} is under the 44px touch target`).toBeGreaterThanOrEqual(44)
        expect(tab.scrollWidth, `${tab.textContent} is cut off`).toBeLessThanOrEqual(tab.clientWidth)
      }
      const gear = box(bar.querySelector('.icon-btn')!)
      expect(gear.right).toBeLessThanOrEqual(390)
      expect(gear.h).toBeGreaterThanOrEqual(44)
    })

  it('stacks the view above the bar', async () => {
    await viewport(390, 844)
    const host = await mount(phone(VIEWS_EN))
    expect(box(host.querySelector('.frame-main')!).bottom).toBe(box(host.querySelector('.tabbar')!).top)
  })
})

describe('the composer', () => {
  it('is a floating box whose field has no edge of its own', async () => {
    await viewport(1280, 800)
    const host = await mount(`
      <div class="shell" data-layout="sidebar"><div class="content">
        <div class="composer-foot"><div class="quickadd">
          <input class="input" placeholder="Add a task…" /><button class="btn">New…</button>
        </div></div>
      </div></div>`)
    const boxEl = getComputedStyle(host.querySelector('.composer-foot > .quickadd')!)
    const field = getComputedStyle(host.querySelector('.composer-foot .input')!)
    expect(boxEl.borderTopLeftRadius).toBe('18px')      // --r-lg
    expect(boxEl.boxShadow).not.toBe('none')
    expect(field.borderTopColor).toBe('rgba(0, 0, 0, 0)')
    expect(getComputedStyle(host.querySelector('.composer-foot .btn')!).borderTopLeftRadius).toBe('12px')
  })
})

describe('Classic is not touched', () => {
  // The frame's sheet loads for every account. Everything in it is scoped to
  // the sidebar layout, and these are the rules most likely to leak if one
  // ever is not: the ones that restyle something Classic draws too.
  const classic = `
    <div class="shell" data-layout="classic"><div class="work"><div class="content" data-pane="list">
      <div class="content-head"><span class="content-title">All lists</span></div>
      <div class="scroll"><div class="task"><div class="pri-bar pri-high"></div>
        <button class="check">✓</button><div class="task-body">A</div></div></div>
    </div></div></div>`

  it('keeps the header rule and the priority bar', async () => {
    await viewport(1280, 800)
    const host = await mount(classic)
    expect(getComputedStyle(host.querySelector('.content-head')!).borderBottomWidth).toBe('1px')
    expect(getComputedStyle(host.querySelector('.content-head')!).borderBottomColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(getComputedStyle(host.querySelector('.pri-bar')!).display).not.toBe('none')
    expect(box(host.querySelector('.pri-bar')!).w).toBe(3)
  })

  it('keeps its title size and full-width rows', async () => {
    await viewport(1440, 900)
    const host = await mount(classic)
    expect(getComputedStyle(host.querySelector('.content-title')!).fontSize).toBe('24px')
    expect(getComputedStyle(host.querySelector('.scroll')!).paddingRight).toBe('0px')
  })
})
