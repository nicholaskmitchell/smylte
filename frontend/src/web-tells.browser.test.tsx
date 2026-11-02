// The web tells, measured: what a long press can select, in real browsers with
// the real stylesheets in the cascade. `web-tells.test.ts` reads the same rule
// as text; only this file can say it wins.

import { beforeEach, describe, expect, it } from 'vitest'
import { mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

// WebKit may ship only the prefixed property.
const userSelect = (el: Element | null) => {
  expect(el, 'element not found').not.toBeNull()
  const cs = getComputedStyle(el!)
  return cs.getPropertyValue('user-select') || cs.getPropertyValue('-webkit-user-select')
}

const MARKUP = `
<div class="shell">
  <nav class="tabbar"><div class="tabs"><button class="tab active" aria-current="page">Today</button></div>
    <button class="icon-btn" aria-label="Settings">⚙</button></nav>
  <div class="view-tabs" role="tablist"><button class="view-tab active" role="tab" aria-selected="true">List</button></div>
  <div class="side-item" role="checkbox" aria-checked="true" tabindex="0"><span class="name">Work</span></div>
  <div class="modal" role="dialog">
    <label class="label" for="t-title">Title</label><input id="t-title" class="input" value="Call the bank">
    <label class="label" for="t-notes">Notes</label><textarea id="t-notes" class="input">Ask about the fee</textarea>
    <label class="wrap">Name <input id="t-wrapped" class="input" value="Home"></label>
    <button class="btn">Save</button>
  </div>
  <div class="task-body" role="button" tabindex="0"><span class="task-title">Call the bank</span></div>
  <div class="day-card-body" role="button" tabindex="0">Pay rent</div>
  <div class="cal-ev" role="button" tabindex="0">Standup</div>
  <div class="task-row"><button class="task-main"><span class="task-title">Someday</span></button></div>
  <div class="day-pop" role="dialog"><button class="agenda-ev"><span class="t">9:00</span><span>Dentist</span></button></div>
  <div class="focus-next__text"><button type="button" class="focus-pick">Write the report</button></div>
  <p id="plain">Plain text</p>
</div>`

describe('a long press selects content, never a control\'s label', () => {
  it('the controls compute to none', async () => {
    await viewport(390)
    const host = await mount(MARKUP)
    for (const sel of ['.tab', '.icon-btn', '.view-tab', '.side-item', 'label.label', 'label.wrap', '.btn']) {
      // `auto` is the default, so this also proves the sheet loaded.
      expect(userSelect(host.querySelector(sel)), sel).toBe('none')
    }
  })

  it('the content does not', async () => {
    await viewport(390)
    const host = await mount(MARKUP)
    for (const sel of ['.task-body', '.task-body .task-title', '.day-card-body', '.cal-ev',
      '.task-main', '.task-main .task-title', '.agenda-ev', '.focus-pick', '#plain']) {
      expect(userSelect(host.querySelector(sel)), sel).not.toBe('none')
    }
  })

  it('every field stays selectable, even inside a label', async () => {
    await viewport(390)
    const host = await mount(MARKUP)
    for (const sel of ['#t-title', '#t-notes', '#t-wrapped']) {
      expect(userSelect(host.querySelector(sel)), sel).toBe('text')
    }
  })
})
