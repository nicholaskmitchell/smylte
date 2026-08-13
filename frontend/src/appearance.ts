// Appearance customization — the override layer that sits on top of the shipped
// design system.
//
// The rule this whole module exists to protect: `styles/tokens.css` is the
// product's design, and it is never edited by customization. Instead every
// override is written as an inline custom property on <html>, which outranks
// the `:root` rules without replacing them. That makes "Reset to Smylte" a
// removeProperty() loop rather than a rebuild, and it means a corrupt or
// hostile stored blob degrades to the default look instead of a broken one.
//
// Shipped *presets* (see PRESETS) are the one thing that does not work this
// way. They are alternative designs rather than customizations, so they live in
// tokens.css under `:root[data-preset=…]` and are selected by an attribute on
// <html>. That keeps them as un-editable as the default, and keeps a preset out
// of the user's stored settings entirely — a palette fix ships with the next
// deploy instead of being frozen into whatever they saved.
//
// Everything here is pure except applyTokens/syncThemeColor/ensureFont, which
// are the only three functions that touch the DOM.

export type Mode = 'light' | 'dark'

export type TokenKind = 'color' | 'length' | 'scale' | 'font' | 'keyword'

export interface TokenSpec {
  label: string
  group: string
  kind: TokenKind
  /** Inclusive bounds for `length` (px) and `scale` (multiplier) tokens. */
  min?: number
  max?: number
  /** The complete set of legal values for a `keyword` token. */
  values?: string[]
  /** How to name those values in the editor, where the CSS keyword is opaque. */
  valueLabels?: Record<string, string>
  /** One-line explanation shown under the control in the editor. */
  hint?: string
}

/** A sparse map of token name → CSS value. Only what the user actually changed. */
export type ThemeTokens = Record<string, string>

export interface CustomTheme {
  id: string
  name: string
  /** Which shipped theme this was seeded from — display metadata only. */
  base: Mode
  light: ThemeTokens
  dark: ThemeTokens
}

export interface Appearance {
  /** Active custom theme id. Null/absent means the shipped default. */
  active?: string | null
  themes?: CustomTheme[]
}

// ── the allowlist ───────────────────────────────────────────────────────────
// Nothing outside this map is ever applied, stored, exported or imported. It is
// the single source of truth for what "customizable" means, and the backend
// mirrors it (see SettingsPatch in backend/tasksd/app.py).

export const TOKENS: Record<string, TokenSpec> = {
  '--bg': { label: 'Background', group: 'Surfaces', kind: 'color' },
  '--bg-elev': { label: 'Raised', group: 'Surfaces', kind: 'color',
    hint: 'Cards, modals, hover states.' },
  '--paper': { label: 'Sunken', group: 'Surfaces', kind: 'color',
    hint: 'The sidebar and column headers.' },

  '--fg': { label: 'Text', group: 'Text', kind: 'color' },
  '--fg-muted': { label: 'Muted', group: 'Text', kind: 'color' },
  '--fg-faint': { label: 'Faint', group: 'Text', kind: 'color' },

  '--rule': { label: 'Rule', group: 'Rules', kind: 'color',
    hint: 'Borders and dividers.' },
  '--rule-faint': { label: 'Rule, faint', group: 'Rules', kind: 'color' },

  '--accent': { label: 'Accent', group: 'Accents', kind: 'color' },
  '--warn': { label: 'Warning', group: 'Accents', kind: 'color',
    hint: 'Overdue dates, destructive actions.' },
  '--ok': { label: 'Success', group: 'Accents', kind: 'color',
    hint: 'All-day events, enabled booking links.' },

  '--pri-high': { label: 'High', group: 'Priority', kind: 'color' },
  '--pri-med': { label: 'Medium', group: 'Priority', kind: 'color' },
  '--pri-low': { label: 'Low', group: 'Priority', kind: 'color' },

  '--serif': { label: 'Reading', group: 'Type', kind: 'font',
    hint: 'Titles and headings.' },
  '--sans': { label: 'Interface', group: 'Type', kind: 'font',
    hint: 'Body text and controls.' },
  '--mono': { label: 'Mono', group: 'Type', kind: 'font',
    hint: 'Labels, dates, counts.' },

  '--radius': { label: 'Corners', group: 'Shape', kind: 'length', min: 0, max: 24 },
  '--fs-scale': { label: 'Text size', group: 'Shape', kind: 'scale', min: 0.8, max: 1.4 },
  '--label-case': { label: 'Labels', group: 'Shape', kind: 'keyword',
    values: ['uppercase', 'none'],
    valueLabels: { uppercase: 'Uppercase', none: 'Sentence case' },
    hint: 'Buttons, micro-labels and column heads.' },
  '--tracking': { label: 'Label tracking', group: 'Shape', kind: 'scale', min: 0, max: 1.5,
    hint: 'Letter-spacing on those same labels. 0 closes it up.' },
  '--gutter': { label: 'Gutter', group: 'Density', kind: 'length', min: 8, max: 64,
    hint: 'Horizontal breathing room around content.' },
  '--row-y': { label: 'Row height', group: 'Density', kind: 'length', min: 2, max: 24,
    hint: 'Vertical padding inside a task row.' },
}

export const TOKEN_NAMES = Object.keys(TOKENS)

/** Editor section order. Tokens render grouped under these headings. */
export const GROUPS = ['Surfaces', 'Text', 'Rules', 'Accents', 'Priority', 'Shape', 'Density', 'Type']

// ── the shipped defaults ────────────────────────────────────────────────────
// A mirror of styles/tokens.css. Duplicated deliberately: the editor needs to
// show what a token *is* before the user overrides it, and reading it back out
// of getComputedStyle would return the override once one is set. appearance.test.ts
// parses tokens.css and asserts these stay identical, so the copy cannot drift.

export const DEFAULTS: Record<Mode, ThemeTokens> = {
  light: {
    '--bg': '#FBFAF7',
    '--bg-elev': '#FFFFFF',
    '--paper': '#F2F0EA',
    '--fg': '#14131A',
    '--fg-muted': 'rgba(20, 19, 26, 0.60)',
    '--fg-faint': 'rgba(20, 19, 26, 0.36)',
    '--rule': 'rgba(20, 19, 26, 0.13)',
    '--rule-faint': 'rgba(20, 19, 26, 0.07)',
    '--accent': 'oklch(0.60 0.19 42)',
    '--warn': 'oklch(0.58 0.20 27)',
    '--ok': 'oklch(0.58 0.13 150)',
    '--pri-high': 'oklch(0.60 0.19 25)',
    '--pri-med': 'oklch(0.68 0.15 70)',
    '--pri-low': 'oklch(0.60 0.10 240)',
  },
  dark: {
    '--bg': '#0C0C10',
    '--bg-elev': '#16161C',
    '--paper': '#1A1A22',
    '--fg': '#ECEAF2',
    '--fg-muted': 'rgba(236, 234, 242, 0.60)',
    '--fg-faint': 'rgba(236, 234, 242, 0.34)',
    '--rule': 'rgba(236, 234, 242, 0.14)',
    '--rule-faint': 'rgba(236, 234, 242, 0.07)',
    '--accent': 'oklch(0.72 0.16 45)',
    '--warn': 'oklch(0.70 0.18 28)',
    '--ok': 'oklch(0.70 0.14 155)',
    '--pri-high': 'oklch(0.70 0.18 30)',
    '--pri-med': 'oklch(0.80 0.14 75)',
    '--pri-low': 'oklch(0.72 0.11 245)',
  },
}

/** Shipped values for the tokens that are shared across both modes. */
export const SHARED_DEFAULTS: ThemeTokens = {
  '--serif': '"Fraunces", Georgia, "Times New Roman", serif',
  '--sans': '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  '--mono': '"JetBrains Mono", ui-monospace, Menlo, monospace',
  '--radius': '0px',
  '--fs-scale': '1',
  '--gutter': '26px',
  '--row-y': '9px',
  '--label-case': 'uppercase',
  '--tracking': '1',
}

/** The effective shipped value of `token` in `mode`, whatever kind it is. */
export function defaultValue(token: string, mode: Mode): string {
  return DEFAULTS[mode][token] ?? SHARED_DEFAULTS[token] ?? ''
}

// ── shipped presets ─────────────────────────────────────────────────────────
// Alternative designs, not customizations. The values below are a mirror of the
// `:root[data-preset=…]` blocks in tokens.css — which is what the browser
// actually applies — and exist here because the editor must show what a token
// *is* under a preset, and forking one has to seed from it. appearance.test.ts
// parses tokens.css and fails the build if the two copies drift.
//
// Ids live in their own namespace so `active` stays a single string across all
// three cases (null, a preset, a saved theme) and a stored theme can never
// shadow one. No preset value may contain a single quote: the drift test that
// pins index.html's copy of the slugs matches on quoted pairs.

export const PRESET_PREFIX = 'preset:'

// Byte-identical to FONT_CHOICES.sans' "System sans", and offered in the serif
// and mono tiers too — a preset that puts one family in every slot has to land
// on a named option in each, not on "Custom (…)".
const SYSTEM_SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'

/** Both maps are dense — a preset restates the whole design, unlike a theme. */
export const PRESETS: readonly CustomTheme[] = [
  {
    id: 'preset:workspace',
    name: 'Workspace',
    base: 'light',
    light: {
      '--bg': '#FBFBFC',
      '--bg-elev': '#FFFFFF',
      '--paper': '#F5F5F7',
      '--fg': '#1D1D1F',
      '--fg-muted': 'rgba(29, 29, 31, 0.62)',
      '--fg-faint': 'rgba(29, 29, 31, 0.38)',
      '--rule': 'rgba(29, 29, 31, 0.11)',
      '--rule-faint': 'rgba(29, 29, 31, 0.06)',
      '--accent': 'oklch(0.56 0.16 253)',
      '--warn': 'oklch(0.55 0.19 27)',
      '--ok': 'oklch(0.56 0.12 155)',
      '--pri-high': 'oklch(0.56 0.18 25)',
      '--pri-med': 'oklch(0.66 0.12 72)',
      '--pri-low': 'oklch(0.58 0.08 250)',
      '--serif': SYSTEM_SANS,
      '--sans': SYSTEM_SANS,
      '--mono': SYSTEM_SANS,
      '--radius': '6px',
      '--fs-scale': '1',
      '--gutter': '24px',
      '--row-y': '11px',
      '--label-case': 'none',
      '--tracking': '0',
    },
    dark: {
      '--bg': '#191919',
      '--bg-elev': '#232323',
      '--paper': '#202020',
      '--fg': '#F5F5F5',
      '--fg-muted': 'rgba(245, 245, 245, 0.60)',
      '--fg-faint': 'rgba(245, 245, 245, 0.36)',
      '--rule': 'rgba(245, 245, 245, 0.13)',
      '--rule-faint': 'rgba(245, 245, 245, 0.07)',
      '--accent': 'oklch(0.70 0.14 253)',
      '--warn': 'oklch(0.68 0.17 28)',
      '--ok': 'oklch(0.70 0.12 158)',
      '--pri-high': 'oklch(0.66 0.18 22)',
      '--pri-med': 'oklch(0.78 0.12 78)',
      '--pri-low': 'oklch(0.70 0.09 252)',
      '--serif': SYSTEM_SANS,
      '--sans': SYSTEM_SANS,
      '--mono': SYSTEM_SANS,
      '--radius': '6px',
      '--fs-scale': '1',
      '--gutter': '24px',
      '--row-y': '11px',
      '--label-case': 'none',
      '--tracking': '0',
    },
  },
]

/** The shipped preset `id` names, or null. */
export function findPreset(id: string | null | undefined): CustomTheme | null {
  if (typeof id !== 'string' || !id) return null
  return PRESETS.find((p) => p.id === id) ?? null
}

/**
 * The `<html data-preset>` value for `id` — `preset:workspace` → `workspace` —
 * or null for the shipped default and for saved themes, which are applied as
 * inline properties instead.
 */
export function presetSlug(id: string | null | undefined): string | null {
  const preset = findPreset(id)
  return preset ? preset.id.slice(PRESET_PREFIX.length) : null
}

// ── validation ──────────────────────────────────────────────────────────────
// This is a security boundary, not just input tidying. Values reach the CSSOM
// from two untrusted-ish places: localStorage (read by the pre-paint script in
// index.html, before any of our code runs) and an imported theme file. The
// charset ban below is what stops a stored value from carrying a `url(...)`
// beacon or breaking out of the property it was written into.

export const MAX_VALUE_LEN = 120
export const MAX_THEMES = 24
export const MAX_NAME_LEN = 120

const FORBIDDEN = /url\(|image\(|expression\(|javascript:|@import|[;{}<>\\]|\/\*/i

/** Functions a color value may legally use. */
const COLOR_FNS = new Set([
  'rgb', 'rgba', 'hsl', 'hsla', 'hwb', 'lab', 'lch', 'oklab', 'oklch',
  'color-mix', 'color', 'var', 'calc',
])

function isColor(v: string): boolean {
  if (/^#[0-9a-f]{3,8}$/i.test(v)) return true
  // A bare keyword: `transparent`, `currentColor`, a named CSS color.
  if (/^[a-z]{3,20}$/i.test(v)) return true
  const fns = [...v.matchAll(/([a-z-]+)\s*\(/gi)].map((m) => m[1].toLowerCase())
  if (!fns.length) return false
  if (!fns.every((f) => COLOR_FNS.has(f))) return false
  // Balanced parens — an unbalanced value would leak into whatever follows it
  // when the pre-paint script writes it out.
  let depth = 0
  for (const ch of v) {
    if (ch === '(') depth++
    else if (ch === ')' && --depth < 0) return false
  }
  return depth === 0
}

/** A font-family list: quoted or bare family names, commas, generic keywords. */
function isFontStack(v: string): boolean {
  return /^[\w\s"'\-,.]+$/.test(v) && /[a-z]/i.test(v)
}

export function isValidValue(kind: TokenKind, raw: string): boolean {
  const v = raw.trim()
  if (!v || v.length > MAX_VALUE_LEN) return false
  if (FORBIDDEN.test(v)) return false
  switch (kind) {
    case 'color': return isColor(v)
    case 'font': return isFontStack(v)
    case 'length': return /^\d{1,3}(\.\d+)?px$/.test(v)
    case 'scale': return /^\d(\.\d+)?$/.test(v)
    // A keyword is only ever legal against its own token's `values`, which this
    // signature cannot see — isValidToken does that check. Refusing here means
    // the kind can never be waved through by a caller that only knows the kind.
    case 'keyword': return false
    default: return false
  }
}

/** True when `value` is a legal, in-range override for `token`. */
export function isValidToken(token: string, value: unknown): boolean {
  const spec = TOKENS[token]
  if (!spec || typeof value !== 'string') return false
  if (spec.kind === 'keyword') return (spec.values ?? []).includes(value.trim())
  if (!isValidValue(spec.kind, value)) return false
  if (spec.min !== undefined || spec.max !== undefined) {
    const n = parseFloat(value)
    if (Number.isNaN(n)) return false
    if (spec.min !== undefined && n < spec.min) return false
    if (spec.max !== undefined && n > spec.max) return false
  }
  return true
}

/** Drop every entry that is not a valid override. Never throws. */
export function sanitizeTokens(raw: unknown): ThemeTokens {
  const out: ThemeTokens = {}
  if (!raw || typeof raw !== 'object') return out
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (isValidToken(k, v)) out[k] = (v as string).trim()
  }
  return out
}

/** Coerce arbitrary parsed JSON into a well-formed Appearance. Never throws. */
export function sanitizeAppearance(raw: unknown): Appearance {
  if (!raw || typeof raw !== 'object') return {}
  const src = raw as Record<string, unknown>
  const themes: CustomTheme[] = []
  if (Array.isArray(src.themes)) {
    for (const t of src.themes.slice(0, MAX_THEMES)) {
      if (!t || typeof t !== 'object') continue
      const o = t as Record<string, unknown>
      if (typeof o.id !== 'string' || !o.id) continue
      if (typeof o.name !== 'string' || !o.name) continue
      // The preset namespace is reserved. Without this, a hand-edited blob
      // could carry a saved theme called `preset:workspace` that the attribute
      // path silently shadows. clientId() never emits a colon, so nothing the
      // app itself created is ever dropped here.
      if (o.id.startsWith(PRESET_PREFIX)) continue
      themes.push({
        id: o.id.slice(0, 64),
        name: o.name.slice(0, MAX_NAME_LEN),
        base: o.base === 'dark' ? 'dark' : 'light',
        light: sanitizeTokens(o.light),
        dark: sanitizeTokens(o.dark),
      })
    }
  }
  // An `active` pointing at a theme that no longer exists — or at a preset this
  // build has dropped — falls back to the shipped default rather than rendering
  // nothing.
  const active = typeof src.active === 'string'
    && (!!findPreset(src.active) || themes.some((t) => t.id === src.active))
    ? src.active
    : null
  return { active, themes }
}

// ── resolution + application ────────────────────────────────────────────────

/**
 * The flat override map for the active theme in `mode`. Empty = nothing to
 * override with, which covers both the shipped default and a preset — a preset
 * is carried by `<html data-preset>` (see presetSlug), so the inline layer must
 * be cleared for it rather than written to.
 */
export function resolve(appearance: Appearance | null | undefined, mode: Mode): ThemeTokens {
  if (!appearance?.active) return {}
  const theme = appearance.themes?.find((t) => t.id === appearance.active)
  if (!theme) return {}
  return sanitizeTokens(mode === 'dark' ? theme.dark : theme.light)
}

/**
 * Write `tokens` onto `el` as inline custom properties, clearing any previously
 * applied override first. Passing `{}` restores the shipped theme exactly.
 */
export function applyTokens(el: HTMLElement, tokens: ThemeTokens): void {
  for (const name of TOKEN_NAMES) el.style.removeProperty(name)
  for (const [name, value] of Object.entries(sanitizeTokens(tokens))) {
    el.style.setProperty(name, value)
  }
}

const hexCache = new Map<string, string>()

/**
 * Flatten any CSS color to `#rrggbb`, for the native color input (which speaks
 * sRGB hex and nothing else).
 *
 * Done by painting one pixel rather than reading a computed style: browsers
 * keep `oklch()` and `color-mix()` in their authored form all the way through
 * getComputedStyle, so there is no conversion to read back. A canvas is the one
 * place the value actually gets rasterized. Returns a neutral grey where there
 * is no 2D context (jsdom) or the value is one canvas cannot parse — the raw
 * text field beside the swatch is always the authoritative control.
 */
export function toSwatchHex(value: string): string {
  const cached = hexCache.get(value)
  if (cached) return cached
  let hex = '#888888'
  try {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.fillStyle = '#888888'
      ctx.fillStyle = value               // ignored outright if unparseable
      ctx.fillRect(0, 0, 1, 1)
      const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
      hex = `#${[r, g, b].map((n) => n.toString(16).padStart(2, '0')).join('')}`
    }
  } catch { /* no canvas support — keep the neutral grey */ }
  hexCache.set(value, hex)
  return hex
}

/**
 * Point the `theme-color` meta at the current background so mobile browser
 * chrome matches — including under a custom theme, which is why this reads the
 * resolved value instead of hardcoding the two shipped hexes.
 */
export function syncThemeColor(): void {
  const meta = document.querySelector('meta[name="theme-color"]')
  if (!meta) return
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
  if (bg) meta.setAttribute('content', bg)
}

// ── persistence (the pre-paint cache) ───────────────────────────────────────
// The server is the source of truth; this mirror exists only so index.html can
// paint the right colors before the bundle loads. Same contract as `tasks-theme`.

export const APPEARANCE_KEY = 'tasks-appearance'

export function cacheAppearance(appearance: Appearance | null): void {
  try {
    if (!appearance?.active) localStorage.removeItem(APPEARANCE_KEY)
    else localStorage.setItem(APPEARANCE_KEY, JSON.stringify(appearance))
  } catch { /* private mode / quota — the server copy still wins on next load */ }
}

export function readCachedAppearance(): Appearance | null {
  try {
    const raw = localStorage.getItem(APPEARANCE_KEY)
    if (!raw) return null
    return sanitizeAppearance(JSON.parse(raw))
  } catch { return null }
}

// ── export / import ─────────────────────────────────────────────────────────

const EXPORT_VERSION = 1

export function serializeTheme(theme: CustomTheme): string {
  return JSON.stringify({
    smylte_theme: EXPORT_VERSION,
    name: theme.name,
    base: theme.base,
    light: theme.light,
    dark: theme.dark,
  }, null, 2)
}

/**
 * Parse an exported theme file. Returns null when the payload is not a theme;
 * anything malformed *inside* a valid theme is dropped rather than rejected, so
 * a file written against a newer token set still imports what it can.
 */
export function parseTheme(text: string, id: string): CustomTheme | null {
  let raw: unknown
  try { raw = JSON.parse(text) } catch { return null }
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  if (o.smylte_theme !== EXPORT_VERSION) return null
  const light = sanitizeTokens(o.light)
  const dark = sanitizeTokens(o.dark)
  if (!Object.keys(light).length && !Object.keys(dark).length) return null
  return {
    id,
    name: (typeof o.name === 'string' && o.name.trim() ? o.name : 'Imported theme')
      .slice(0, MAX_NAME_LEN),
    base: o.base === 'dark' ? 'dark' : 'light',
    light,
    dark,
  }
}

// ── fonts ───────────────────────────────────────────────────────────────────
// The three shipped families are loaded by index.html. Anything else is fetched
// on first use rather than up front, so choosing a font costs a request only for
// the person who chose it — the default install still loads exactly three.

export interface FontChoice {
  label: string
  stack: string
  /** Google Fonts `family=` spec. Absent for system stacks, which need no request. */
  google?: string
}

export const FONT_CHOICES: Record<'serif' | 'sans' | 'mono', FontChoice[]> = {
  serif: [
    { label: 'Fraunces (default)', stack: SHARED_DEFAULTS['--serif'] },
    { label: 'Georgia', stack: 'Georgia, "Times New Roman", serif' },
    { label: 'System serif', stack: 'ui-serif, Iowan Old Style, Palatino, serif' },
    // Also in the sans tier. A theme that wants one family in every slot — the
    // Workspace preset does — needs it offered here too, or forking it lands on
    // "Custom (…)" for a stack the app itself ships.
    { label: 'System sans', stack: SYSTEM_SANS },
    { label: 'Lora', stack: '"Lora", Georgia, serif', google: 'Lora:wght@400;500;600' },
    { label: 'EB Garamond', stack: '"EB Garamond", Georgia, serif', google: 'EB+Garamond:wght@400;500;600' },
    { label: 'Playfair Display', stack: '"Playfair Display", Georgia, serif', google: 'Playfair+Display:wght@400;500;600' },
    { label: 'Source Serif 4', stack: '"Source Serif 4", Georgia, serif', google: 'Source+Serif+4:wght@400;500;600' },
  ],
  sans: [
    { label: 'Inter (default)', stack: SHARED_DEFAULTS['--sans'] },
    { label: 'System sans', stack: SYSTEM_SANS },
    { label: 'IBM Plex Sans', stack: '"IBM Plex Sans", sans-serif', google: 'IBM+Plex+Sans:wght@400;500;600' },
    { label: 'Work Sans', stack: '"Work Sans", sans-serif', google: 'Work+Sans:wght@400;500;600' },
    { label: 'Public Sans', stack: '"Public Sans", sans-serif', google: 'Public+Sans:wght@400;500;600' },
    { label: 'Manrope', stack: '"Manrope", sans-serif', google: 'Manrope:wght@400;500;600' },
    { label: 'Atkinson Hyperlegible', stack: '"Atkinson Hyperlegible", sans-serif', google: 'Atkinson+Hyperlegible:wght@400;700' },
  ],
  mono: [
    { label: 'JetBrains Mono (default)', stack: SHARED_DEFAULTS['--mono'] },
    { label: 'System mono', stack: 'ui-monospace, Menlo, Consolas, monospace' },
    { label: 'System sans', stack: SYSTEM_SANS },
    { label: 'IBM Plex Mono', stack: '"IBM Plex Mono", monospace', google: 'IBM+Plex+Mono:wght@400;500' },
    { label: 'Source Code Pro', stack: '"Source Code Pro", monospace', google: 'Source+Code+Pro:wght@400;500' },
    { label: 'Space Mono', stack: '"Space Mono", monospace', google: 'Space+Mono:wght@400;700' },
    { label: 'Roboto Mono', stack: '"Roboto Mono", monospace', google: 'Roboto+Mono:wght@400;500' },
  ],
}

const loadedFonts = new Set<string>()

/** Inject the Google Fonts stylesheet for `stack`, once, if it needs one. */
export function ensureFont(stack: string): void {
  for (const choices of Object.values(FONT_CHOICES)) {
    const hit = choices.find((c) => c.stack === stack)
    if (!hit?.google || loadedFonts.has(hit.google)) continue
    loadedFonts.add(hit.google)
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = `https://fonts.googleapis.com/css2?family=${hit.google}&display=swap`
    document.head.appendChild(link)
  }
}

/** Load whatever families a resolved token map refers to. */
export function ensureFonts(tokens: ThemeTokens): void {
  for (const name of ['--serif', '--sans', '--mono']) {
    if (tokens[name]) ensureFont(tokens[name])
  }
}
