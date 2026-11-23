// A select, and (stage 8) a date or time field, that Field notes draws its
// glyph on, measured in a real browser. The control moved inside `.ink-field`
// (InkSelect, DateTimeInput), so every rule in app.css that sized it in its
// row had to move to the wrapper (fieldnotes.css, "fields draw their glyph").
// What this holds is that nothing moved: in each row that sizes one, the
// control inside its wrapper has the box the bare control had, at a phone's
// width and a desktop's. And that the presets never see the wrapper.
import { beforeEach, describe, expect, it } from 'vitest'
import { applyDesign } from './appearance'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const CARET = '<svg class="icon-ink" data-icon="caret" viewBox="0 0 24 24" aria-hidden="true"><path d="M7.4 10.1C8.9 11.6 10.4 13.1 12 14.6C13.6 13.1 15.1 11.6 16.6 10"/></svg>'
const OPTIONS = '<option>Work</option><option>Errands and the long list</option>'

/** The control in `cls`, bare (as it was) or in its `.ink-field` (as it is). */
type Make = (cls: string, wrapped: boolean) => string
const select: Make = (cls, w) => {
  const s = `<select class="${cls}" data-ctl>${OPTIONS}</select>`
  return w ? `<span class="ink-field">${s}${CARET}</span>` : s
}

/** Each row that sizes a select, class for class from the components. */
export const SELECT_ROWS: { name: string; html: (ctl: (cls: string) => string) => string }[] = [
  { name: 'a dialog field', html: (c) => `<div class="overlay"><div class="modal"><div class="field"><label class="label">Repeat</label>${c('input')}</div></div></div>` },
  { name: 'a dialog field-row', html: (c) => `<div class="overlay"><div class="modal"><div class="field-row"><div class="field"><label class="label">Calendar</label>${c('input')}</div><div class="field"><label class="label">Length</label><input class="input" /></div></div></div></div>` },
  { name: 'a settings row (.input)', html: (c) => `<div class="settings-menu"><div class="set-panel"><div class="menu-row"><label>Opens on</label>${c('input')}</div></div></div>` },
  { name: 'a settings row (.menu-toggle)', html: (c) => `<div class="settings-menu"><div class="set-panel"><div class="menu-row"><label>Language</label>${c('menu-toggle')}</div></div></div>` },
  { name: 'a mail settings row', html: (c) => `<div class="settings-menu"><div class="set-panel"><div class="menu-row"><label>Task list</label>${c('menu-toggle mail-select')}</div></div></div>` },
  { name: 'a reminder row', html: (c) => `<div class="overlay"><div class="modal"><div class="field reminder-row"><label class="label">Reminder</label>${c('menu-toggle reminder-field')}</div></div></div>` },
  { name: 'the Tasks composer', html: (c) => `<div class="shell"><div class="content" data-pane="tasks"><div class="composer-foot"><div class="quickadd"><input class="input" />${c('input quickadd-list')}<button class="btn">Add</button></div></div></div></div>` },
  { name: 'Home\'s quick add', html: (c) => `<div class="shell"><div class="dash-mod"><form class="dash-quickadd"><input class="input" />${c('input quickadd-list')}<button class="btn">Add</button></form></div></div>` },
  { name: 'Today\'s composer', html: (c) => `<div class="shell"><div class="content today-pane"><div class="composer-foot"><form class="quickadd today-add"><input class="input" /><div class="today-add-opts"><button type="button" class="btn ghost today-swap">Make it a note</button>${c('input quickadd-list')}</div></form></div></div></div>` },
  { name: 'a bulk row', html: (c) => `<div class="overlay"><div class="modal"><div class="bulk-rows"><div class="bulk-row"><span class="bulk-cell bulk-f-title"><input class="input" /></span><span class="bulk-cell bulk-f-list"><span class="bulk-cell-label label">List</span>${c('input')}</span><span class="bulk-cell bulk-f-priority"><span class="bulk-cell-label label">Priority</span>${c('input')}</span></div></div></div></div>` },
  { name: 'a task property', html: (c) => `<div class="overlay"><div class="modal"><div class="task-props"><div class="task-prop prop-list"><label class="label">List</label><span class="task-prop-controls">${c('input')}</span></div></div></div></div>` },
  { name: 'a mail suggestion', html: (c) => `<div class="shell"><div class="mail-sug"><div class="mail-sug-actions">${c('input mail-sug-pick')}<button class="btn ghost">Not now</button><button class="btn">Add</button></div></div></div>` },
  { name: 'the theme bar', html: (c) => `<div class="settings-menu"><div class="set-panel"><div class="appear-bar">${c('input')}<button class="btn ghost">Save as</button><button class="btn ghost">Export</button></div></div></div>` },
  { name: 'a theme token', html: (c) => `<div class="settings-menu"><div class="set-panel"><div class="appear-row"><label class="appear-label">Serif</label><div class="appear-control">${c('input')}<button class="appear-clear">Reset</button></div></div></div></div>` },
]

/** The first control's box in each fixture, bare and wrapped. */
export async function compare(rows: typeof SELECT_ROWS, make: Make, width: number) {
  const off: string[] = []
  for (const r of rows) {
    document.body.innerHTML = ''
    const bare = await mount(r.html((cls) => make(cls, false)))
    const wrapped = await mount(r.html((cls) => make(cls, true)))
    const a = [...bare.querySelectorAll('[data-ctl]')].map(box)
    const b = [...wrapped.querySelectorAll('[data-ctl]')].map(box)
    expect(b.length, `${r.name}: vacuity`).toBe(a.length)
    a.forEach((x, i) => {
      const y = b[i]
      for (const k of ['w', 'h', 'left'] as const) {
        if (Math.abs(x[k] - y[k]) > 1) off.push(`${r.name} at ${width}px: ${k} ${x[k]} -> ${y[k]}`)
      }
    })
  }
  return off
}

describe('a select that draws its caret', () => {
  it.each([320, 390, 1024, 1440])('keeps the box the bare select had, in every row that sizes one, at %ipx', async (w) => {
    await viewport(w)
    expect(await compare(SELECT_ROWS, select, w)).toEqual([])
  })

  it('draws the caret inside its trailing end, and no gradient caret under it', async () => {
    await viewport(1024)
    const host = await mount(SELECT_ROWS[0].html((c) => select(c, true)))
    const s = box(host.querySelector('[data-ctl]')!)
    const caret = box(host.querySelector('.ink-field > .icon-ink')!)
    expect(caret.w).toBe(20)
    expect(caret.right).toBeLessThanOrEqual(s.right - 8)
    expect(caret.right).toBeGreaterThanOrEqual(s.right - 12)
    expect(Math.abs(caret.top + caret.h / 2 - (s.top + s.h / 2))).toBeLessThanOrEqual(1)
    expect(getComputedStyle(host.querySelector('[data-ctl]')!).backgroundImage).toBe('none')
  })

  it('is no box under a preset, which keeps its select as it was', async () => {
    await viewport(1024)
    applyDesign(document.documentElement, 'refined')
    const host = await mount(SELECT_ROWS[2].html((c) => select(c, true)))
    expect(getComputedStyle(host.querySelector('.ink-field')!).display).toBe('contents')
    expect(getComputedStyle(host.querySelector('.ink-field > .icon-ink')!).display).toBe('none')
    document.body.innerHTML = ''
    expect(await compare(SELECT_ROWS, select, 1024)).toEqual([])
  })
})

const field = (type: string): Make => (cls, w) => {
  const i = `<input class="${cls}" type="${type}" data-ctl />`
  const icon = `<svg class="icon-ink" data-icon="${type === 'time' ? 'time' : 'date'}" viewBox="0 0 24 24" aria-hidden="true"><path d="M4.2 6.3h15.7"/></svg>`
  return w ? `<span class="ink-field">${i}${icon}</span>` : i
}

/** Each row that sizes a date or time field, class for class from the components. */
const DATE_ROWS: { name: string; type: string; html: (ctl: (cls: string) => string) => string }[] = [
  { name: 'an event\'s start and end', type: 'datetime-local', html: (c) => `<div class="overlay"><div class="modal"><div class="field-row"><div class="field"><label class="label">Start</label>${c('input')}</div><div class="field"><label class="label">End</label>${c('input')}</div></div></div></div>` },
  { name: 'an event\'s repeat-until', type: 'date', html: (c) => `<div class="overlay"><div class="modal"><div class="field"><label class="label">Until</label>${c('input')}</div></div></div>` },
  { name: 'a bulk row\'s due date', type: 'date', html: (c) => `<div class="overlay"><div class="modal"><div class="bulk-rows"><div class="bulk-row"><span class="bulk-cell bulk-f-title"><input class="input" /></span><span class="bulk-cell bulk-f-due"><span class="bulk-cell-label label">Due</span>${c('input')}<input class="input" type="time" /></span></div></div></div></div>` },
  { name: 'a bulk row\'s due time', type: 'time', html: (c) => `<div class="overlay"><div class="modal"><div class="bulk-rows"><div class="bulk-row"><span class="bulk-cell bulk-f-title"><input class="input" /></span><span class="bulk-cell bulk-f-due"><span class="bulk-cell-label label">Due</span><input class="input" type="date" />${c('input')}</span></div></div></div></div>` },
  { name: 'a task property\'s date', type: 'date', html: (c) => `<div class="overlay"><div class="modal"><div class="task-props"><div class="task-prop prop-due"><label class="label">Due</label><span class="task-prop-controls">${c('input')}<input class="input" type="time" /></span></div></div></div></div>` },
  { name: 'a task property\'s time', type: 'time', html: (c) => `<div class="overlay"><div class="modal"><div class="task-props"><div class="task-prop prop-due"><label class="label">Due</label><span class="task-prop-controls"><input class="input" type="date" />${c('input')}</span></div></div></div></div>` },
  { name: 'a notification time', type: 'time', html: (c) => `<div class="settings-menu"><div class="set-panel"><div class="menu-row"><label>Digest at</label>${c('input notif-time')}</div></div></div>` },
  { name: 'a mail suggestion\'s due date', type: 'date', html: (c) => `<div class="shell"><div class="mail-sug"><div class="mail-sug-head"><span class="mail-kind">Task</span><input class="input mail-sug-title" />${c('input mail-sug-due')}</div></div></div>` },
  { name: 'an availability range', type: 'time', html: (c) => `<div class="overlay"><div class="modal"><div class="sched-ranges"><span class="sched-range">${c('input')} – ${c('input')}</span></div></div></div>` },
]

describe('a date or time field that draws its page or clock', () => {
  it.each([320, 390, 1024, 1440])('keeps the box the bare field had, in every row that sizes one, at %ipx', async (w) => {
    await viewport(w)
    const off: string[] = []
    for (const r of DATE_ROWS) off.push(...await compare([r], field(r.type), w))
    expect(off).toEqual([])
  })

  it('draws the page over the browser\'s own glyph, which it no longer paints', async () => {
    await viewport(1024)
    const host = await mount(DATE_ROWS[1].html((c) => field('date')(c, true)))
    const input = host.querySelector('[data-ctl]')!
    const icon = box(host.querySelector('.ink-field > .icon-ink')!)
    expect(icon.w).toBe(20)
    expect(icon.right).toBeLessThanOrEqual(box(input).right - 10)
    // The glyph is a pseudo-element no computed style reaches: read the rule.
    const rule = [...document.styleSheets].flatMap((s) => [...s.cssRules]).find((r) =>
      r instanceof CSSStyleRule && r.selectorText.includes('.ink-field > input::-webkit-calendar-picker-indicator'))
    expect((rule as CSSStyleRule | undefined)?.style.opacity).toBe('0')
  })
})
