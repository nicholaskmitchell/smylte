// The dialogs' own type under Field notes, measured in a real browser: a
// larger title, the step count as a margin note, and the drawn done mark
// showing finished where it sits in a row that records no check of its own.

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mount } from './test/browser-measure'
import { applyDesign } from './appearance'

beforeEach(() => { document.body.innerHTML = '' })
afterEach(() => { applyDesign(document.documentElement, null) })

const HEAD = '<div class="modal"><div class="modal-head">'
  + '<span class="modal-title">How long is today?</span>'
  + '<span class="plan-step mono">Step 1 of 3</span></div></div>'

describe('a dialog\'s title', () => {
  it('is 26px under Field notes', async () => {
    const host = await mount(HEAD)
    expect(getComputedStyle(host.querySelector('.modal-title')!).fontSize).toBe('26px')
  })

  it('is 18px under refined', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(HEAD)
    expect(getComputedStyle(host.querySelector('.modal-title')!).fontSize).toBe('18px')
  })
})

describe('a ritual\'s step count', () => {
  it('is an italic margin note in Newsreader under Field notes', async () => {
    const host = await mount(HEAD)
    const s = getComputedStyle(host.querySelector('.plan-step')!)
    expect(s.fontStyle).toBe('italic')
    expect(s.fontFamily).toMatch(/Newsreader/)
  })

  it('is not italic under refined', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(HEAD)
    expect(getComputedStyle(host.querySelector('.plan-step')!).fontStyle).not.toBe('italic')
  })
})

describe('the done mark of a row with no check of its own', () => {
  const MARK = '<span class="today-mark" role="img" aria-label="Done">'
    + '<svg class="check-ink" viewBox="0 0 28 28" aria-hidden="true">'
    + '<path class="check-frame" d="M2 2L26 2L26 26L2 26Z"/>'
    + '<path class="check-tick ink" pathLength="1" d="M8.6 14.6C10 15.8 11.4 17.6 12.4 19C14.6 14.4 18.6 9.2 23.8 5.8"/>'
    + '</svg></span>'

  it('shows its tick drawn, with no .on to draw it', async () => {
    const host = await mount(MARK)
    const tick = getComputedStyle(host.querySelector('.check-tick')!)
    expect(tick.opacity).toBe('1')
    expect(parseFloat(tick.strokeDashoffset)).toBe(0)
  })

  it('is anchored to its own box, so the ink sits on it and not on the dialog', async () => {
    const host = await mount(MARK)
    expect(getComputedStyle(host.querySelector('.today-mark')!).position).toBe('relative')
  })
})
