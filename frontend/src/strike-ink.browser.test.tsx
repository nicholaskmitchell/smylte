// The strike through a finished title (StrikeInk), in a real engine with the
// real stylesheets. Under Field notes the strike is absolute at the title's
// left, so an svg left to the browser's default size (300x150) is a box wider
// than a phone's title, and it pushed the Calendar's agenda and the share page
// sideways. jsdom has no layout and cannot see it.
import { StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { StrikeInk } from './components/Marks'

let root: Root | null = null
let host: HTMLElement | null = null
afterEach(() => {
  root?.unmount(); host?.remove(); root = null; host = null
})

const frame = () => new Promise(requestAnimationFrame)

async function mountStrike(on: boolean) {
  host = document.createElement('div')
  host.style.cssText = 'position: relative; width: 200px; overflow: auto'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(<StrictMode><span className="title">Water the seedlings</span><StrikeInk on={on} seed="x" /></StrictMode>)
  for (let i = 0; i < 200 && !host.querySelector('svg.strike-ink'); i++) await frame()
  await document.fonts.ready
  await frame()
  return host.querySelector('svg.strike-ink') as SVGSVGElement
}

describe('the strike under Field notes', () => {
  it('takes no box of its own while unticked, so its title never scrolls sideways', async () => {
    const svg = await mountStrike(false)
    const b = svg.getBoundingClientRect()
    expect([b.width, b.height]).toEqual([0, 0])
    expect(host!.scrollWidth, `the host scrolls to ${host!.scrollWidth}`).toBeLessThanOrEqual(200)
  })

  it('measures to its host once ticked', async () => {
    const svg = await mountStrike(true)
    const b = svg.getBoundingClientRect()
    const h = host!.getBoundingClientRect()
    expect(b.width).toBeCloseTo(h.width, 0)
    expect(b.height).toBeCloseTo(h.height, 0)
    expect(b.height).toBeGreaterThan(0)
    expect(host!.scrollWidth).toBeLessThanOrEqual(200)
  })
})
