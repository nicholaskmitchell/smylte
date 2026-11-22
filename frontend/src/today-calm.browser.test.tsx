// Field notes' calm Today rows, measured in a real browser.
//
// The unset estimate and the remove button are hidden with opacity and
// pointer-events, and whether that hiding wins over app.css's own
// `.today-drop` rules (which show the ✕ on hover and on every touchscreen) is a
// question about the cascade that jsdom cannot answer.

import { afterEach, describe, expect, it, beforeEach } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

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

/** The list head as TodayView renders it under Field notes, with Plan my day on
 *  the line beside ⋯ (held to the real JSX by `TodayView.fieldnotes.test.tsx`).
 *  `key` makes the ids unique so a head with the link and one without can share a
 *  page; `link` leaves the link out and nothing else. */
const head = (key: string, count: string, link = true) => `
  <div class="shell"><div class="content today-pane">
    <div class="fn-list-head" id="head-${key}">
      <div class="fn-head-text">
        <span class="content-title" id="title-${key}">Today</span>
        <span class="content-sub today-count" id="count-${key}">${count}</span>
      </div>
      <div class="fn-head-tools" id="tools-${key}">
        ${link ? `<button type="button" class="today-linkish fn-plan" id="plan-${key}">Plan my day</button>` : ''}
        <div class="today-acts"><button type="button" class="btn ghost today-menu-btn mono" id="more-${key}" aria-label="More actions">···</button></div>
      </div>
    </div>
  </div></div>`

describe('Plan my day on the Today line under Field notes', () => {
  const mid = (el: Element) => { const b = box(el); return b.top + b.h / 2 }
  afterEach(() => { document.documentElement.style.removeProperty('--fs-scale') })

  const ONE = '1 done · 7 on the day'
  const TEN = '0 done · 10 on the day'
  const cases: [number, string, number][] = [
    ...[320, 375, 390, 430].flatMap((w) => [ONE, TEN].map((c) => [w, c, 1] as [number, string, number])),
    [430, ONE, 1.2], [430, TEN, 1.2],
  ]

  it.each(cases)(
    'keeps the link and ⋯ on the title’s line and adds no row (%ipx, "%s", --fs-scale %f)',
    async (w, count, scale) => {
      await viewport(w)
      document.documentElement.style.setProperty('--fs-scale', String(scale))
      const host = await mount(head('with', count) + head('without', count, false))
      const q = (id: string) => host.querySelector(`#${id}`)!
      const withH = box(q('head-with')).h
      const withoutH = box(q('head-without')).h
      expect(withH, 'no layout').toBeGreaterThan(0)
      const plan = box(q('plan-with'))
      expect(plan.h, 'no layout').toBeGreaterThan(0)
      const title = box(q('title-with'))
      const tools = box(q('tools-with'))
      const at = `at ${w}px, "${count}", --fs-scale ${scale}`
      // (a) the link and ⋯ share a line.
      expect(Math.abs(mid(q('plan-with')) - mid(q('more-with'))), `link and ⋯ share a line ${at}`).toBeLessThanOrEqual(2)
      // (b) the tools are on the title's line.
      expect(tools.top, `tools start above the title's bottom ${at}`).toBeLessThan(title.bottom)
      expect(tools.bottom, `tools end below the title's top ${at}`).toBeGreaterThan(title.top)
      // (c) no row of their own: adding the link may at most push the count under the title.
      const countH = box(q('count-with')).h
      expect(withH - withoutH, `the link adds a row ${at}`).toBeLessThanOrEqual(countH + 3)
      // (d) where the count has room beside the title, the link adds nothing.
      if ((w === 390 || w === 430) && count === ONE && scale === 1) {
        expect(withH - withoutH, `the link adds height ${at}`).toBeLessThanOrEqual(1)
      }
    })

  it('gives the link a 44px tap box that adds no height', async () => {
    await viewport(390)
    const host = await mount(head('with', ONE))
    const plan = host.querySelector('#plan-with')!
    const b = box(plan)
    expect(b.h, 'no layout').toBeGreaterThan(0)
    const x = b.left + b.w / 2
    const y = b.top + b.h / 2
    const hit = (dy: number) => document.elementFromPoint(x, y + dy)?.closest('.fn-plan') ?? null
    expect(hit(-20), '20px above the centre is the link').toBe(plan)
    expect(hit(20), '20px below the centre is the link').toBe(plan)
    expect(hit(-24), '24px above the centre is not').toBeNull()
    expect(hit(24), '24px below the centre is not').toBeNull()
  })
})
