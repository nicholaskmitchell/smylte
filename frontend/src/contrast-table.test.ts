// The Field notes contrast table.
//
// Every pair of tokens that Field notes ever paints together is listed here
// with its role, and each is checked in light and dark against the WCAG floor
// for that role: 4.5:1 for text, 3:1 for marks and for the edge of a field
// (WCAG 1.4.11). The values are read from ds/themes.css, the design system's
// own file, so the table is about what ships rather than about a copy.
//
// A secondary control (a ghost button, a settings toggle, a pick) has no edge
// at rest under Field notes: it is a face, --ctl-face, the ink at 8% (6% at
// night) over its ground, and its 3:1 edge shows under the pointer. The owner
// chose that on 22 Nov over the 3:1 edge at rest these controls had; WCAG
// 1.4.11 asks for no boundary where the word identifies the control. So the
// face's own pairs are here instead: its word, --fg or --warn, at 4.5:1 on
// the face over each ground. The share is read from tokens.css.
//
// `npm run contrast` writes the same table to docs/contrast.md, for the merge
// request. Pairs that fail are not in the passing list: they are the "never
// paired" rows at the end, which say which combinations the stylesheets must
// not produce, and the browser contrast walk (backlog.sep03.browser.test.tsx)
// measures what the pages actually paint.
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { composite, contrast, parseColor } from './contrast'

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

// --ctl-face (tokens.css): `color-mix(in oklab, var(--fg) N%, transparent)`,
// which keeps the ink's own colour and lowers only its alpha, so the browser
// paints it as --fg at N% over the ground. 8% in the Field notes lever block,
// 6% in the dark block after it.
const tokensCss = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '')
function faceShare(sel: string): number {
  const re = new RegExp(`(^|\\n)${sel.replace(/[[\]().*+?^$|]/g, '\\$&')}\\s*\\{([^}]*)\\}`)
  const m = /--ctl-face\s*:\s*color-mix\(in oklab, var\(--fg\) ([\d.]+)%, transparent\)/.exec(re.exec(tokensCss)?.[2] ?? '')
  if (!m) throw new Error(`no --ctl-face in tokens.css's ${sel} block`)
  return +m[1] / 100
}
const FACE = {
  light: faceShare(':root[data-surface="app"]'),
  dark: faceShare(':root[data-surface="app"][data-theme="dark"]'),
}
const FACE_OVER = '--ctl-face over '

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
  { fg: '--rule-strong', role: 'mark', what: 'field edges, a control\'s edge under the pointer, quiet marks (--mark-quiet)' },
  { fg: '--pri-high', role: 'mark', what: 'priority mark, beside the task title' },
  { fg: '--pri-med', role: 'mark', what: 'priority mark, beside the task title' },
  { fg: '--pri-low', role: 'mark', what: 'priority mark, beside the task title' },
]

/** A secondary control's word on its face, over each ground. */
const ON_FACE: Omit<Pair, 'bg'>[] = [
  { fg: '--fg', role: 'text', what: 'a secondary control\'s word on its face' },
  { fg: '--warn', role: 'text', what: 'a destructive control\'s word on its face' },
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
  { fg: '--fg-muted', bg: `${FACE_OVER}--paper`, role: 'text', what: 'a face carries --fg or --warn words only' },
]

const floor = (role: Pair['role']) => (role === 'text' ? 4.5 : 3)
/** A ground, or a control's face over one: --fg at the face's share,
 *  composited over the ground as the browser paints it. */
const ground = (theme: keyof typeof THEMES, bg: string): string => {
  const t = THEMES[theme]
  if (!bg.startsWith(FACE_OVER)) return t[bg]
  const ink = parseColor(t['--fg'])
  const under = parseColor(t[bg.slice(FACE_OVER.length)])
  const [r, g, b] = composite([ink[0], ink[1], ink[2], FACE[theme]], [under[0], under[1], under[2]])
  return `rgb(${r}, ${g}, ${b})`
}
const ratio = (theme: keyof typeof THEMES, p: Pair) => {
  const t = THEMES[theme]
  return contrast(t[p.fg], ground(theme, p.bg))
}

const PAIRS: Pair[] = [
  ...ON_SURFACES.flatMap((p) => SURFACES.map((bg) => ({ ...p, bg }))),
  ...ON_FACE.flatMap((p) => SURFACES.map((bg) => ({ ...p, bg: `${FACE_OVER}${bg}` }))),
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

  it('reads the control face\'s share from tokens.css', () => {
    expect(FACE.light).toBeGreaterThan(0)
    expect(FACE.dark).toBeGreaterThan(0)
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
      'Text needs 4.5:1, and marks and the edges of fields 3:1 (WCAG 2.x AA, 1.4.3 and 1.4.11),',
      'on every surface each sits on, in both themes.',
      '',
      'A secondary control (a ghost button, a settings toggle, a pick) has no edge at rest:',
      'it is a face, `--ctl-face`, the ink at ' + `${FACE.light * 100}% (${FACE.dark * 100}% at night)` + ' over its ground,',
      'and its 3:1 edge (`--rule-strong`) shows under the pointer. The owner chose this on 22 Nov;',
      'WCAG 1.4.11 asks for no boundary where the word identifies the control. The face\'s',
      'words are the `--ctl-face over …` rows.',
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
