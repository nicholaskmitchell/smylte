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
    const line = el.querySelector('g.dm-line')!
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
    const line = el.querySelector('g.dm-line')!
    const [f1, f2, f3] = [...line.querySelectorAll('path')].map((p) => getComputedStyle(p).visibility)
    expect([f1, f2, f3]).toEqual(['visible', 'hidden', 'hidden'])
    // A reward shows finished, at full size, with no grow.
    const reward = el.querySelector('.dm-reward.on')!
    expect(getComputedStyle(reward).scale).toBe('1')
  })
})

describe('ink', () => {
  // A one-frame line (the focus loop, a reward's still outline) is a path that
  // is itself .dm-line, not a path inside one. It must be inked, not filled:
  // filled, the loop's leaves and steam came out as solid black shapes.
  it('inks every line, the focus loop\'s included, and fills none', () => {
    const el = host()
    flushSync(() => createRoot(el).render(<DayDrawing drawing={drawing} state={state({ focusActive: true })} />))
    const lines = [...el.querySelectorAll<SVGPathElement>('.dm-line path, path.dm-line')]
    expect(lines.some((p) => p.closest('.dm-ambient')), 'the fixture\'s focus loop has a line').toBe(true)
    for (const p of lines) {
      const cs = getComputedStyle(p)
      expect(cs.fill, p.outerHTML.slice(0, 60)).toBe('none')
      expect(cs.stroke).not.toBe('none')
    }
  })

  it('scales the pen with the drawing: --stroke-pen at the phone\'s 128px, in proportion wider', () => {
    const el = host()
    el.style.width = '128px'
    el.style.height = '160px'
    flushSync(() => createRoot(el).render(<DayDrawing drawing={drawing} state={state({})} />))
    const svg = el.querySelector('svg')!
    svg.style.width = '128px'
    svg.style.height = '160px'
    const p = el.querySelector<SVGPathElement>('.dm-line path')!
    const units = parseFloat(getComputedStyle(p).strokeWidth)
    const pen = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--stroke-pen'))
    const pxPerUnit = svg.getBoundingClientRect().width / drawing.viewBox[2]
    expect(units * pxPerUnit).toBeCloseTo(pen, 2)
  })

  it('paints a glow with the wash, fading out', () => {
    const glowing = { ...drawing, marks: drawing.marks.map((m, i) => (i === 0 ? { ...m, role: 'glow' as const } : m)) }
    const el = host()
    flushSync(() => createRoot(el).render(<DayDrawing drawing={glowing} state={state({})} />))
    const g = el.querySelector<SVGPathElement>('.dm-glow')!
    expect(getComputedStyle(g).fill).toMatch(/^url\(/)
    const stops = [...el.querySelectorAll('stop')].map((s) => getComputedStyle(s))
    const wash = getComputedStyle(el.querySelector('.dm-glow')!).getPropertyValue('--wash').trim()
    expect(wash).not.toBe('')
    expect(stops.map((s) => s.stopOpacity)).toEqual(['1', '1', '0'])
  })

  it('lifts the glow toward the ink at night, and only at night', () => {
    // The dark wash is 1.5:1 on the dark paper, so a glow of it read as unlit;
    // fieldnotes.css mixes it 30% toward the ink in the dark theme only. Each
    // theme's stop is compared with the same expression resolved by the same
    // engine, so the test does not depend on how a colour is serialised.
    const glowing = { ...drawing, marks: drawing.marks.map((m, i) => (i === 0 ? { ...m, role: 'glow' as const } : m)) }
    const root = document.documentElement
    const before = root.dataset.theme
    const probe = (value: string) => {
      const span = document.createElement('span')
      span.style.color = value
      document.body.append(span)
      const out = getComputedStyle(span).color
      span.remove()
      return out
    }
    const stopIn = (theme: 'light' | 'dark') => {
      root.dataset.theme = theme
      const el = host()
      flushSync(() => createRoot(el).render(<DayDrawing drawing={glowing} state={state({})} />))
      return getComputedStyle(el.querySelector('stop')!).stopColor
    }
    try {
      expect(stopIn('light')).toBe(probe('var(--wash)'))
      const dark = stopIn('dark')
      expect(dark).toBe(probe('color-mix(in oklab, var(--wash) 70%, var(--fg))'))
      expect(dark).not.toBe(probe('var(--wash)'))
    } finally {
      if (before === undefined) delete root.dataset.theme
      else root.dataset.theme = before
    }
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
