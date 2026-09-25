// The sidebar layout's frame (layout.ts, styles/layout.css), measured in a real
// browser. `layout-shell.test.tsx` pins which tree mounts; this pins what the
// stylesheet does with it — which is the half jsdom cannot see.
//
// Raw markup in the shape AppNav, TabBar and the views render (see
// test/browser-measure.ts on why markup rather than components). The shapes
// are the real ones, down to the elements between the elements a rule names:
// the first version of this file wrote a Tasks row with the tick straight
// after the priority bar, which the real row never does (a twisty sits
// between them), and so passed a rule that matched no row in the app.
import { beforeEach, describe, expect, it } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const VIEWS_EN = ['Today', 'Home', 'Tasks', 'Calendar', 'Scheduling']
const VIEWS_DE = ['Heute', 'Start', 'Aufgaben', 'Kalender', 'Buchungen']

const tabs = (labels: string[], active: number) =>
  labels.map((v, i) => `<button class="tab ${i === active ? 'active' : ''}">${v}</button>`).join('')

/** The desktop frame as App renders it: the nav, the view's column, and — as
 *  the frame's own last child, not the nav's — the settings menu. */
const desk = ({ main = '', menu = '', slot = '', folded = false } = {}) => `
  <div class="shell" data-layout="sidebar"><div class="frame"${folded ? ' data-nav="folded"' : ''}>
    <nav class="appnav${folded ? ' collapsed' : ''}" aria-label="Views">
      <div class="appnav-head">${folded ? '' : '<span class="brand">Smylte<span class="dot">.</span></span>'}
        <button class="icon-btn appnav-fold">${folded ? '»' : '«'}</button></div>
      ${folded ? '' : `<div class="tabs appnav-tabs">${tabs(VIEWS_EN, 1)}</div>`}
      <div class="appnav-slot">${slot}</div>
      <div class="appnav-foot"><button class="appnav-settings"><svg width="15" height="15"></svg>
        ${folded ? '' : '<span class="appnav-settings-word">Settings</span>'}</button></div>
    </nav>
    <div class="frame-main">${main || `<div class="content">
      <div class="content-head"><span class="content-title">Home</span><span class="content-sub">5 modules</span></div>
    </div>`}</div>
    ${menu}
  </div></div>`

/** The phone frame: the view's column, the bar under it, and anything drawn
 *  beside the bar (the settings sheet, a toast). */
const phone = (labels: string[], { main = '', after = '' } = {}) => `
  <div class="shell" data-layout="sidebar"><div class="frame">
    <div class="frame-main">${main || '<div class="content"></div>'}</div>
    <nav class="tabbar" aria-label="Views">
      ${tabs(labels, 0)}
      <button class="icon-btn"><svg width="15" height="15"></svg></button>
    </nav>
    ${after}
  </div></div>`

/** A resolved colour, the way the browser computes the same token elsewhere. */
function tokenColor(host: HTMLElement, token: string): string {
  const probe = document.createElement('span')
  probe.style.color = `var(${token})`
  host.querySelector('.shell')!.appendChild(probe)
  const c = getComputedStyle(probe).color
  probe.remove()
  return c
}

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

  it('drops the rule under a view header, which is the page\'s only one now', async () => {
    await viewport(1280, 800)
    const host = await mount(desk())
    const head = getComputedStyle(host.querySelector('.content-head')!)
    expect(head.borderBottomColor).toBe('rgba(0, 0, 0, 0)')
  })

  it('folds to a 52px rail, and the view takes the rest', async () => {
    await viewport(1280, 800)
    const host = await mount(desk({ folded: true }))
    expect(box(host.querySelector('.appnav')!).w).toBe(52)
    expect(box(host.querySelector('.frame-main')!).left).toBe(52)
  })
})

describe('the settings menu', () => {
  const MENU = '<div class="menu settings-menu" data-view="panel" style="height: 400px"><button class="btn ghost">x</button></div>'

  it.each([false, true])('opens beside the column, inside the window (folded: %s)', async (folded) => {
    await viewport(1024, 768)
    const host = await mount(desk({ menu: MENU, folded }))
    const nav = box(host.querySelector('.appnav')!)
    const menu = box(host.querySelector('.menu')!)
    expect(menu.left).toBeGreaterThan(nav.right)
    expect(menu.left - nav.right, 'the menu is not beside the column').toBeLessThanOrEqual(12)
    expect(menu.right).toBeLessThanOrEqual(1024)
    expect(menu.bottom).toBeLessThanOrEqual(768)
    expect(menu.top).toBeGreaterThanOrEqual(0)
  })

  it('inherits none of the column\'s custom properties', async () => {
    // Drawn inside the nav it took the paper hover (--bg-elev, the menu's own
    // background, so no hover showed at all) and the inset focus offset.
    await viewport(1280, 800)
    const host = await mount(desk({ menu: MENU }))
    const menu = getComputedStyle(host.querySelector('.menu')!)
    const nav = getComputedStyle(host.querySelector('.appnav')!)
    const page = getComputedStyle(document.body)
    for (const prop of ['--ghost-hover-bg', '--focus-offset']) {
      expect(menu.getPropertyValue(prop), prop).toBe(page.getPropertyValue(prop))
    }
    expect(nav.getPropertyValue('--ghost-hover-bg'), 'vacuity: the column does set it')
      .not.toBe(page.getPropertyValue('--ghost-hover-bg'))
  })

  it('keeps the phone sheet\'s own icon buttons their size', async () => {
    // `.tabbar .icon-btn` once reached the sheet's Back and Close and made
    // them 44px, borderless and wider than the slot that stands in for Back.
    await viewport(390, 844)
    const host = await mount(phone(VIEWS_EN, { after: `
      <div class="overlay set-overlay"><div class="settings-menu set-sheet" data-view="panel">
        <div class="set-head"><button class="icon-btn set-back">‹</button>
          <span class="set-title">Appearance</span><button class="icon-btn set-close">✕</button></div>
      </div></div>` }))
    for (const sel of ['.set-back', '.set-close']) {
      const el = host.querySelector(sel)!
      expect(box(el).w, sel).toBeLessThan(40)
      expect(getComputedStyle(el).borderTopColor, sel).not.toBe('rgba(0, 0, 0, 0)')
    }
  })
})

describe('priority', () => {
  // The two row shapes TasksView draws, as it draws them: the list's TaskRow
  // puts a twisty (or its gap) between the bar and the tick; the day card
  // does not.
  const rows = `
    <div class="shell" data-layout="sidebar"><div class="scroll">
      <div class="task" data-pri="high" id="list-high"><div class="pri-bar pri-high"></div>
        <span class="twisty-gap"></span><button class="check">✓</button><div class="task-body">A</div></div>
      <div class="task" data-pri="med" id="list-parent"><div class="pri-bar pri-med"></div>
        <button class="twisty open">›</button><button class="check">✓</button><div class="task-body">B</div></div>
      <div class="task" id="list-none"><div class="pri-bar"></div>
        <span class="twisty-gap"></span><button class="check">✓</button><div class="task-body">C</div></div>
      <div class="day-card" data-pri="low" id="card-low"><div class="pri-bar pri-low"></div>
        <button class="check">✓</button><div class="day-card-body">D</div></div>
    </div></div>`

  it('is the tick\'s edge on every row shape, and the bar is gone', async () => {
    await viewport(1280, 800)
    const host = await mount(rows)
    const tick = (id: string) => getComputedStyle(host.querySelector(`#${id} > .check`)!).borderTopColor
    expect(tick('list-high')).toBe(tokenColor(host, '--pri-high'))
    expect(tick('list-parent')).toBe(tokenColor(host, '--pri-med'))
    expect(tick('card-low')).toBe(tokenColor(host, '--pri-low'))
    expect(tick('list-none')).toBe(tokenColor(host, '--fg-faint'))
    for (const bar of host.querySelectorAll('.pri-bar')) {
      expect(getComputedStyle(bar).display).toBe('none')
    }
  })
})

describe('at a short window', () => {
  // A phone on its side gets the desktop frame (it is chosen by width), and
  // so does a short laptop window. The collections must keep some room.
  const lists = `<div class="side"><div class="side-head"><span class="label">Lists</span></div>
    <div class="side-list">${['Errands', 'Personal', 'Reading', 'Work', 'Home', 'Garden']
      .map((n) => `<div class="side-item"><span class="swatch"></span><span class="name">${n}</span></div>`).join('')}</div>
    <button class="side-completed">✓ View completed</button><button class="side-completed">⏸ View parked</button></div>`

  it.each([[844, 390], [932, 430]])('keeps the lists visible at %ix%i, and scrolls the column', async (w, h) => {
    await viewport(w, h)
    const host = await mount(desk({ slot: lists }))
    const list = host.querySelector('.side-list')!
    const row = box(list.querySelector('.side-item')!)
    expect(list.clientHeight, 'the lists got no room').toBeGreaterThanOrEqual(3 * row.h)
    const nav = host.querySelector('.appnav')!
    expect(getComputedStyle(nav).overflowY).toBe('auto')
    expect(nav.scrollHeight, 'vacuity: the column is taller than the window').toBeGreaterThan(nav.clientHeight)
    // …and Settings stays on screen at its foot while it does.
    const foot = box(host.querySelector('.appnav-settings')!)
    expect(foot.bottom).toBeLessThanOrEqual(h)
    expect(foot.bottom).toBeGreaterThan(h - 60)
  })
})

describe('Today', () => {
  // The header in its real shape: title, nav, figures, spacer, then the
  // actions group, with the ··· menu a child of that group.
  const pane = (cols: 'one' | 'two') => `
    <div class="content today-pane"${cols === 'two' ? ' data-cols="two"' : ''}>
      <div class="content-head today-head">
        <span class="content-title">Today</span>
        <div class="today-nav"><button class="icon-btn">‹</button><button class="icon-btn">›</button></div>
        <span class="content-sub">Friday, September 25</span><span class="spacer"></span>
        <div class="today-acts">
          <button class="btn ghost today-review">Review</button>
          <button class="btn today-focus">Start working</button>
          <button class="btn ghost today-menu-btn mono">···</button>
          <div class="today-menu"><button class="today-menu-item">Shut down</button></div>
        </div>
      </div>
      <div class="scroll"></div>
    </div>`

  it.each([[1280, 'one'], [1440, 'one'], [1920, 'one'], [1920, 'two']] as const)(
    'hangs the ··· menu from its button at %i (%s column)', async (w, cols) => {
      await viewport(w, 900)
      const host = await mount(desk({ main: pane(cols) }))
      const btn = box(host.querySelector('.today-menu-btn')!)
      const menu = box(host.querySelector('.today-menu')!)
      expect(Math.abs(menu.right - btn.right), 'the menu is not under its button').toBeLessThanOrEqual(1)
      expect(menu.top).toBeGreaterThanOrEqual(btn.bottom)
      expect(menu.top - btn.bottom).toBeLessThanOrEqual(10)
    })
})

describe('the toast', () => {
  const composer = `<div class="content"><div class="scroll" style="flex: 1"></div>
    <div class="composer-foot"><div class="quickadd"><input class="input" placeholder="Add a task…" />
      <button class="btn">New…</button></div></div></div>`
  const toast = '<div class="toast" role="alert"><span>Could not save</span><button class="icon-btn">✕</button></div>'

  it.each([[1280, 800], [1024, 768], [1920, 1080]])('clears the composer at %ix%i', async (w, h) => {
    await viewport(w, h)
    const host = await mount(desk({ main: composer, menu: toast }))
    const t = box(host.querySelector('.toast')!)
    const c = box(host.querySelector('.composer-foot > .quickadd')!)
    expect(t.bottom, 'the toast covers the composer').toBeLessThanOrEqual(c.top)
  })

  it('clears the composer and the tab bar on a phone', async () => {
    await viewport(390, 844)
    const host = await mount(phone(VIEWS_EN, { main: composer, after: toast }))
    const t = box(host.querySelector('.toast')!)
    expect(t.bottom).toBeLessThanOrEqual(box(host.querySelector('.composer-foot > .quickadd')!).top)
    expect(t.bottom).toBeLessThanOrEqual(box(host.querySelector('.tabbar')!).top)
  })
})

describe('on a phone', () => {
  it.each([
    [390, 'en', VIEWS_EN], [390, 'de', VIEWS_DE],
    [320, 'en', VIEWS_EN], [320, 'de', VIEWS_DE],
  ] as const)('fits every view along the bottom, untruncated, at %ipx (%s)', async (w, _, labels) => {
    await viewport(w, 844)
    const host = await mount(phone([...labels]))
    const bar = host.querySelector('.tabbar')!
    expect(box(bar).bottom).toBe(844)
    expect(bar.scrollWidth, 'the bar scrolls sideways').toBeLessThanOrEqual(bar.clientWidth)
    for (const tab of bar.querySelectorAll('.tab')) {
      expect(box(tab).h, `${tab.textContent} is under the 44px touch target`).toBeGreaterThanOrEqual(44)
      expect(tab.scrollWidth, `${tab.textContent} is cut off`).toBeLessThanOrEqual(tab.clientWidth)
    }
    const gear = box(bar.querySelector('.icon-btn')!)
    expect(gear.right).toBeLessThanOrEqual(w)
    expect(gear.h).toBeGreaterThanOrEqual(44)
  })

  it('marks the open view with the accent, not only a fill', async () => {
    await viewport(390, 844)
    const host = await mount(phone(VIEWS_EN))
    const on = getComputedStyle(host.querySelector('.tabbar .tab.active')!)
    expect(on.boxShadow).toMatch(/inset/)
    expect(on.boxShadow).toContain(tokenColor(host, '--accent'))
  })

  it('stacks the view above the bar', async () => {
    await viewport(390, 844)
    const host = await mount(phone(VIEWS_EN))
    expect(box(host.querySelector('.frame-main')!).bottom).toBe(box(host.querySelector('.tabbar')!).top)
  })

  it('keeps the calendar\'s day rows the width of the list', async () => {
    // On the phone these rows are buttons, and a button's `width: auto` is
    // its text's — "Standup" drew 156px wide in a 390px list.
    await viewport(390, 844)
    const host = await mount(phone(VIEWS_EN, { main: `<div class="day-agenda">
      <button class="agenda-ev"><span class="t">9:30 AM</span><span>Standup</span></button>
      <button class="agenda-ev agenda-task"><span class="t">All day</span><span class="tick">○</span><span>Pay rent</span></button>
    </div>` }))
    const list = box(host.querySelector('.day-agenda')!)
    const inset = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--row-inset'))
    for (const row of host.querySelectorAll('.agenda-ev')) {
      expect(box(row).w, row.textContent!).toBeCloseTo(list.w - 2 * inset, 0)
    }
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
  // ever is not: the ones that restyle something Classic draws too. The row is
  // TaskRow's real shape, priority attribute and all.
  const classic = `
    <div class="shell" data-layout="classic"><div class="work"><div class="content" data-pane="list">
      <div class="content-head"><span class="content-title">All lists</span></div>
      <div class="scroll"><div class="task" data-pri="high"><div class="pri-bar pri-high"></div>
        <span class="twisty-gap"></span><button class="check">✓</button><div class="task-body">A</div></div></div>
    </div></div></div>`

  it('keeps the header rule and the priority bar', async () => {
    await viewport(1280, 800)
    const host = await mount(classic)
    expect(getComputedStyle(host.querySelector('.content-head')!).borderBottomWidth).toBe('1px')
    expect(getComputedStyle(host.querySelector('.content-head')!).borderBottomColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(getComputedStyle(host.querySelector('.pri-bar')!).display).not.toBe('none')
    expect(box(host.querySelector('.pri-bar')!).w).toBe(3)
    expect(getComputedStyle(host.querySelector('.check')!).borderTopColor).toBe(tokenColor(host, '--fg-faint'))
  })

  it('keeps its title size and full-width rows', async () => {
    await viewport(1440, 900)
    const host = await mount(classic)
    expect(getComputedStyle(host.querySelector('.content-title')!).fontSize).toBe('24px')
    expect(getComputedStyle(host.querySelector('.scroll')!).paddingRight).toBe('0px')
  })
})
