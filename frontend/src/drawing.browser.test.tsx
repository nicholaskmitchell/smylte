// The day's drawing in a real engine: what moves, what holds still under
// reduced motion, and what it costs to draw.
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { cdp, server } from 'vitest/browser'
import fixture from './test/drawing-fixture.json'
import { DayDrawing } from './components/DayDrawing'
import { EMPTY_DAY, sanitizeDrawing, type DayState } from './drawing'

const drawing = sanitizeDrawing(fixture)!
const state = (over: Partial<DayState>): DayState => ({ ...EMPTY_DAY, nothingPlanned: false, ...over })
const chromium = server.browser === 'chromium'
/** The CDP session, typed for the two calls this file makes. */
const devtools = () => cdp() as unknown as { send(method: string, params?: object): Promise<unknown> }

function host() {
  const el = document.createElement('div')
  el.style.width = '192px'
  el.style.height = '240px'
  document.body.appendChild(el)
  return el
}

afterEach(async () => {
  document.body.innerHTML = ''
  if (chromium) {
    await devtools().send('Emulation.setEmulatedMedia', { features: [] })
    await devtools().send('Emulation.setCPUThrottlingRate', { rate: 1 })
  }
})

describe('motion', () => {
  it('boils: three frames of each line, shown one at a time', async () => {
    const el = host()
    flushSync(() => createRoot(el).render(<DayDrawing drawing={drawing} state={state({})} />))
    const line = el.querySelector('.dm-line')!
    const visible = [...line.querySelectorAll('path')].filter((p) => getComputedStyle(p).visibility === 'visible')
    expect(visible.length, 'one frame of three at a time').toBe(1)
    expect(document.getAnimations().length).toBeGreaterThan(0)
  })

  it.skipIf(!chromium)('holds still under reduced motion: frame one, and nothing animating', async () => {
    await devtools().send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] })
    const el = host()
    flushSync(() => createRoot(el).render(<DayDrawing drawing={drawing} state={state({ rewards: 3, focusActive: true })} />))
    await new Promise(requestAnimationFrame)
    expect(document.getAnimations(), 'something still animates').toEqual([])
    const line = el.querySelector('.dm-line')!
    const [f1, f2, f3] = [...line.querySelectorAll('path')].map((p) => getComputedStyle(p).visibility)
    expect([f1, f2, f3]).toEqual(['visible', 'hidden', 'hidden'])
    // A reward shows finished, at full size, with no grow.
    const reward = el.querySelector('.dm-reward.on')!
    expect(getComputedStyle(reward).scale).toBe('1')
  })
})

describe('cost', () => {
  // The budget is a mid phone: Chromium at a quarter of this machine's speed.
  // The common case is a state change on a drawing already up (a tick); the
  // first draw is reported too.
  it.skipIf(!chromium)('redraws a state change in under 2ms on a throttled CPU', async () => {
    const el = host()
    const root = createRoot(el)
    flushSync(() => root.render(<DayDrawing drawing={drawing} state={state({ rewards: 0 })} />))
    await devtools().send('Emulation.setCPUThrottlingRate', { rate: 4 })
    const times: number[] = []
    for (let i = 0; i < 30; i++) {
      const t = performance.now()
      flushSync(() => root.render(<DayDrawing drawing={drawing} state={state({ rewards: i % 13 })} />))
      times.push(performance.now() - t)
    }
    times.sort((a, b) => a - b)
    const median = times[15]
    expect(median, `median redraw ${median.toFixed(2)}ms`).toBeLessThan(2)
  })

  it('stays inside its structural budget', () => {
    const paths = drawing.marks.reduce((n, m) => n + m.frames.length, 0)
      + (drawing.ambient?.frames.flat().length ?? 0)
    expect(paths).toBeLessThan(700)
    expect(JSON.stringify(drawing).length, 'payload bytes').toBeLessThan(64 * 1024)
  })
})
