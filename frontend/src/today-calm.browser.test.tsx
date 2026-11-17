// Field notes' calm Today rows, measured in a real browser.
//
// The unset estimate and the remove button are hidden with opacity and
// pointer-events, and whether that hiding wins over app.css's own
// `.today-drop` rules (which show the ✕ on hover and on every touchscreen) is a
// question about the cascade that jsdom cannot answer.

import { describe, expect, it, beforeEach } from 'vitest'
import { mount } from './test/browser-measure'

beforeEach(() => {
  document.body.innerHTML = ''
  // The shipped design, which the browser setup already switches on; said again
  // here because this file is about nothing else. The setup's afterEach puts it
  // back, so a test that measures a preset elsewhere cannot leak into this one.
  document.documentElement.dataset.surface = 'app'
})

const ROW = (est: string) => `
    <li class="today-row">
      <button class="check">&#10003;</button>
      <span class="today-title">Water the plants</span>
      <span class="today-meta">${est}<span class="today-due mono">Aug 28</span>
      <button class="today-drop">&#10005;</button></span></li>`
/** A row in the page's own list, where TodayView puts the day's rows. */
const row = (est: string) => `
  <div class="shell"><div class="content today-pane"><div class="scroll"><ul class="today-list">
    ${ROW(est)}
  </ul></div></div></div>`
/** The same row in a dialog on Today: the planning ritual's estimate step and
 *  the shutdown review render the day's rows there, to edit them. */
const dialogRow = (est: string) => `
  <div class="shell"><div class="content today-pane">
    <div class="overlay"><div class="modal" role="dialog"><ul class="today-list">
      ${ROW(est)}
    </ul></div></div>
    <div class="scroll"></div>
  </div></div>`
const UNSET = '<button class="today-est mono unset">+</button>'
const SET = '<button class="today-est mono">25m</button>'

/** Let a started opacity transition finish, so the value read is the one it
 *  settles on. Reading the style first makes the engine start the transition,
 *  and it is `getAnimations` that then lists it. */
async function settle(...els: Element[]) {
  els.forEach((el) => getComputedStyle(el).opacity)
  for (const a of document.getAnimations()) a.finish()
  await new Promise(requestAnimationFrame)
}

const look = (el: Element) => {
  const s = getComputedStyle(el)
  return { opacity: s.opacity, pointerEvents: s.pointerEvents }
}

describe('Field notes rows keep their tools out of sight until asked', () => {
  it('hides the unset estimate and the remove button at rest', async () => {
    const host = await mount(row(UNSET))
    const est = host.querySelector('.today-est')!
    const drop = host.querySelector('.today-drop')!
    await settle(est, drop)
    expect(look(drop)).toEqual({ opacity: '0', pointerEvents: 'none' })
    expect(look(est)).toEqual({ opacity: '0', pointerEvents: 'none' })
  })

  it('shows them on the row the title was tapped on', async () => {
    const host = await mount(row(UNSET))
    const est = host.querySelector('.today-est')!
    const drop = host.querySelector('.today-drop')!
    host.querySelector('.today-row')!.setAttribute('data-tools', '')
    await settle(est, drop)
    expect(look(drop)).toEqual({ opacity: '1', pointerEvents: 'auto' })
    expect(look(est)).toEqual({ opacity: '1', pointerEvents: 'auto' })
  })

  it('shows them when focus is anywhere in the row', async () => {
    const host = await mount(row(UNSET))
    const est = host.querySelector('.today-est')!
    const drop = host.querySelector('.today-drop')!
    host.querySelector<HTMLElement>('.check')!.focus()
    await settle(est, drop)
    expect(look(drop)).toEqual({ opacity: '1', pointerEvents: 'auto' })
    expect(look(est)).toEqual({ opacity: '1', pointerEvents: 'auto' })
  })

  it('keeps them in view on rows in a dialog, where they are the point', async () => {
    // The planning ritual's estimate step says "Tap an estimate to set it" over
    // these rows, and the shutdown review removes rows with the ✕: hiding the
    // tools there would leave the instruction pointing at nothing.
    // Field notes leaves them to app.css's own rules there: the estimate always
    // shows, and the ✕ keeps the reveal every design gives it (on hover with a
    // mouse, always on a touchscreen), so it is never made unclickable.
    const host = await mount(dialogRow(UNSET))
    const est = host.querySelector('.today-est')!
    const drop = host.querySelector('.today-drop')!
    await settle(est, drop)
    expect(look(est)).toEqual({ opacity: '1', pointerEvents: 'auto' })
    expect(look(drop).pointerEvents).toBe('auto')
  })

  it('leaves a set estimate showing', async () => {
    const host = await mount(row(SET))
    const est = host.querySelector('.today-est')!
    await settle(est)
    expect(getComputedStyle(est).opacity).toBe('1')
  })
})
