// Field notes: the design system's token files and how the repo stacks on them.
//
// The look's colours, motion and shape come from two files copied verbatim from
// the N.K.M. design system (styles/ds/SOURCE.md). These tests hold the three
// promises that make that safe:
//
//   1. the copies are byte-for-byte the design system's (a hash pin), so a
//      tweak made here instead of upstream fails the build;
//   2. the repo's own Workspace blocks restate every property the design
//      system's copy of Workspace sets, so loading the design system first can
//      never leak its values into Workspace (the repo raised Workspace's
//      --fg-faint to 0.49 for 3:1; the design system ships 0.38);
//   3. the design system files load before tokens.css, in main.tsx and in the
//      browser project's setup alike.
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8')
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')

const PINS: Record<string, string> = {
  'src/styles/ds/themes.css': '7587482214b1547a1eb09f49a5deeb59e4eaebcbfe723a7d5bbcec36edcff071',
  'src/styles/ds/app-motion.css': '299ddb0d09d0d21762d2dd912c437ceb7b2cd130ecd4909543bbb204a91657a1',
}

/** Every custom property declared in the block whose selector is exactly `sel`. */
function propsOf(css: string, sel: string): Set<string> {
  const out = new Set<string>()
  for (const m of strip(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (m[1].trim() !== sel) continue
    for (const p of m[2].matchAll(/(--[\w-]+)\s*:/g)) out.add(p[1])
  }
  return out
}

describe('design system files', () => {
  it.each(Object.entries(PINS))('%s is the design system copy, unedited', (path, sha) => {
    const hash = createHash('sha256').update(readFileSync(resolve(process.cwd(), path))).digest('hex')
    expect(hash, `${path} differs from the design system; edit upstream and copy again`).toBe(sha)
  })

  it('SOURCE.md records the same hashes the test pins', () => {
    const source = read('src/styles/ds/SOURCE.md')
    for (const sha of Object.values(PINS)) expect(source).toContain(sha)
  })
})

describe('the repo shadows the design system copy of Workspace', () => {
  const ds = read('src/styles/ds/themes.css')
  const tokens = read('src/styles/tokens.css')
  it.each([
    ':root[data-preset="workspace"]',
    ':root[data-preset="workspace"][data-theme="dark"]',
  ])('%s restates every property the design system sets', (sel) => {
    const upstream = propsOf(ds, sel)
    expect(upstream.size, `${sel} is gone from ds/themes.css`).toBeGreaterThan(10)
    const ours = propsOf(tokens, sel)
    const missing = [...upstream].filter((p) => !ours.has(p))
    expect(missing, `tokens.css ${sel} would leak these from the design system`).toEqual([])
  })
})

describe('load order', () => {
  const order = (text: string) =>
    [...text.matchAll(/^import '\.{1,2}\/styles\/([\w/.-]+\.css)'/gm)].map((m) => m[1])
  const expected = ['fonts.css', 'ds/themes.css', 'ds/app-motion.css', 'tokens.css', 'app.css',
    'classic.css', 'layout.css', 'fieldnotes.css', 'display.css']

  it('main.tsx loads the design system first, then the repo, then Field notes', () => {
    expect(order(read('src/main.tsx'))).toEqual(expected)
  })

  it('the browser project loads the same sheets in the same order', () => {
    expect(order(read('src/test/browser-setup.ts'))).toEqual(expected)
  })
})

describe('the Field notes lever block', () => {
  const tokens = strip(read('src/styles/tokens.css'))
  const ds = strip(read('src/styles/ds/themes.css'))
  const block = (css: string, sel: string) => {
    const m = new RegExp(`(^|\\n)${sel.replace(/[[\]().*+?^$|]/g, '\\$&')}\\s*\\{([^}]*)\\}`).exec(css)
    return m ? m[2] : ''
  }
  const value = (body: string, prop: string) => new RegExp(`${prop}\\s*:\\s*([^;]+);`).exec(body)?.[1].trim()
  const fn = block(tokens, ':root[data-surface="app"]')
  const upstream = block(ds, ':root[data-surface="app"]')
  const base = block(tokens, ':root')

  it('finds both blocks', () => {
    expect(fn).toContain('--r-xs')
    expect(upstream).toContain('--r-xs')
    expect(value(base, '--radius')).toBe('8px')
  })

  it.each(['--r-xs', '--r-lg'])('%s, derived from --radius, equals the design system at the default', (prop) => {
    // The slider has to keep moving every corner, so the repo derives the two
    // steps the design system writes as literals; at the default radius the
    // derivation must land exactly on the design system's value.
    const radius = parseFloat(value(base, '--radius')!)
    const k = /calc\(var\(--radius\)\s*\*\s*([\d.]+)\)/.exec(value(fn, prop) ?? '')
    expect(k, `${prop} is not derived from --radius`).not.toBeNull()
    expect(`${radius * parseFloat(k![1])}px`).toBe(value(upstream, prop))
  })

  it('sets no colour of its own: colours come from the design system', () => {
    expect(fn).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|oklch\(|hsla?\(/i)
  })
})

describe('fieldnotes.css', () => {
  const css = strip(read('src/styles/fieldnotes.css'))
  // At-rule preludes (`@media (hover: hover) {`) are not selectors.
  const selectors = [...css.replace(/@[^{;]+\{/g, '{').matchAll(/([^{}]+)\{/g)]
    .map((m) => m[1].trim()).filter(Boolean)

  it('has rules to check', () => {
    expect(selectors.length).toBeGreaterThan(10)
  })

  it('scopes every rule to [data-surface="app"], so a preset never sees one', () => {
    // Split a selector list on its top-level commas only: `:is(.a, .b)` is one.
    const split = (list: string) => {
      const out: string[] = []
      let depth = 0, cur = ''
      for (const ch of list) {
        if (ch === '(') depth++
        if (ch === ')') depth--
        if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = '' } else cur += ch
      }
      return [...out, cur.trim()]
    }
    const loose = selectors.flatMap(split)
      .filter((s) => s && !/^(:root)?\[data-surface="app"\]/.test(s) && !/^(from|to|[\d.]+%)$/.test(s))
    expect(loose).toEqual([])
  })

  it('writes no colour, duration, easing or radius as a literal', () => {
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|oklch\(|hsla?\(/i)
    expect(css).not.toMatch(/cubic-bezier\(/)
    expect(css).not.toMatch(/(?<![\w-])\d*\.?\d+m?s\b/)
    for (const m of css.matchAll(/border(?:-[a-z-]+)?-radius\s*:\s*([^;]+);/g)) {
      expect(m[1].trim(), 'a corner takes a --r-* step').toMatch(/^(0|var\(--r-[\w-]+\)(\s+var\(--r-[\w-]+\)|\s+0)*)$/)
    }
  })

  it('scales every font size with --fs-scale', () => {
    // `0` is the one exception: it hides a glyph the drawn mark replaces.
    for (const m of css.matchAll(/font-size\s*:\s*([^;]+);/g)) expect(m[1].trim()).toMatch(/var\(--fs-scale\)|^0$/)
  })
})
