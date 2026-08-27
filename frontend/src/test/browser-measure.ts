// The measurement harness both `*.browser.test.tsx` files use.
//
// Extracted when the second one arrived rather than copied, because the two
// interesting lines here are the ones nobody would reproduce from memory: the
// order of `mount` and `document.fonts.ready`, and the `requestAnimationFrame`
// after it. A second copy that got either wrong would measure fallback-font
// metrics and be off by a few px, silently, and differently depending on how
// fast the run is.
import { page } from '@vitest/browser/context'

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
  document.body.appendChild(host)
  await document.fonts.ready
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
