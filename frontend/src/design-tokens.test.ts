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
// The sidebar layout's frame (layout.ts). Held to the same rules as app.css:
// it is the shipped default's frame, so a stray corner or an unpaired family
// here is on every screen.
const layoutCss = strip(read('./styles/layout.css'))
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

  it.each([['tokens.css', tokensCss, 4], ['app.css', appCss, 30], ['layout.css', layoutCss, 6]] as const)('%s rounds only by the scale', (_, css, floor) => {
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

  it('no :has() or :where() in layout.css', () => {
    // :has() for the reason app.css gives beside `.color-dot.custom`: a
    // browser that cannot parse it drops the whole rule. :where() because the
    // frame's rules win by the attribute they are scoped under, and a
    // zero-specificity selector would quietly lose that.
    expect(layoutCss).not.toMatch(/:has\(|:where\(/)
  })

  it('layout.css never reaches into Classic', () => {
    // Every rule is scoped to the sidebar frame: to an element only it
    // renders, or to the shell's attribute. A bare `.content-head` here would
    // restyle Classic's header, which the screenshot comparison would catch
    // only for the screens it happens to take.
    const OWN = /\.appnav|\.tabbar|\.frame(-main)?\b|\.composer-foot|\.today-cols|\.today-side|\.shell\[data-layout="sidebar"\]/
    const selectors = [...layoutCss.matchAll(/([^{}@]+)\{[^{}]*\}/g)]
      .map((m) => m[1].trim())
      .filter((sel) => sel && !/^(from|to|\d+%)$/.test(sel))
      .flatMap((sel) => sel.split(','))
      .map((sel) => sel.trim())
    expect(selectors.length, 'vacuity: the rules were found').toBeGreaterThanOrEqual(40)
    expect(selectors.filter((sel) => !OWN.test(sel))).toEqual([])
    expect(layoutCss).not.toMatch(/data-layout="classic"/)
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

describe('T9 · the sans is fitted, and only the sans', () => {
  // `font-size-adjust` is INHERITED, and the value on <body> is tuned for one
  // face: Hanken Grotesk's 0.493em x-height, taken to 0.516em. Anything set in
  // the serif or the mono underneath it would be rescaled by that face's own
  // x-height instead (Newsreader's 0.426em would grow a fifth), so the rule is
  // that a family never travels without its adjust. Every declaration of a
  // family in the three sheets is checked here, because nothing in a unit test
  // renders the difference, and the browser suite only sees what it mounts.
  const displayCss = strip(read('./styles/display.css'))

  /** Every rule body (selector included) that declares a family, with the
   *  family and the adjust it declares. Nested @media bodies are reached
   *  because the pattern cannot span a brace. */
  const families = (css: string) =>
    [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter((m) => /font-family\s*:/.test(m[2]))
      .map((m) => ({
        rule: m[1].trim(),
        family: /font-family\s*:\s*([^;]+?)\s*(;|$)/.exec(m[2])![1],
        adjust: /font-size-adjust\s*:\s*([^;]+?)\s*(;|$)/.exec(m[2])?.[1],
      }))

  // The sans TEXT is adjusted: the sans, and the note face, which is the sans
  // here and the mono under Classic (whose --sans-adjust is `none`, so the
  // pairing holds in both). The CONTROL face is not: it keeps the sizes T6–T7
  // set for Hanken, and a control sits on the user agent's `line-height:
  // normal`, which an adjust would grow. The glyph face is the mono here and
  // the sans under Classic, and needs no adjust in either.
  const APP: Record<string, string> = {
    'var(--sans)': 'var(--sans-adjust)',
    'var(--font-note)': 'var(--sans-adjust)',
    'var(--font-control)': 'none',
    'var(--serif)': 'none',
    'var(--mono)': 'none',
    'var(--font-glyph)': 'none',
  }
  // Controls that name the sans itself rather than the control face, and so
  // are unadjusted for the control face's reason.
  const SANS_CONTROLS = new Set(['.set-sheet .set-nav-item'])
  // `inherit` is the form controls' own rule, which takes the family and
  // leaves the adjust to the user agent (see the next test), so it pairs with
  // nothing.
  const expected = (f: { rule: string, family: string }) =>
    SANS_CONTROLS.has(f.rule) ? 'none' : f.family === 'inherit' ? undefined : APP[f.family]

  it.each([['tokens.css', tokensCss, 5], ['app.css', appCss, 80], ['layout.css', layoutCss, 2]] as const)(
    'pairs every family in %s with its adjust', (_, css, floor) => {
      const found = families(css)
      expect(found.length, 'vacuity: the families were found').toBeGreaterThanOrEqual(floor)
      const bad = found
        .filter((f) => f.adjust !== expected(f))
        .map((f) => `${f.rule}: ${f.family} with ${f.adjust ?? 'no adjust'}`)
      expect(bad).toEqual([])
      expect(found.filter((f) => SANS_CONTROLS.has(f.rule)).length, 'vacuity: the sans controls are there')
        .toBe(css === appCss ? SANS_CONTROLS.size : 0)
    })

  it('leaves the display unadjusted, every face of it', () => {
    // A display is a poster, drawn under the app's <body> but in its own
    // faces, and render.py draws the same design without any adjust.
    const found = families(displayCss)
    expect(found.length).toBeGreaterThanOrEqual(5)
    expect(found.filter((f) => f.adjust !== 'none').map((f) => f.rule)).toEqual([])
  })

  it('sets the adjust on <body>, and leaves the form controls to the user agent', () => {
    // The user agent's `font` shorthand on a control resets the adjust to
    // none, which is what the control face wants; a rule that handed it back
    // would grow every field and glyph button by a pixel of `normal` line.
    const rule = (sel: string) => {
      const m = new RegExp(`(^|\\n)${sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`).exec(tokensCss)
      if (!m) throw new Error(`no ${sel} rule`)
      return m[2]
    }
    expect(rule('body')).toMatch(/font-size-adjust:\s*var\(--sans-adjust\)/)
    expect(rule('button')).not.toMatch(/font-size-adjust/)
    expect(rule('input, select, textarea')).not.toMatch(/font-size-adjust/)
  })

  it('gives Workspace, and a theme in another sans, the neutral values Classic restates', () => {
    // T9 is a fit for Hanken Grotesk. Workspace sets the system face in all
    // three slots, and a saved theme can set any sans (appearance.ts marks it
    // `data-sans="other"`). Workspace's preset block is the 23 Appearance
    // tokens and only those, so the neutral values are a second block, which
    // the saved themes share.
    const T9 = ['--sans-adjust', '--wght-ui', '--wght-content', '--ls-content']
    const values = (body: string) => Object.fromEntries(
      [...body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].filter((d) => T9.includes(d[1])).map((d) => [d[1], d[2].trim()]))
    const neutral = [...tokensCss.matchAll(/([^{}]+)\{([^}]*)\}/g)]
      .filter((m) => m[1].includes(':root[data-preset="workspace"]') && m[1].includes(':root[data-sans="other"]'))
    expect(neutral, 'one block holds both selectors').toHaveLength(1)
    const workspace = values(neutral[0][2])
    const classic = values(/:root\[data-preset="classic"\]\s*\{([^}]*)\}/.exec(classicCss)![1])
    expect(Object.keys(classic).sort()).toEqual([...T9].sort())
    expect(workspace).toEqual(classic)
  })
})
