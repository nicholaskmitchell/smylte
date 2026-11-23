// The segmented switch under Field notes, measured in a real browser: words,
// the chosen one in ink with the nav's drawn underline (TabInk), no track and
// no thumb. Markup as CalendarViewTabs renders it; controls-ink.test.ts holds
// every switch's JSX to it.
import { beforeEach, describe, expect, it } from 'vitest'
import { applyDesign } from './appearance'
import { box, mount, over, paint, ratio } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const INK = '<svg class="tab-ink" viewBox="0 0 34 6" aria-hidden="true"><path class="ink" pathLength="1" d="M2 4C9 2.4 18 2 32 3.2"/></svg>'
const SWITCH = `<div class="shell" style="background: var(--bg)"><div style="display: flex">
  <div class="view-tabs" role="tablist" style="--n: 3; --i: 0">
    <button type="button" role="tab" aria-selected="true" class="view-tab active">List${INK}</button>
    <button type="button" role="tab" aria-selected="false" class="view-tab ">3-Day${INK}</button>
    <button type="button" role="tab" aria-selected="false" class="view-tab ">Week${INK}</button>
  </div></div></div>`

describe('the segmented switch', () => {
  it.each(['light', 'dark'])('is words, the chosen one underlined in the pen, %s', async (theme) => {
    document.documentElement.dataset.theme = theme
    const host = await mount(SWITCH)
    const track = host.querySelector('.view-tabs')!
    expect(getComputedStyle(track, '::before').content, 'a thumb').toBe('none')
    expect(paint(getComputedStyle(track).backgroundColor)[3], 'a track').toBe(0)
    const [chosen, other] = host.querySelectorAll('.view-tab')
    const ink = (t: Element) => getComputedStyle(t.querySelector('.tab-ink path')!)
    expect(ink(chosen).opacity).toBe('1')
    expect(ink(other).opacity).toBe('0')
    // The underline sits under the word.
    const word = box(chosen)
    const line = box(chosen.querySelector('.tab-ink')!)
    expect(line.top).toBeGreaterThan(word.top + word.h / 2)
    const bg = paint(getComputedStyle(host.querySelector('.shell')!).backgroundColor)
    for (const t of [chosen, other]) {
      expect(ratio(over(paint(getComputedStyle(t).color), bg), bg)).toBeGreaterThanOrEqual(4.5)
    }
    expect(getComputedStyle(chosen).color).not.toBe(getComputedStyle(other).color)
  })

  it('keeps its track and thumb, and no underline, under a preset', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(SWITCH)
    expect(getComputedStyle(host.querySelector('.view-tabs')!, '::before').content).not.toBe('none')
    expect(getComputedStyle(host.querySelector('.tab-ink')!).display).toBe('none')
  })
})
