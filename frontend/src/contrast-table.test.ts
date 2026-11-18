// The Field notes contrast table.
//
// Every pair of tokens that Field notes ever paints together is listed here
// with its role, and each is checked in light and dark against the WCAG floor
// for that role: 4.5:1 for text, 3:1 for marks and control edges (WCAG 1.4.11).
// The values are read from ds/themes.css, the design system's own file, so the
// table is about what ships rather than about a copy.
//
// `npm run contrast` writes the same table to docs/contrast.md, for the merge
// request. Pairs that fail are not in the passing list: they are the "never
// paired" rows at the end, which say which combinations the stylesheets must
// not produce, and the browser contrast walk (backlog.sep03.browser.test.tsx)
// measures what the pages actually paint.
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { contrast } from './contrast'

const css = readFileSync(resolve(process.cwd(), 'src/styles/ds/themes.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '')

function block(sel: string): Record<string, string> {
  const re = new RegExp(`(^|\\n)${sel.replace(/[[\]().*+?^$|]/g, '\\$&')}\\s*\\{([^}]*)\\}`)
  const body = re.exec(css)?.[2] ?? ''
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}

const light = block(':root[data-surface="app"]')
const THEMES = {
  light,
  dark: { ...light, ...block(':root[data-surface="app"][data-theme="dark"]') },
}

const SURFACES = ['--bg', '--bg-elev', '--paper', '--bg-float'] as const

type Pair = { fg: string; bg: string; role: 'text' | 'mark'; what: string }

/** Text and marks on each of the four grounds. */
const ON_SURFACES: Omit<Pair, 'bg'>[] = [
  { fg: '--fg', role: 'text', what: 'body text, titles' },
  { fg: '--fg-muted', role: 'text', what: 'meta, secondary text, quiet text (--tx-quiet)' },
  { fg: '--accent', role: 'text', what: 'coral ink as text: links, margin-note times' },
  { fg: '--warn', role: 'text', what: 'a warning, always beside a word' },
  { fg: '--ok', role: 'text', what: 'a confirmation, always beside a word' },
  { fg: '--fg', role: 'mark', what: 'the pen: icons, checkbox frames, drawings' },
  { fg: '--accent', role: 'mark', what: 'ticks, strikes, the tab underline, the focus ring' },
  { fg: '--rule-strong', role: 'mark', what: 'control edges, quiet marks (--mark-quiet)' },
  { fg: '--pri-high', role: 'mark', what: 'priority mark, beside the task title' },
  { fg: '--pri-med', role: 'mark', what: 'priority mark, beside the task title' },
  { fg: '--pri-low', role: 'mark', what: 'priority mark, beside the task title' },
]

/** Pairs on a fill rather than a ground. */
const ON_FILLS: Pair[] = [
  { fg: '--bg', bg: '--fg', role: 'text', what: 'a primary button: paper on ink' },
  { fg: '--on-accent', bg: '--accent-fill', role: 'text', what: 'text or a glyph on a coral fill' },
  { fg: '--fg', bg: '--highlight', role: 'text', what: 'the highlighter, behind ink text only' },
  { fg: '--fg', bg: '--wash', role: 'text', what: 'ink over the sage wash' },
  { fg: '--accent-fill', bg: '--bg', role: 'mark', what: 'a coral fill (dark only; outlined in ink in light)' },
]

/** Combinations the stylesheets must never produce, with why. */
const NEVER: Pair[] = [
  { fg: '--fg-faint', bg: '--bg', role: 'text', what: 'faint is decoration and disabled only' },
  { fg: '--fg-muted', bg: '--highlight', role: 'text', what: 'the highlighter takes --fg text only' },
  { fg: '--accent', bg: '--highlight', role: 'text', what: 'the highlighter takes --fg text only' },
  { fg: '--warn', bg: '--highlight', role: 'text', what: 'the highlighter takes --fg text only' },
  { fg: '--pri-med', bg: '--highlight', role: 'mark', what: 'no priority mark on the highlighter' },
  { fg: '--accent-fill', bg: '--bg', role: 'mark', what: 'a coral fill in light, unless outlined in ink' },
]

const floor = (role: Pair['role']) => (role === 'text' ? 4.5 : 3)
const ratio = (theme: keyof typeof THEMES, p: Pair) => {
  const t = THEMES[theme]
  return contrast(t[p.fg], t[p.bg])
}

const PAIRS: Pair[] = [
  ...ON_SURFACES.flatMap((p) => SURFACES.map((bg) => ({ ...p, bg }))),
  ...ON_FILLS,
]

/** Which pairs apply in which theme: the coral fill is outlined in light. */
const applies = (theme: keyof typeof THEMES, p: Pair) =>
  !(theme === 'light' && p.fg === '--accent-fill' && p.bg === '--bg')

describe('Field notes contrast', () => {
  it('reads both themes from the design system', () => {
    for (const t of Object.values(THEMES)) for (const v of [...SURFACES, '--fg', '--accent-fill']) {
      expect(t[v], `${v} missing from ds/themes.css`).toMatch(/^#|^rgba?\(/)
    }
  })

  for (const theme of ['light', 'dark'] as const) {
    it.each(PAIRS.filter((p) => applies(theme, p)).map((p) => [`${p.fg} on ${p.bg} (${p.role})`, p] as const))(
      `${theme}: %s`, (_, p) => {
        expect(ratio(theme, p)).toBeGreaterThanOrEqual(floor(p.role))
      })
  }

  it('writes the table when asked (npm run contrast)', () => {
    const out = process.env.CONTRAST_OUT
    if (!out) return
    const row = (p: Pair) => {
      const cells = (['light', 'dark'] as const).map((th) => {
        if (!applies(th, p)) return 'outlined'
        const r = ratio(th, p)
        return `${r.toFixed(2)}${r >= floor(p.role) ? '' : ' ✗'}`
      })
      return `| \`${p.fg}\` on \`${p.bg}\` | ${p.role} | ${floor(p.role)} | ${cells.join(' | ')} | ${p.what} |`
    }
    const head = '| Pair | Role | Floor | Light | Dark | Where |\n|---|---|---|---|---|---|'
    const never = (p: Pair) => {
      const cells = (['light', 'dark'] as const).map((th) => ratio(th, p).toFixed(2))
      return `| \`${p.fg}\` on \`${p.bg}\` | ${cells.join(' | ')} | ${p.what} |`
    }
    const doc = [
      '# Field notes: contrast',
      '',
      'Generated by `npm run contrast` from `frontend/src/styles/ds/themes.css`.',
      'Text needs 4.5:1 and marks and control edges 3:1 (WCAG 2.x AA, 1.4.3 and 1.4.11),',
      'on every surface each sits on, in both themes.',
      '',
      '## Pairs in use',
      '',
      head,
      ...PAIRS.map(row),
      '',
      '## Never paired',
      '',
      'These fail the floor and the stylesheets do not produce them.',
      '',
      '| Pair | Light | Dark | Rule |\n|---|---|---|---|',
      ...NEVER.map(never),
      '',
    ].join('\n')
    writeFileSync(resolve(process.cwd(), out), doc)
  })
})
