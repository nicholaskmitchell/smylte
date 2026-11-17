// Field notes' Calendar and Scheduling, measured in a real browser: a task
// chip's tick shows its drawn mark only when the task is done, a done chip keeps
// no line-through of its own (the drawn strike stands in for it), and
// Scheduling's empty states take their padding from the page's gutter now that
// the inline style is gone. jsdom computes no cascade, so the rules in
// fieldnotes.css's "cp3 · Calendar" block can only be checked here.

import { afterEach, describe, expect, it, beforeEach } from 'vitest'
import { mount, viewport } from './test/browser-measure'
import { applyDesign } from './appearance'

beforeEach(() => {
  document.body.innerHTML = ''
  document.documentElement.dataset.surface = 'app'
})

afterEach(() => { applyDesign(document.documentElement, null) })

// The markup of Marks.tsx's CheckInk, copied: the paths' shapes do not matter
// here, the classes do.
const INK = `<svg class="check-ink" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
  <path class="check-frame" d="M4 4L24 4L24 24L4 24Z"/>
  <path class="check-tick ink" pathLength="1" d="M8.6 14.6C10 15.8 11.4 17.6 12.4 19C14.6 14.4 18.6 9.2 23.8 5.8"/>
</svg>`

const CHIPS = `
  <div class="shell"><div class="work"><div class="content"><div class="scroll">
    <div class="cal-cell">
      <div class="cal-task done" style="--ev-c:#1565C0"><span class="tick">${INK}</span><bdi>Post letter</bdi></div>
      <div class="cal-task" style="--ev-c:#1565C0"><span class="tick">${INK}</span><bdi>Renew passport</bdi></div>
    </div>
  </div></div></div></div>`

const SCHED = `
  <div class="shell"><div class="work"><div class="content">
    <div class="content-switch sched-switch"><span class="spacer"></span></div>
    <div class="scroll">
      <div class="empty">No links yet</div>
      <div class="sched-list"></div>
      <div class="section-label label">Upcoming</div>
      <div class="empty">Nothing booked</div>
    </div>
  </div></div></div>`

describe('Field notes Calendar', () => {
  it('shows the tick mark on a done task chip and hides it on an open one', async () => {
    const host = await mount(CHIPS)
    const tick = (sel: string) =>
      getComputedStyle(host.querySelector(`${sel} .check-tick`)!).opacity
    expect(tick('.cal-task.done')).toBe('1')
    expect(tick('.cal-task:not(.done)')).toBe('0')
  })

  it('leaves a done chip\'s line to the drawn strike', async () => {
    const host = await mount(CHIPS)
    const done = host.querySelector('.cal-task.done')!
    expect(getComputedStyle(done).textDecorationLine).toBe('none')
  })

  it('keeps the presets as they were', async () => {
    const host = await mount(CHIPS)
    applyDesign(document.documentElement, 'refined')
    expect(getComputedStyle(host.querySelector('.cal-task.done')!).textDecorationLine)
      .toBe('line-through')
  })
})

describe('Field notes Scheduling', () => {
  it.each([390, 1280])('pads its empty states by the gutter at %ipx', async (w) => {
    await viewport(w)
    const host = await mount(SCHED)
    const probe = document.createElement('div')
    probe.style.paddingLeft = 'var(--gutter)'
    host.querySelector('.scroll')!.appendChild(probe)
    const gutter = getComputedStyle(probe).paddingLeft
    expect(parseFloat(gutter)).toBeGreaterThan(0)
    for (const empty of host.querySelectorAll('.scroll > .empty')) {
      expect(getComputedStyle(empty).paddingLeft).toBe(gutter)
    }
    const label = getComputedStyle(host.querySelector('.section-label')!)
    expect(label.paddingLeft).toBe(gutter)
    expect(label.fontFamily).toMatch(/Newsreader/)
    expect(label.textTransform).toBe('none')
  })
})
