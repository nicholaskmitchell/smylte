import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Both files are read as text rather than imported: index.html is not a module,
// and `?raw` on a stylesheet returns an empty string under this suite's
// `css: false` (see vite.config.ts) — which would make the drift checks below
// pass without ever looking at anything.
const read = (rel: string) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')
const tokensCss = read('./styles/tokens.css')
const indexHtml = read('../index.html')
import {
  APPEARANCE_KEY, DEFAULTS, GROUPS, MAX_THEMES, SHARED_DEFAULTS, TOKENS, TOKEN_NAMES,
  applyTokens, cacheAppearance, defaultValue, isValidToken, isValidValue,
  parseTheme, readCachedAppearance, resolve, sanitizeAppearance, sanitizeTokens,
  serializeTheme, type CustomTheme,
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
