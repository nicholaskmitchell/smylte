// The measuring harness itself (test/browser-measure.ts): what it hands back
// is the layout a page whose fonts had already loaded would have.
import { describe, expect, it } from 'vitest'
import { mount } from './test/browser-measure'

describe('mount', () => {
  it('measures a select by the face it asked for, even when that face arrived after its first layout', async () => {
    // A face of its own, at a URL no earlier request has fetched, so it is
    // still on its way when the select is first laid out. Chromium lays a
    // select out once with the fallback's metrics and keeps that height when
    // the face lands; a select mounted after the load has the face's height.
    const family = `MountProbe${Math.random().toString(36).slice(2)}`
    const style = document.createElement('style')
    style.textContent = `@font-face { font-family: ${family}; src: url(/fonts/hanken-grotesk-latin.woff2?${family}) format('woff2'); font-weight: 100 900; }
      .mount-probe { font: 16px ${family}, sans-serif; line-height: normal; padding: 10px; border: 1px solid; box-sizing: border-box; appearance: none; width: 280px; }`
    document.head.appendChild(style)
    try {
      const select = '<select class="mount-probe"><option>Errands and the long list</option></select>'
      const first = (await mount(select)).querySelector('select')!
      const fresh = (await mount(select)).querySelector('select')!
      expect(document.fonts.check(`16px ${family}`), 'vacuity: the face loaded').toBe(true)
      expect(first.getBoundingClientRect().height).toBe(fresh.getBoundingClientRect().height)
    } finally {
      style.remove()
      document.body.innerHTML = ''
    }
  })
})
