// The refinement's token layer, and Classic's hold on it.
//
// The September 2026 refinement changed the default design without changing a
// colour, and Classic keeps the design before it selectable. Both rest on one
// arrangement, and this file is what keeps it from quietly coming apart:
//
//   * tokens.css declares every value the refinement changed as a LEVER, and
//     app.css reads the lever where the old literal stood.
//   * classic.css sets every one of those levers back, and does nothing else
//     a variant rule could be beaten by.
//
// A lever classic.css forgets leaks the current design into Classic; a lever
// it invents does nothing; a customizable token or `--gutter` declared there
// overrides the user and the mobile block. Nothing renders wrong in a unit
// test when any of that happens, which is why it is checked as text.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { FONT_CHOICES, TOKENS } from './appearance'

const read = (rel: string) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')

const tokensCss = strip(read('./styles/tokens.css'))
const appCss = strip(read('./styles/app.css'))
const classicCss = strip(read('./styles/classic.css'))
const fontsCss = strip(read('./styles/fonts.css'))

/** The custom properties declared in the first block that opens with
 *  `opener` (a selector, then `{`), in declaration order. Comments are
 *  stripped first, so a brace inside one cannot end the block early. */
function declared(css: string, opener: RegExp): string[] {
  const m = opener.exec(css)
  if (!m) throw new Error(`no block matching ${opener}`)
  const start = m.index + m[0].length
  const body = css.slice(start, css.indexOf('}', start))
  return [...body.matchAll(/(--[\w-]+)\s*:/g)].map((d) => d[1])
}

// The FIXED-token block is the :root block that holds --r-sm; the first :root
// block is the 23 customizable tokens and holds none of these.
const fixedBlock = (() => {
  const blocks = [...tokensCss.matchAll(/(^|\n):root\s*\{/g)]
  for (const b of blocks) {
    const start = b.index! + b[0].length
    const body = tokensCss.slice(start, tokensCss.indexOf('}', start))
    if (/--r-sm\s*:/.test(body)) return [...body.matchAll(/(--[\w-]+)\s*:/g)].map((d) => d[1])
  }
  throw new Error('no :root block declares --r-sm')
})()

// The radius SCALE is derived from --radius, which Classic's preset block sets
// to 0px — so Classic squares it without restating a single step. Every other
// fixed token is a lever.
const DERIVED = new Set(['--r-xs', '--r-sm', '--r-md', '--r-lg', '--r-pill', '--r-dot', '--r-thumb', '--r-menu-item'])
const levers = fixedBlock.filter((t) => !DERIVED.has(t))
const classicLevers = declared(classicCss, /:root\[data-preset="classic"\]\s*\{/)

describe('Classic restates every lever, and only levers', () => {
  it('finds both blocks', () => {
    // Vacuity guard: a parse that returned nothing would pass everything below.
    expect(levers.length).toBeGreaterThan(30)
    expect(classicLevers.length).toBeGreaterThan(30)
  })

  it('sets back every lever the current design declares', () => {
    const missing = levers.filter((t) => !classicLevers.includes(t))
    expect(missing, 'Classic would take the current design\'s value for these').toEqual([])
  })

  it('and sets nothing tokens.css does not declare as one', () => {
    const extra = classicLevers.filter((t) => !levers.includes(t))
    expect(extra, 'these set nothing any rule reads').toEqual([])
  })

  it('never sets a customizable token, the gutter, or a structural width', () => {
    // The 23 are the preset block's (mirrored in appearance.ts), and an inline
    // override of a user's own theme must outrank them — which a rule here,
    // loaded after app.css at (0,2,0), would not. `--gutter` is re-declared by
    // the mobile block, which classic.css would beat on source order.
    const owned = new Set([...Object.keys(TOKENS), '--gutter', '--check-size', '--today-mark-w', '--today-line'])
    const everything = [...classicCss.matchAll(/(--[\w-]+)\s*:/g)].map((d) => d[1])
    expect(everything.filter((t) => owned.has(t))).toEqual([])
  })

  it('declares each lever once in each file', () => {
    const dupes = (xs: string[]) => xs.filter((x, i) => xs.indexOf(x) !== i)
    expect(dupes(levers)).toEqual([])
    expect(dupes(classicLevers)).toEqual([])
  })
})

describe('the radius scale', () => {
  // The rule the old "rounding opt-in" block at the end of app.css used to
  // hold by being the one place a corner was set: every corner in these two
  // sheets is square or a step of the scale. A bare `var(--radius)` would not
  // follow the scale, a literal px would not follow the slider or Classic,
  // and 50% is a perfect circle (S3).
  const corners = (css: string) =>
    [...css.matchAll(/border-radius\s*:\s*([^;]+);/g)].map((m) => m[1].trim())

  it.each([['tokens.css', tokensCss, 4], ['app.css', appCss, 30]] as const)('%s rounds only by the scale', (_, css, floor) => {
    const bad = corners(css).filter((v) => !(v === '0' || /^(var\(--r-[\w-]+\)|0)(\s+(var\(--r-[\w-]+\)|0))*$/.test(v)))
    expect(bad).toEqual([])
    expect(corners(css).length, 'vacuity: the scale is used where it should be').toBeGreaterThanOrEqual(floor)
  })

  it('no :where() in app.css', () => {
    // classic.css uses it to add no specificity, and the cascade checks in
    // mobile-layout.test.ts do not model it — so it stays out of the sheet
    // those checks read.
    expect(appCss).not.toMatch(/:where\(/)
  })
})

describe('every self-hosted family is actually hosted', () => {
  // A preset's fonts are never fetched by `ensureFonts` (a preset is not in
  // `themes`), so a FONT_CHOICES entry with no Google spec that names a family
  // fonts.css does not declare renders in the fallback — silently, and only
  // for whoever picks it. That is Classic's Fraunces and Inter, and the
  // shipped three.
  const faces = new Set([...fontsCss.matchAll(/font-family:\s*'([^']+)'/g)].map((m) => m[1]))
  const hosted = Object.values(FONT_CHOICES).flat()
    .filter((c) => !c.google)
    .map((c) => /^"([^"]+)"/.exec(c.stack)?.[1])
    .filter((f): f is string => !!f)

  it('finds them', () => {
    expect(hosted).toEqual(expect.arrayContaining(['Newsreader', 'Hanken Grotesk', 'JetBrains Mono', 'Fraunces', 'Inter']))
  })

  it.each(['Newsreader', 'Hanken Grotesk', 'JetBrains Mono', 'Fraunces', 'Inter'])('%s has an @font-face', (family) => {
    expect(faces.has(family)).toBe(true)
  })

  it('and no family is offered as self-hosted that is not', () => {
    expect(hosted.filter((f) => !faces.has(f))).toEqual([])
  })
})
