// The Android app's WebView floor, kept honest from this side.
//
// The Android app refuses to start on a WebView built on a Chromium older than
// HostProtocol.MIN_WEBVIEW_MAJOR and says what to update, because below it this
// page loads broken with no message: today the palette's oklch() and the tints'
// color-mix() (111) are what set it. Nothing else tells the Android side when
// the page starts to need something newer, so this test scans the page's own
// sources for features newer than the floor.
//
// It is a tripwire, not a proof. FEATURES lists what a change here is likely to
// reach for, with the first Android WebView to support each (from
// @mdn/browser-compat-data 8.1.8); a feature missing from the list goes unseen.
// The full check, done once for the floor itself, scanned every property,
// value, unit, selector and API of the built page against that data.
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const FRONTEND = process.cwd()
const HOST_PROTOCOL = resolve(FRONTEND, '../android/src/main/kotlin/com/nicholaskmitchell/smylte/HostProtocol.kt')

interface Feature {
  name: string
  pattern: RegExp
  /** The first Android WebView with it; Infinity when none has it. */
  webview: number
  /** Only in stylesheets: the pattern would mistake script for it. */
  cssOnly?: boolean
  /** What a WebView without it shows instead, when that is only cosmetic. */
  cosmetic?: string
}

const FEATURES: Feature[] = [
  // What sets the floor today.
  { name: 'oklch()', pattern: /\boklch\(/, webview: 111 },
  { name: 'oklab()', pattern: /\boklab\(/, webview: 111 },
  { name: 'color-mix()', pattern: /\bcolor-mix\(/, webview: 111 },
  { name: 'lab() and lch()', pattern: /(?<![\w.-])(?:lab|lch)\(/, webview: 111, cssOnly: true },
  { name: 'color() with a colour space', pattern: /(?<![\w.-])color\(\s*(?:srgb|display-p3|rec2020|a98-rgb|prophoto-rgb|xyz)/, webview: 111 },
  { name: 'dynamic, small and large viewport units', pattern: /\d(?:dv|sv|lv)(?:h|w|i|b|min|max)\b/, webview: 108 },
  // Newer than the floor.
  { name: 'relative colour syntax (from)', pattern: /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(\s*from\b/, webview: 119 },
  { name: 'light-dark()', pattern: /\blight-dark\(/, webview: 123 },
  { name: 'anchor positioning (anchor-name, anchor())', pattern: /\banchor-name\s*:|(?<![\w.-])anchor\(/, webview: 125 },
  { name: 'position-anchor', pattern: /\bposition-anchor\s*:/, webview: 151 },
  { name: '@starting-style', pattern: /@starting-style\b/, webview: 117 },
  { name: '@scope', pattern: /@scope\b/, webview: 118 },
  { name: 'field-sizing', pattern: /\bfield-sizing\s*:/, webview: 123 },
  { name: 'interpolate-size and calc-size()', pattern: /\binterpolate-size\s*:|\bcalc-size\(/, webview: 129 },
  { name: 'text-box', pattern: /\btext-box(?:-trim|-edge)?\s*:/, webview: 133 },
  { name: 'round(), mod() and rem()', pattern: /(?<![\w.-])(?:round|mod|rem)\(/, webview: 125, cssOnly: true },
  { name: 'transition-behavior', pattern: /\btransition-behavior\s*:|\ballow-discrete\b/, webview: 117 },
  { name: 'popover', pattern: /:popover-open\b|\bpopover=|\b(?:show|hide|toggle)Popover\(/, webview: 114 },
  { name: ':user-valid and :user-invalid', pattern: /:user-(?:in)?valid\b/, webview: 119 },
  { name: '::details-content', pattern: /::details-content\b/, webview: 131 },
  { name: 'scrollend', pattern: /\bscrollend\b|\bonScrollEnd\b/, webview: 114 },
  { name: 'Object.groupBy and Map.groupBy', pattern: /\b(?:Object|Map)\.groupBy\(/, webview: 117 },
  { name: 'Promise.withResolvers', pattern: /\bPromise\.withResolvers\(/, webview: 119 },
  { name: 'URL.canParse', pattern: /\bURL\.canParse\(/, webview: 120 },
  { name: 'Array.fromAsync', pattern: /\bArray\.fromAsync\(/, webview: 121 },
  { name: 'the new Set methods', pattern: /\.(?:union|intersection|difference|symmetricDifference|isSubsetOf|isSupersetOf|isDisjointFrom)\(/, webview: 122 },
  { name: 'URL.parse', pattern: /\bURL\.parse\(/, webview: 126 },
  { name: 'Promise.try', pattern: /\bPromise\.try\(/, webview: 128 },
  { name: 'Intl.DurationFormat', pattern: /\bIntl\.DurationFormat\b/, webview: 129 },
  // Newer than the floor, and only cosmetic without it.
  {
    name: 'font-size-adjust', pattern: /\bfont-size-adjust\s*:/, webview: 127,
    cosmetic: 'text renders at its own x-height, about 5% smaller',
  },
  {
    name: 'safe alignment', pattern: /\b(?:justify|align)-(?:content|items|self)\s*:\s*safe\b/, webview: 115,
    cosmetic: 'recognised but without effect, so an overflowing Focus view stays centred and a short window cuts off its top',
  },
  {
    name: 'scrollbar-width and scrollbar-color', pattern: /\bscrollbar-(?:width|color)\s*:/, webview: Infinity,
    cosmetic: 'no WebView has them; the tab strip hides its scrollbar with ::-webkit-scrollbar',
  },
  {
    name: 'text-wrap: balance or pretty', pattern: /\btext-wrap(?:-style)?\s*:\s*(?:balance|pretty)\b/, webview: 114,
    cosmetic: 'lines wrap as usual',
  },
]

/** The page's own sources: stylesheets, scripts and the document. Tests are not the page. */
function sources(): string[] {
  const out = [join(FRONTEND, 'index.html')]
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name)
      if (entry.isDirectory()) {
        if (path !== join(FRONTEND, 'src/test')) walk(path)
      } else if (/\.(css|ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
        out.push(path)
      }
    }
  }
  walk(join(FRONTEND, 'src'))
  return out
}

/** The text with its comments removed, since comments mention features the page doesn't use. */
function code(path: string): string {
  const text = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, ' ')
  if (path.endsWith('.css')) return text
  // `//` after a colon is a URL, not a comment.
  return text.replace(/<!--[\s\S]*?-->/g, ' ').replace(/(^|[^:\\])\/\/.*$/gm, '$1')
}

function minWebView(): number {
  const m = /const\s+val\s+MIN_WEBVIEW_MAJOR\s*=\s*(\d+)\b/.exec(readFileSync(HOST_PROTOCOL, 'utf8'))
  if (!m) throw new Error('no MIN_WEBVIEW_MAJOR in HostProtocol.kt')
  return Number(m[1])
}

function found(): Map<Feature, string[]> {
  const uses = new Map<Feature, string[]>()
  for (const path of sources()) {
    const text = code(path)
    const isCss = path.endsWith('.css')
    for (const feature of FEATURES) {
      if (feature.cssOnly && !isCss) continue
      if (feature.pattern.test(text)) uses.set(feature, [...(uses.get(feature) ?? []), relative(FRONTEND, path)])
    }
  }
  return uses
}

describe('the Android WebView floor', () => {
  const floor = minWebView()
  const uses = found()

  it('scans the page', () => {
    const files = sources().map((p) => relative(FRONTEND, p))
    expect(files).toContain('index.html')
    expect(files).toContain(join('src', 'styles', 'tokens.css'))
    expect(files).toContain(join('src', 'appearance.ts'))
    expect(files.some((f) => f.includes('.test.'))).toBe(false)
  })

  it('is not below anything the page needs', () => {
    const above = [...uses]
      .filter(([f]) => !f.cosmetic && f.webview > floor)
      .map(([f, files]) => `${f.name} (WebView ${f.webview}) in ${files.join(', ')}`)
    // Each of these would show the page broken on an Android WebView between
    // the floor and its version. Raise MIN_WEBVIEW_MAJOR in HostProtocol.kt (and
    // its tests and docs) to the highest of them, or give the feature a fallback
    // and mark it cosmetic here.
    expect(above, `above the Android floor of ${floor}`).toEqual([])
  })

  it('is set by something the page uses', () => {
    // A floor higher than anything that needs it turns working phones away.
    // Lowering it needs the full check again: below 111 the next steps down
    // are dvh (108), the individual transforms (104) and crypto.randomUUID (92).
    const needed = Math.max(...[...uses.keys()].filter((f) => !f.cosmetic).map((f) => f.webview))
    expect(needed).toBe(floor)
  })

  it('finds a feature where it is used and not where a comment names it', () => {
    const color = FEATURES.find((f) => f.name === 'oklch()')!
    expect(uses.get(color)).toContain(join('src', 'styles', 'tokens.css'))
    expect(uses.get(color)).toContain(join('src', 'appearance.ts'))
    // app.css explains in a comment why it doesn't use :has(); comments are stripped.
    expect(code(join(FRONTEND, 'src/styles/app.css'))).not.toMatch(/\/\*/)
  })
})
