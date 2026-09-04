import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { contrast } from './test/contrast'

// Both files are read as text rather than imported: index.html is not a module,
// and `?raw` on a stylesheet returns an empty string under this suite's
// `css: false` (see vite.config.ts) — which would make the drift checks below
// pass without ever looking at anything.
const read = (rel: string) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')
const tokensCss = read('./styles/tokens.css')
const indexHtml = read('../index.html')
import {
  APPEARANCE_KEY, DEFAULTS, FONT_CHOICES, GROUPS, MAX_THEMES, PRESETS, PRESET_PREFIX,
  SHARED_DEFAULTS, TOKENS, TOKEN_NAMES,
  applyTokens, cacheAppearance, defaultValue, findPreset, isValidToken, isValidValue,
  parseTheme, presetSlug, readCachedAppearance, resolve, sanitizeAppearance,
  sanitizeTokens, serializeTheme, type CustomTheme, type Mode,
} from './appearance'

/** Pull `--name: value;` pairs out of one CSS rule block. */
function parseBlock(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(selector + ' {')
  if (start < 0) throw new Error(`no ${selector} block in tokens.css`)
  const body = css.slice(start + selector.length + 2, css.indexOf('}', start))
  const out: Record<string, string> = {}
  for (const line of body.split('\n')) {
    const m = line.match(/^\s*(--[\w-]+)\s*:\s*([^;]+);/)
    if (m) out[m[1]] = m[2].trim()
  }
  return out
}

// ── the guarantee that matters most ─────────────────────────────────────────
// "Do not change the default theme" is the whole premise of this feature, so it
// gets a test rather than a promise. DEFAULTS is a hand-maintained mirror of
// tokens.css (the editor needs to know a token's shipped value even while an
// override is in force, which rules out reading it back from the DOM) — these
// cases are what stop the mirror from drifting off the real stylesheet.

describe('shipped defaults', () => {
  const light = parseBlock(tokensCss, ':root')
  const dark = parseBlock(tokensCss, ':root[data-theme="dark"]')

  it('mirrors every light-mode color in tokens.css', () => {
    for (const [token, value] of Object.entries(DEFAULTS.light)) {
      expect(light[token], `${token} drifted from tokens.css`).toBe(value)
    }
  })

  it('mirrors every dark-mode color in tokens.css', () => {
    for (const [token, value] of Object.entries(DEFAULTS.dark)) {
      expect(dark[token], `${token} drifted from tokens.css`).toBe(value)
    }
  })

  it('mirrors the shared type / shape / density tokens', () => {
    for (const [token, value] of Object.entries(SHARED_DEFAULTS)) {
      expect(light[token], `${token} drifted from tokens.css`).toBe(value)
    }
  })

  it('covers every customizable token with a default', () => {
    for (const token of TOKEN_NAMES) {
      expect(defaultValue(token, 'light'), `${token} has no light default`).toBeTruthy()
      expect(defaultValue(token, 'dark'), `${token} has no dark default`).toBeTruthy()
    }
  })

  it('declares every customizable token in tokens.css', () => {
    // A token in the allowlist that no stylesheet reads would be a control that
    // silently does nothing.
    for (const token of TOKEN_NAMES) {
      expect(token in light, `${token} is not declared in :root`).toBe(true)
    }
  })
})

// ── the contrast the shipped tokens must keep ───────────────────────────────
// 2026-09-03 sweep, test gap. Two closed findings (docs/AUDIT.md: "--fg-faint
// is 2.30:1 against the shipped light background" and "--fg-faint carries real
// text at 2.3:1") raised the token to clear WCAG's 3:1 floor, and the second
// asked for "a contrast assertion to that same test so the token cannot drift
// back". Nothing computed a ratio: the mirror tests above only hold DEFAULTS to
// tokens.css, so reverting BOTH files to `rgba(20, 19, 26, 0.36)` passed the
// whole suite. This is the number, measured the way the findings measured it —
// sRGB compositing, WCAG 2.x luminance, the WORST of the three backgrounds a
// token is painted over — for every block tokens.css ships.
//
// Only the bars every block clears TODAY are asserted, because a pin is a
// drift guard and not a new finding: `--fg-faint` at 3.0 (it is UI-component
// colour as well as caption colour), `--fg-muted` at AA text (4.5), and the
// three semantic colours at the 3.0 non-text floor. Light `--accent` and
// `--ok` measure 3.6–4.3 on `--paper` and so do NOT clear AA text; that is a
// palette decision recorded separately, not something this test settles.

describe('shipped contrast', () => {
  const BLOCKS: Array<[string, string]> = [
    ['light', ':root'],
    ['dark', ':root[data-theme="dark"]'],
    ['workspace light', ':root[data-preset="workspace"]'],
    ['workspace dark', ':root[data-preset="workspace"][data-theme="dark"]'],
  ]
  const BACKGROUNDS = ['--bg', '--bg-elev', '--paper']

  /** The lowest ratio a token reaches over any of the three backgrounds. */
  const worst = (block: Record<string, string>, token: string) =>
    Math.min(...BACKGROUNDS.map((bg) => contrast(block[token], block[bg])))

  it.each(BLOCKS)('%s: --fg-faint clears 3:1 on every background it is painted over',
    (_name, selector) => {
      const block = parseBlock(tokensCss, selector)
      // The value the two findings fixed was 2.30 (light) and 2.75 (dark).
      expect(worst(block, '--fg-faint')).toBeGreaterThanOrEqual(3.0)
    })

  it.each(BLOCKS)('%s: --fg-muted is AA text on every background', (_name, selector) => {
    const block = parseBlock(tokensCss, selector)
    expect(worst(block, '--fg-muted')).toBeGreaterThanOrEqual(4.5)
  })

  it.each(BLOCKS)('%s: the semantic colours clear the non-text floor', (_name, selector) => {
    const block = parseBlock(tokensCss, selector)
    for (const token of ['--accent', '--warn', '--ok']) {
      expect(worst(block, token), token).toBeGreaterThanOrEqual(3.0)
    }
  })

  it('reads every syntax tokens.css uses, so a token it cannot parse fails loudly', () => {
    // The helper's own vacuity guard: an unparseable colour throws rather than
    // composites to black, which would pass every ratio above by accident.
    expect(contrast('#FFFFFF', '#000000')).toBeCloseTo(21, 1)
    // The value the two findings measured: 0.36 alpha over the light --bg.
    expect(contrast('rgba(20, 19, 26, 0.36)', '#FBFAF7')).toBeCloseTo(2.30, 1)
    expect(contrast('oklch(0.60 0.19 42)', '#FFFFFF')).toBeGreaterThan(4)
    expect(() => contrast('var(--fg)', '#FFFFFF')).toThrow()
  })
})

// ── the shipped presets ─────────────────────────────────────────────────────
// A preset is applied by tokens.css, not by this module, so the module's copy of
// it is *only* ever read by the editor — which means a value that drifted off
// the stylesheet would show a wrong number in the panel and seed a fork that
// does not match what the user was looking at, with nothing else going wrong.
// That is precisely the kind of bug that survives a manual pass, hence these.

describe('shipped presets', () => {
  it('mirror the tokens.css block they are applied from', () => {
    for (const preset of PRESETS) {
      const slug = preset.id.slice(PRESET_PREFIX.length)
      const light = parseBlock(tokensCss, `:root[data-preset="${slug}"]`)
      const dark = parseBlock(tokensCss, `:root[data-preset="${slug}"][data-theme="dark"]`)
      expect(preset.light, `${preset.id} light drifted from tokens.css`).toEqual(light)
      expect(preset.dark, `${preset.id} dark drifted from tokens.css`).toEqual(dark)
    }
  })

  it('restate the whole design in both modes', () => {
    // Unlike a theme, a preset is not sparse — a token it forgets would fall
    // through to Smylte's value and read as a rendering bug in one mode only.
    for (const preset of PRESETS) {
      expect(Object.keys(preset.light).sort()).toEqual([...TOKEN_NAMES].sort())
      expect(Object.keys(preset.dark).sort()).toEqual([...TOKEN_NAMES].sort())
    }
  })

  it('survive the validator they will be seeded through', () => {
    // A typo'd oklch() would otherwise be dropped silently when a fork is
    // sanitized on its way to the server.
    for (const preset of PRESETS) {
      expect(sanitizeTokens(preset.light), `${preset.id} light`).toEqual(preset.light)
      expect(sanitizeTokens(preset.dark), `${preset.id} dark`).toEqual(preset.dark)
    }
  })

  it('take ids in the reserved namespace, unique and short enough to store', () => {
    const seen = new Set<string>()
    for (const preset of PRESETS) {
      expect(preset.id.startsWith(PRESET_PREFIX)).toBe(true)
      expect(preset.id.length).toBeLessThanOrEqual(64)   // the backend's max_length
      expect(seen.has(preset.id), `${preset.id} is declared twice`).toBe(false)
      seen.add(preset.id)
    }
  })

  it('name font stacks the editor actually offers', () => {
    // Otherwise forking a preset lands the type controls on "Custom (…)" for a
    // stack the app itself ships.
    const tiers = { '--serif': 'serif', '--sans': 'sans', '--mono': 'mono' } as const
    for (const preset of PRESETS) {
      for (const [token, tier] of Object.entries(tiers)) {
        for (const mode of ['light', 'dark'] as Mode[]) {
          const stack = preset[mode][token]
          expect(FONT_CHOICES[tier].some((c) => c.stack === stack),
            `${preset.id} ${mode} ${token} is not in FONT_CHOICES.${tier}`).toBe(true)
        }
      }
    }
  })

  it('resolve to an attribute, not to inline overrides', () => {
    // The whole point of the split: applyTokens must *clear* the inline layer
    // for a preset, or a saved theme's leftovers would sit on top of it.
    const app = { active: PRESETS[0].id, themes: [] }
    expect(resolve(app, 'light')).toEqual({})
    expect(presetSlug(app.active)).toBe('workspace')
    expect(presetSlug('preset:nope')).toBe(null)
    expect(presetSlug(null)).toBe(null)
    expect(findPreset(PRESETS[0].id)).toEqual(PRESETS[0])
  })
})

// ── the pre-paint script ────────────────────────────────────────────────────
// index.html restates the token list and the value guard because it runs before
// the bundle exists. Two copies of a security check is exactly the kind of thing
// that rots, so the copies are compared here.

describe('pre-paint script in index.html', () => {
  const html = indexHtml

  it('honours exactly the tokens the app allows', () => {
    const block = html.match(/var TOKENS = \[([\s\S]*?)\]/)
    expect(block, 'no TOKENS array found in the pre-paint script').toBeTruthy()
    const inline = [...block![1].matchAll(/'(--[\w-]+)'/g)].map((m) => m[1])
    expect(inline.sort()).toEqual([...TOKEN_NAMES].sort())
  })

  it('uses the same rejection pattern as the module', () => {
    const inline = html.match(/var BAD = (\/.*\/i)\n/)
    expect(inline, 'no BAD regex found in the pre-paint script').toBeTruthy()
    // Both sides must reject the same payloads, however each is written.
    const hostile = [
      'url(https://evil.example/x.png)',
      'red; background: url(//evil)',
      '}html{display:none',
      '@import "evil.css"',
      'expression(alert(1))',
    ]
    const bad = new RegExp(inline![1].slice(1, -2), 'i')
    for (const v of hostile) {
      expect(bad.test(v), `pre-paint accepted ${v}`).toBe(true)
      expect(isValidValue('color', v), `module accepted ${v}`).toBe(false)
    }
  })

  it('reads the same localStorage key the app writes', () => {
    expect(html).toContain(`'${APPEARANCE_KEY}'`)
  })

  it('knows every preset slug, and its background in both modes', () => {
    // This copy is what stops a preset flashing Smylte on every load, and it
    // doubles as the allowlist of attribute values the script will write — so a
    // preset missing here fails open (default look) rather than closed.
    const start = html.indexOf('var PRESET_BG = {')
    expect(start, 'no PRESET_BG found in the pre-paint script').toBeGreaterThan(-1)
    const literal = html.slice(start, html.indexOf('\n        }', start))
    const inline: Record<string, Record<string, string>> = {}
    for (const m of literal.matchAll(
      /'([\w-]+)':\s*\{\s*'light':\s*'([^']*)',\s*'dark':\s*'([^']*)'\s*\}/g
    )) {
      inline[m[1]] = { light: m[2], dark: m[3] }
    }
    expect(Object.keys(inline).sort())
      .toEqual(PRESETS.map((p) => p.id.slice(PRESET_PREFIX.length)).sort())
    for (const preset of PRESETS) {
      const slug = preset.id.slice(PRESET_PREFIX.length)
      expect(inline[slug].light, `${slug} light background drifted`).toBe(preset.light['--bg'])
      expect(inline[slug].dark, `${slug} dark background drifted`).toBe(preset.dark['--bg'])
    }
  })
})

// ── validation ──────────────────────────────────────────────────────────────

describe('isValidValue', () => {
  it('accepts the color notations the design system is authored in', () => {
    for (const v of ['#FBFAF7', '#fff', 'oklch(0.60 0.19 42)', 'rgba(20, 19, 26, 0.60)',
      'transparent', 'color-mix(in oklch, var(--accent) 30%, transparent)']) {
      expect(isValidValue('color', v), v).toBe(true)
    }
  })

  it('rejects anything that could escape the property or phone home', () => {
    for (const v of ['url(//evil)', 'red; color: blue', 'red}html{x:y', '@import x',
      'expression(1)', 'javascript:1', 'image-set(//x)', 'a'.repeat(121)]) {
      expect(isValidValue('color', v), v).toBe(false)
    }
  })

  it('rejects unbalanced parens, which would leak into the next declaration', () => {
    expect(isValidValue('color', 'oklch(0.6 0.1 40')).toBe(false)
    expect(isValidValue('color', 'oklch(0.6 0.1 40))')).toBe(false)
  })

  it('rejects color functions that are not color functions', () => {
    expect(isValidValue('color', 'attr(href)')).toBe(false)
    expect(isValidValue('color', 'element(#x)')).toBe(false)
  })

  it('holds lengths, scales and font stacks to their own shapes', () => {
    expect(isValidValue('length', '12px')).toBe(true)
    expect(isValidValue('length', '12')).toBe(false)
    expect(isValidValue('length', '12em')).toBe(false)
    expect(isValidValue('scale', '1.15')).toBe(true)
    expect(isValidValue('scale', '11px')).toBe(false)
    expect(isValidValue('font', '"Inter", sans-serif')).toBe(true)
    expect(isValidValue('font', 'url(evil.woff)')).toBe(false)
  })
})

describe('isValidToken', () => {
  it('refuses tokens outside the allowlist', () => {
    expect(isValidToken('--not-a-token', '#fff')).toBe(false)
    expect(isValidToken('--accent', '#fff')).toBe(true)
  })

  it('enforces each token’s range', () => {
    expect(isValidToken('--radius', '8px')).toBe(true)
    expect(isValidToken('--radius', '99px')).toBe(false)     // max 24
    expect(isValidToken('--fs-scale', '1.2')).toBe(true)
    expect(isValidToken('--fs-scale', '9')).toBe(false)      // max 1.4
    expect(isValidToken('--row-y', '1px')).toBe(false)       // min 2
  })

  it('refuses a value of the wrong kind for the token', () => {
    expect(isValidToken('--accent', '12px')).toBe(false)
    expect(isValidToken('--radius', 'oklch(0.6 0.1 40)')).toBe(false)
  })

  it('holds a keyword token to its own closed set', () => {
    expect(isValidToken('--label-case', 'uppercase')).toBe(true)
    expect(isValidToken('--label-case', 'none')).toBe(true)
    // Real CSS keywords that are simply not offered, and a value of another kind.
    expect(isValidToken('--label-case', 'lowercase')).toBe(false)
    expect(isValidToken('--label-case', 'capitalize')).toBe(false)
    expect(isValidToken('--label-case', '#fff')).toBe(false)
    // A bare keyword is a legal *color*, so the kind must not be waved through
    // on the strength of the value alone.
    expect(isValidValue('keyword', 'uppercase')).toBe(false)
  })

  it('bounds label tracking', () => {
    expect(isValidToken('--tracking', '0')).toBe(true)
    expect(isValidToken('--tracking', '1.5')).toBe(true)
    expect(isValidToken('--tracking', '4')).toBe(false)     // max 1.5
    expect(isValidToken('--tracking', '2px')).toBe(false)
  })
})

describe('sanitizeTokens', () => {
  it('keeps the good and drops the rest without throwing', () => {
    expect(sanitizeTokens({
      '--accent': '#ff0000',
      '--nope': '#ff0000',
      '--bg': 'url(//evil)',
      '--radius': '4px',
    })).toEqual({ '--accent': '#ff0000', '--radius': '4px' })
  })

  it('survives junk in place of an object', () => {
    for (const junk of [null, undefined, 'x', 42, []]) {
      expect(sanitizeTokens(junk)).toEqual({})
    }
  })
})

describe('sanitizeAppearance', () => {
  const theme = (over: Partial<CustomTheme> = {}): CustomTheme => ({
    id: 't1', name: 'Mine', base: 'light', light: { '--accent': '#ff0000' }, dark: {}, ...over,
  })

  it('clears an active id that points at no theme', () => {
    expect(sanitizeAppearance({ active: 'ghost', themes: [] }).active).toBe(null)
  })

  it('keeps an active id that resolves', () => {
    expect(sanitizeAppearance({ active: 't1', themes: [theme()] }).active).toBe('t1')
  })

  it('drops themes missing an id or a name', () => {
    const out = sanitizeAppearance({ themes: [theme(), { name: 'no id' }, { id: 'x' }] })
    expect(out.themes).toHaveLength(1)
  })

  it('caps how many themes can be stored', () => {
    const many = Array.from({ length: MAX_THEMES + 10 }, (_, i) => theme({ id: `t${i}` }))
    expect(sanitizeAppearance({ themes: many }).themes!.length).toBe(MAX_THEMES)
  })

  it('scrubs hostile token values nested inside a theme', () => {
    const out = sanitizeAppearance({
      active: 't1',
      themes: [theme({ light: { '--bg': 'url(//evil)', '--accent': '#00ff00' } })],
    })
    expect(out.themes![0].light).toEqual({ '--accent': '#00ff00' })
  })

  it('keeps an active preset id even with no themes of the user’s own', () => {
    const out = sanitizeAppearance({ active: PRESETS[0].id, themes: [] })
    expect(out.active).toBe(PRESETS[0].id)
  })

  it('clears an active preset id this build does not ship', () => {
    expect(sanitizeAppearance({ active: 'preset:gone', themes: [] }).active).toBe(null)
  })

  it('drops a saved theme squatting in the preset namespace', () => {
    // Otherwise a hand-edited blob could park a theme on a preset's id, where
    // the attribute path would quietly shadow it — a theme that is selected,
    // editable, and has no effect.
    const out = sanitizeAppearance({
      active: PRESETS[0].id,
      themes: [theme({ id: PRESETS[0].id, name: 'Impostor' }), theme()],
    })
    expect(out.themes!.map((t) => t.id)).toEqual(['t1'])
    expect(out.active).toBe(PRESETS[0].id)
  })

  it('survives junk', () => {
    for (const junk of [null, 'x', 42]) expect(sanitizeAppearance(junk)).toEqual({})
  })
})

// ── resolution + application ────────────────────────────────────────────────

describe('resolve', () => {
  const app = {
    active: 't1',
    themes: [{
      id: 't1', name: 'Mine', base: 'light' as const,
      light: { '--accent': '#ff0000' }, dark: { '--accent': '#00ff00' },
    }],
  }

  it('returns nothing when the shipped default is active', () => {
    expect(resolve({ active: null, themes: app.themes }, 'light')).toEqual({})
    expect(resolve(null, 'light')).toEqual({})
    expect(resolve(undefined, 'light')).toEqual({})
  })

  it('picks the map for the mode in play', () => {
    expect(resolve(app, 'light')).toEqual({ '--accent': '#ff0000' })
    expect(resolve(app, 'dark')).toEqual({ '--accent': '#00ff00' })
  })

  it('falls back to the default when active names a missing theme', () => {
    expect(resolve({ active: 'gone', themes: app.themes }, 'light')).toEqual({})
  })
})

describe('applyTokens', () => {
  it('writes overrides as inline properties, leaving :root alone', () => {
    const el = document.createElement('html')
    applyTokens(el, { '--accent': '#ff0000', '--radius': '6px' })
    expect(el.style.getPropertyValue('--accent')).toBe('#ff0000')
    expect(el.style.getPropertyValue('--radius')).toBe('6px')
  })

  it('is lossless to reset — the shipped theme always comes back', () => {
    const el = document.createElement('html')
    applyTokens(el, { '--accent': '#ff0000', '--bg': '#000000', '--radius': '6px' })
    applyTokens(el, {})
    for (const token of TOKEN_NAMES) expect(el.style.getPropertyValue(token)).toBe('')
    expect(el.getAttribute('style')).toBeFalsy()
  })

  it('clears a token that the new theme does not set', () => {
    const el = document.createElement('html')
    applyTokens(el, { '--accent': '#ff0000' })
    applyTokens(el, { '--bg': '#000000' })
    expect(el.style.getPropertyValue('--accent')).toBe('')
    expect(el.style.getPropertyValue('--bg')).toBe('#000000')
  })

  it('never applies a value that failed validation', () => {
    const el = document.createElement('html')
    applyTokens(el, { '--bg': 'url(//evil)', '--nope': 'red' })
    expect(el.getAttribute('style')).toBeFalsy()
  })
})

// ── persistence + portability ───────────────────────────────────────────────

describe('the pre-paint cache', () => {
  it('round-trips an active theme', () => {
    const app = {
      active: 't1',
      themes: [{ id: 't1', name: 'Mine', base: 'light' as const, light: { '--accent': '#ff0000' }, dark: {} }],
    }
    cacheAppearance(app)
    expect(readCachedAppearance()).toEqual(app)
  })

  it('clears the key when the shipped default is active, so nothing is applied', () => {
    cacheAppearance({ active: null, themes: [] })
    expect(localStorage.getItem(APPEARANCE_KEY)).toBe(null)
    expect(readCachedAppearance()).toBe(null)
  })

  it('keeps the key for a preset, which has no themes to store', () => {
    // The `!active` shortcut that clears the key for the default must not also
    // clear it for a preset — that would flash Smylte on every reload.
    cacheAppearance({ active: PRESETS[0].id, themes: [] })
    expect(localStorage.getItem(APPEARANCE_KEY)).toBeTruthy()
    expect(readCachedAppearance()!.active).toBe(PRESETS[0].id)
  })

  it('returns null rather than throwing on a corrupt blob', () => {
    localStorage.setItem(APPEARANCE_KEY, '{not json')
    expect(readCachedAppearance()).toBe(null)
  })

  it('scrubs a tampered blob instead of trusting it', () => {
    localStorage.setItem(APPEARANCE_KEY, JSON.stringify({
      active: 't1',
      themes: [{ id: 't1', name: 'x', light: { '--bg': 'url(//evil)' }, dark: {} }],
    }))
    expect(readCachedAppearance()!.themes![0].light).toEqual({})
  })
})

describe('export / import', () => {
  const theme: CustomTheme = {
    id: 't1', name: 'Midnight', base: 'dark',
    light: { '--accent': '#ff0000' }, dark: { '--accent': '#00ff00', '--radius': '4px' },
  }

  it('round-trips a theme through a file', () => {
    const back = parseTheme(serializeTheme(theme), 'new-id')
    expect(back).toEqual({ ...theme, id: 'new-id' })
  })

  it('refuses files that are not Smylte themes', () => {
    expect(parseTheme('not json', 'id')).toBe(null)
    expect(parseTheme('{"hello":1}', 'id')).toBe(null)
    expect(parseTheme(JSON.stringify({ smylte_theme: 99, light: {} }), 'id')).toBe(null)
  })

  it('refuses a theme whose overrides were all rejected', () => {
    const hostile = JSON.stringify({ smylte_theme: 1, name: 'x', light: { '--bg': 'url(//evil)' } })
    expect(parseTheme(hostile, 'id')).toBe(null)
  })

  it('imports what it can from a file written by a newer client', () => {
    const forward = JSON.stringify({
      smylte_theme: 1, name: 'Future', light: { '--accent': '#ff0000', '--unknown-token': 'x' },
    })
    expect(parseTheme(forward, 'id')!.light).toEqual({ '--accent': '#ff0000' })
  })
})

describe('TOKENS metadata', () => {
  it('assigns every token to a rendered group', () => {
    for (const [token, spec] of Object.entries(TOKENS)) {
      expect(GROUPS, `${token} is in group "${spec.group}", which nothing renders`)
        .toContain(spec.group)
    }
  })
})

// ── the mobile 16px input floor ─────────────────────────────────────────────
// app.css sets `.input { font-size: max(16px, …) }` inside the mobile block
// with a comment calling the floor load-bearing: below 16px, iOS Safari zooms
// the page on focus, and once it zooms it does not zoom back — every later tap
// lands offset from what the user sees. Any rule that outranks it has to put it
// back, and the file already does that twice for higher-specificity selectors.
// `.appear-text` outranked it a third way: the same (0,1,0) specificity, but
// declared later in the file, so it won on source order in every viewport.

describe('the mobile input floor', () => {
  const appCss = read('./styles/app.css')

  /** The text of the `@media (max-width: 720px)` blocks, brace-matched. */
  const mobileBlocks = (() => {
    const out: string[] = []
    const re = /@media \(max-width: 720px\)\s*\{/g
    for (let m = re.exec(appCss); m; m = re.exec(appCss)) {
      let depth = 1
      let i = m.index + m[0].length
      const from = i
      while (i < appCss.length && depth > 0) {
        if (appCss[i] === '{') depth++
        else if (appCss[i] === '}') depth--
        i++
      }
      out.push(appCss.slice(from, i - 1))
    }
    return out
  })()

  it('finds the mobile blocks at all', () => {
    expect(mobileBlocks.length).toBeGreaterThan(0)
  })

  const declaredMobile = (selector: string) =>
    mobileBlocks.some((b) =>
      new RegExp(`(^|[,{}\\s])${selector.replace('.', '\\.')}\\s*\\{[^}]*font-size:\\s*max\\(16px`, 'm')
        .test(b)
      || new RegExp(`${selector.replace('.', '\\.')}[^{}]*\\{[^}]*font-size:\\s*max\\(16px`)
        .test(b))

  it.each([
    ['.input', 'the floor itself'],
    ['.bulk-row .input', 'a (0,2,0) selector that outranks it'],
    ['.sched-range .input', 'a (0,2,0) selector that outranks it'],
    ['.appear-text', 'a (0,1,0) selector that outranks it on source order'],
  ])('keeps %s at the floor on mobile (%s)', (selector) => {
    expect(declaredMobile(selector)).toBe(true)
  })

  it('leaves the desktop size alone, so only the mobile floor changed', () => {
    // The designed 12px still stands outside the media query — the fix raises
    // the floor on phones, it does not resize the control everywhere.
    const desktopRule = '.appear-text { font-size: calc(12px * var(--fs-scale)); }'
    expect(appCss).toContain(desktopRule)
    expect(mobileBlocks.some((b) => b.includes(desktopRule))).toBe(false)
  })
})
