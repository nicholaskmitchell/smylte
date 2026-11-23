// The measurement harness both `*.browser.test.tsx` files use.
//
// Extracted when the second one arrived rather than copied, because the two
// interesting lines here are the ones nobody would reproduce from memory: the
// order of `mount` and `document.fonts.ready`, and the `requestAnimationFrame`
// after it. A second copy that got either wrong would measure fallback-font
// metrics and be off by a few px, silently, and differently depending on how
// fast the run is.
import { page } from 'vitest/browser'

/** Put the page at a viewport. 844 is an iPhone 14's CSS height. */
export const viewport = (width: number, height = 844) => page.viewport(width, height)

/** Mount raw markup, wait for it to be measurable, and hand it back.
 *
 *  The await is not politeness. Fonts are self-hosted (`public/fonts/*.woff2`,
 *  wired in fonts.css) and a face loads LAZILY, when a rule that uses it first
 *  matches something in the document — so `document.fonts.ready` resolves
 *  immediately on an empty page and flips back to `loading` the moment text is
 *  mounted. Measuring in that window gives fallback-font metrics. Hence: mount,
 *  THEN wait, then measure. (Found by `layout.browser.test.tsx`'s own vacuity
 *  guard, which failed on `status === 'loading'` the first time it ran.)
 *
 *  Raw markup rather than a component wherever the thing under test is a
 *  stylesheet rule. The class names are held to the real JSX by the guards in
 *  `mobile-layout.test.ts` and by the component suites, so this stays a
 *  measurement harness rather than a second source of truth about what the app
 *  renders. */
export async function mount(html: string): Promise<HTMLElement> {
  const host = document.createElement('div')
  host.innerHTML = html
  // Any face that finishes loading while this mount waits (see LATE FACES).
  let landed = false
  const onLanded = () => { landed = true }
  document.fonts.addEventListener('loadingdone', onLanded)
  document.body.appendChild(host)
  // SETTLE, rather than await once. The paragraph above is a Chromium
  // observation: there, one `ready` after the mount is enough. WebKit resolves
  // `ready` while faces the just-mounted subtree asked for are still arriving
  // and then puts `status` back to 'loading', so a single await measures
  // fallback metrics there exactly as no await does in Chromium — silently, and
  // differently depending on how fast the run is.
  //
  // Bounded rather than a `while`: a face that never resolves has to reach
  // `layout.browser.test.tsx`'s vacuity guard as a failure, not hang the run.
  // The first await is unconditional and that is load-bearing: in Chromium
  // `status` is still 'loaded' the instant after `appendChild` — the lazy load
  // has not started — so a loop guarded on `status !== 'loaded'` skips its body
  // entirely and measures fallback metrics, which is the very failure the
  // paragraph above describes. Await first, THEN settle.
  await document.fonts.ready
  for (let i = 0; i < 20 && document.fonts.status !== 'loaded'; i++) {
    await new Promise(requestAnimationFrame)
    await document.fonts.ready
  }
  document.fonts.removeEventListener('loadingdone', onLanded)
  // LATE FACES. Waiting for the faces is not enough for a <select>: Chromium
  // lays one out once, with the fallback's metrics if its face has not
  // arrived, and keeps that height when the face lands (at a phone's 16px,
  // 40px where a select laid out after the load is 43px; WebKit lays it out
  // again). So the first fixture a file mounts measured a select by the
  // fallback, which ink-fields.browser.test.tsx caught on CI, where the
  // fonts arrive more slowly than here. When a face landed during this
  // mount, the subtree is put back, which lays it out afresh with the faces
  // in, as a page whose fonts had already loaded lays it out.
  // browser-measure.browser.test.tsx holds this.
  if (landed) {
    host.remove()
    document.body.appendChild(host)
  }
  // AT REST. Popovers, menus, modals, sheets, toasts and the scrim all enter
  // with a fade and a short rise (app.css, "entrances"), so for a few hundred
  // milliseconds after one mounts its box is displaced and its opacity is
  // under 1 — a contrast measured then composites against a half-faded
  // surface, and an edge measured then is a few pixels low. What every test in
  // this project pins is the layout the user reads, which is the one after the
  // entrance, so the entrances are finished before anything is measured.
  // An infinite animation has no end to finish at, and `finish()` throws on
  // one; it is ambient and never changes a box. (The Today drawing's line boil
  // is not one: DayDrawing.tsx steps it with a clock, not an animation.)
  for (const a of document.getAnimations()) {
    if (a.effect?.getComputedTiming().endTime === Infinity) continue
    a.finish()
  }
  await new Promise(requestAnimationFrame)
  return host
}

/** A box, rounded to a tenth of a pixel — enough to compare edges, not enough
 *  to make an assertion fail on sub-pixel rounding. */
export const box = (el: Element) => {
  const r = el.getBoundingClientRect()
  return {
    w: +r.width.toFixed(1), h: +r.height.toFixed(1), top: +r.top.toFixed(1),
    left: +r.left.toFixed(1), right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1),
  }
}

/** A colour as the browser paints it: r, g, b in 0–255 and alpha in 0–1.
 *
 *  `getComputedStyle` hands a colour back in whatever space it was written
 *  in, and a `color-mix()` (Field notes' control face, `--ctl-face`) computes
 *  to `oklab(…)` or `color(…)`, which no `rgb()` regex reads. So the browser
 *  itself draws the value on a one-pixel canvas and the pixel is read back. A
 *  value the browser cannot parse throws: a test must fail loudly rather than
 *  measure a colour it never read. */
export type Paint = [number, number, number, number]
let pixel: CanvasRenderingContext2D | null = null
export function paint(css: string): Paint {
  if (!CSS.supports('color', css)) throw new Error(`not a colour: ${JSON.stringify(css)}`)
  if (!pixel) {
    const c = document.createElement('canvas')
    c.width = 1
    c.height = 1
    pixel = c.getContext('2d', { willReadFrequently: true })!
  }
  pixel.clearRect(0, 0, 1, 1)
  pixel.fillStyle = css
  pixel.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = pixel.getImageData(0, 0, 1, 1).data
  return [r, g, b, a / 255]
}

/** `fg` laid over an opaque `bg`, sRGB source-over, as the browser composites. */
export const over = (fg: Paint, bg: Paint): Paint =>
  [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3])).concat(1) as Paint

/** The WCAG 2.x contrast of two opaque paints. */
export function ratio(a: Paint, b: Paint): number {
  const lin = (c: number) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }
  const lum = (p: Paint) => 0.2126 * lin(p[0]) + 0.7152 * lin(p[1]) + 0.0722 * lin(p[2])
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** Finish every transition and finite animation, then wait a frame: a colour
 *  read mid-transition (a hover's edge fades in over --dur-fast) is neither
 *  the old one nor the new one. */
export async function settle(): Promise<void> {
  for (const a of document.getAnimations()) {
    if (a.effect?.getComputedTiming().endTime === Infinity) continue
    a.finish()
  }
  await new Promise(requestAnimationFrame)
}
