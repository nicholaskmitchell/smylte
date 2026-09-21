// What the desktop host actually receives when the page reports its background.
//
// This has to be a BROWSER test and it has to run in WebKit, because the thing
// under test is the engine's own colour serialisation. jsdom has no 2D canvas
// context at all, so under the unit project every assertion here would pass
// vacuously — and WebKit is not incidental: it is the engine the Linux client
// embeds, so it is the one whose answer decides whether that client's window
// chrome works.
//
// The bug being pinned. `syncCaption` reads `--bg` off the live CSSOM and sends
// it to the host, which parses `#RRGGBB`. The old normaliser assigned the value
// to `canvas.fillStyle` and read the property back — and that getter serialises
// per CSS Color 4, so a colour that did not start in sRGB comes back as
// `color(srgb …)` and one with alpha as `rgba(…)`. Neither is hex.
//
// That mattered because the Appearance editor accepts any CSS colour for `--bg`
// on purpose — the design system is authored in OKLCH and the swatch control
// says so. So an ordinary custom theme sent the host something it could not
// read, the host took that to mean "no colour to report", and on Linux that
// clears ONE display-wide stylesheet: the header bar lost its colour, the
// update strip went back to the GTK theme's label colour on the page's
// background, and the floating window lost the inset hairline that is its only
// visible border.
import { describe, expect, it, afterEach, vi } from 'vitest'
import { syncCaption } from './desktop'

/// Every POST the page made to the host, as [path, parsed body].
function captureHostCalls(): { sent: Array<[string, Record<string, unknown>]> } {
  const sent: Array<[string, Record<string, unknown>]> = []
  vi.stubGlobal('fetch', (path: string, init?: RequestInit) => {
    sent.push([path, init?.body ? JSON.parse(String(init.body)) : {}])
    return Promise.resolve(new Response('{}', { status: 200 }))
  })
  return { sent }
}

/// Set `--bg` the way a custom theme does — an inline property on <html>,
/// which is exactly what index.html's pre-paint script and appearance.ts write.
function setBackground(value: string): void {
  document.documentElement.style.setProperty('--bg', value)
}

/// The colour the host was told, or undefined if it was told nothing.
async function reportedBackground(): Promise<string | undefined> {
  const { sent } = captureHostCalls()
  syncCaption()
  // syncCaption fires the POST without awaiting it; one microtask turn is
  // enough for the fetch stub above to have recorded the call.
  await Promise.resolve()
  const call = sent.find(([path]) => path === '/desktop/appearance')
  return call?.[1].background as string | undefined
}

const HEX = /^#[0-9a-f]{6}$/i

afterEach(() => {
  vi.unstubAllGlobals()
  document.documentElement.style.removeProperty('--bg')
})

describe('the background reported to the desktop host', () => {
  it('is hex for the shipped themes, which are authored as hex', async () => {
    setBackground('#0C0C10')
    expect(await reportedBackground()).toBe('#0C0C10')
  })

  it.each([
    // The shape that broke it. A dark OKLCH background is what the Appearance
    // editor produces the moment anyone uses it as intended.
    ['oklch(0.2 0.02 250)'],
    ['oklch(0.98 0.005 90)'],
    // Every other space the editor's own validator lets through.
    ['lab(50% 40 59.5)'],
    ['hsl(220 40% 12%)'],
    ['color(display-p3 0.1 0.1 0.12)'],
    ['rgb(12 12 16)'],
    ['rebeccapurple'],
  ])('is hex for %s, whatever space it was written in', async (value) => {
    setBackground(value)
    const reported = await reportedBackground()
    // The assertion the old code failed: not "did it send something" but "can
    // the host read what it sent".
    expect(reported).toMatch(HEX)
  })

  it('flattens a translucent background to what is actually on screen', async () => {
    // Black at half alpha over the canvas is mid grey, and mid grey is what the
    // title bar has to be. Sending the unflattened value would paint the frame
    // black — a colour that is nowhere on the screen.
    setBackground('rgba(0, 0, 0, 0.5)')
    const reported = await reportedBackground()
    expect(reported).toMatch(HEX)

    const channel = parseInt(reported!.slice(1, 3), 16)
    expect(channel).toBeGreaterThan(100)
    expect(channel).toBeLessThan(160)
  })

  it('round-trips a known colour exactly rather than approximately', async () => {
    // oklch(0.7 0 0) is a neutral grey: all three channels must come back
    // equal, which a conversion that went through the wrong transfer function
    // or the wrong gamut would not manage.
    setBackground('oklch(0.7 0 0)')
    const reported = await reportedBackground()
    expect(reported).toMatch(HEX)

    const [r, g, b] = [1, 3, 5].map((at) => parseInt(reported!.slice(at, at + 2), 16))
    expect(r).toBe(g)
    expect(g).toBe(b)
    // Mid-to-light grey, not black and not white — i.e. the lightness survived.
    expect(r).toBeGreaterThan(140)
    expect(r).toBeLessThan(200)
  })

  it('sends an unreadable value through unchanged rather than inventing one', async () => {
    // The host documents an unparseable colour as "hand the frame back to the
    // system", and that is the honest outcome for a garbage token. What must
    // NOT happen is the canvas backdrop leaking out as a confident `#ffffff`,
    // which is what painting without a validity check would produce.
    setBackground('not-a-colour')
    const reported = await reportedBackground()
    expect(reported).not.toBe('#ffffff')
  })
})
