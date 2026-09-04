/**
 * The 2026-09-03 sweep: the rolling face's headline size, in a real browser.
 *
 * ONE finding, and it is here rather than in `backlog.sep03.settings.test.tsx`
 * because jsdom cannot see it: it has no ResizeObserver, every box is 0x0 so
 * `fitNow` bails before measuring, and `display.browser.test.tsx` calls
 * `fitNow` on raw markup and writes the size itself — so nothing anywhere
 * rendered `<DisplayView>` and asked what size the headline actually paints at.
 *
 * The mechanism: `fitNow` ended every pass with `title.style.fontSize = ''`
 * ("React owns the size"), and `NowFace` re-applied it through a style prop.
 * That holds only while the fit VALUE changes. The ResizeObserver's initial
 * notification re-runs the measure in the same frame; `fitNow` clears the
 * inline size and returns the same number; React diffs `{fontSize:'80px'}`
 * against `{fontSize:'80px'}` and writes nothing. The node is left with no
 * inline size and paints at the stylesheet's `clamp(20px, 7vh, 120px)` —
 * 33.6px at 800x480 where the fit said 80. Measured, before the fix:
 * inline '' / computed 33.6px / fitted 80.
 *
 * Production-shaped mount — `createRoot` + `StrictMode` as main.tsx does, with
 * `fetch` stubbed to hand back a `now` frame — rather than the raw-markup
 * harness, because the failure lives in the React / observer interaction and
 * raw markup has neither.
 */
import { describe, expect, it, afterEach } from 'vitest'
import { StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { viewport } from './test/browser-measure'
import { DisplayView, fitNow } from './components/DisplayView'
import type { DisplayFrame } from './api'

const FRAME: DisplayFrame = {
  display: { name: 'Desk', mode: 'now', palette: 'eink', refresh_seconds: 300, rotation: 0 },
  generated_at: '2026-09-03T22:00:00.000Z',
  day: '2026-09-03',
  language: 'en',
  time_format: '24h',
  sources: [{ id: 'home', name: 'Home', color: '#16A34A', treatment: 'solid', initial: '' }],
  now: {
    planned: true,
    heading: 'Now',
    next_heading: 'Next',
    current: { text: 'Renew the buildings insurance before the renewal date', kind: 'task',
      source: 'home', estimate: '1h 30m', estimate_minutes: 90 },
    next: { text: 'Email Sam about the contract', kind: 'task', source: null,
      estimate: '', estimate_minutes: null },
    remaining: 2,
    counts: { done: 1, total: 5 },
    empty_text: 'Nothing today',
    all_done_text: 'All done',
    preview_text: 'Today isn’t planned yet',
    preview_hint: 'This is what opening it would put on it.',
  },
}

const realFetch = window.fetch
let root: Root | null = null
let host: HTMLElement | null = null

afterEach(() => {
  root?.unmount()
  host?.remove()
  root = null
  host = null
  window.fetch = realFetch
})

const frame = () => new Promise(requestAnimationFrame)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Mount the page as main.tsx does and wait for the face to be on screen. */
async function mountNow(): Promise<HTMLElement> {
  window.fetch = (async () =>
    new Response(JSON.stringify(FRAME), { status: 200,
      headers: { 'Content-Type': 'application/json' } })) as typeof fetch
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(<StrictMode><DisplayView token="t" /></StrictMode>)
  for (let i = 0; i < 100 && !host.querySelector('.display-now__title'); i++) await sleep(10)
  await document.fonts.ready
  // A couple of frames: the layout effect, the observer's initial
  // notification, and any React commit those provoke.
  await frame(); await frame(); await sleep(50); await frame()
  return host
}

describe('2026-09-03 — the rolling face keeps its fitted headline size', () => {
  it.each([[800, 480], [1024, 600]])('at %ix%i the headline paints at the size fitNow chose',
    async (w, h) => {
      await viewport(w, h)
      const page = await mountNow()
      const title = page.querySelector('.display-now__title') as HTMLElement
      const face = page.querySelector('.display-now') as HTMLElement
      expect(title, 'the face did not render').not.toBeNull()

      // Read what the page PAINTS before touching the node — `fitNow` below
      // writes to it, and the question is what React left there.
      const painted = parseFloat(getComputedStyle(title).fontSize)
      const fit = fitNow(face)!
      expect(fit).not.toBeNull()
      // Old code: painted 33.6 (the 7vh fallback), fit 80.
      expect(painted, `${w}x${h}: painted ${painted}px, fitted ${fit.size}px`)
        .toBeCloseTo(fit.size, 0)
    })

  it('CONTROL: the size it paints is bigger than the stylesheet fallback at 800x480',
    async () => {
      // 7vh of 480 is 33.6px. A fit that agreed with the fallback by
      // coincidence would pass the case above while proving nothing.
      await viewport(800, 480)
      const page = await mountNow()
      const title = page.querySelector('.display-now__title') as HTMLElement
      expect(parseFloat(getComputedStyle(title).fontSize)).toBeGreaterThan(40)
    })
})
