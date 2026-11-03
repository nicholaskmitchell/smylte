// The Android client's accent from the wallpaper: an opt-in on one phone that
// swaps the accent, and only the accent, for a tone of the phone's own palette
// (Material You) that stays readable on the theme's backgrounds.
//
// It is never part of a theme. The switch lives in this WebView's local
// storage, not the account, so the owner's other devices, the theme itself and
// its exports keep the theme's accent. When it is on, App writes the tone as an
// inline `--accent` after `applyTokens`, which clears every token first, so it
// is written again on every theme or mode change; main.tsx writes it once
// before the first render, so the tab strip does not open on the theme's
// accent.
//
// Outside the Android client, and on Android 11, there is no palette
// (`hostAccent()` is null) and nothing here writes anything.

import { ACCENT_TONES, hostAccent, isAccentRamp } from './android'
import { isValidToken, type Mode } from './appearance'
import { contrast, tryParseColor } from './contrast'

/** The non-text floor the shipped accents are held to (appearance.test.ts). */
export const MIN_ACCENT_CONTRAST = 3

/** The backgrounds an accent is drawn on or beside: the three the token tests
 *  measure the shipped accents against. */
export const ACCENT_SURFACES = ['--bg', '--bg-elev', '--paper'] as const

/** The tones tried, in order: Material's own accent tone for each mode first
 *  (600 on light, 200 on dark), then further from the background. White and
 *  black, and the middle tones, are never offered. */
const TRY: Record<Mode, readonly number[]> = {
  light: [600, 700, 800, 900],
  dark: [200, 100, 50, 10],
}

/** This phone's switch. Per device on purpose: it never goes to the account. */
export const DEVICE_ACCENT_KEY = 'smylte-device-accent'

/** The first tone that clears 3:1 against every surface, or null: a palette
 *  that is not one, a surface it cannot read (or not opaque, so what is behind
 *  it would decide), or no tone that clears it. Pure: surfaces in any other
 *  syntax are normalised by `applySystemAccent` first. */
export function pickAccent(
  ramp: readonly string[], mode: Mode, surfaces: readonly string[],
): string | null {
  if (!isAccentRamp(ramp) || surfaces.length === 0) return null
  for (const s of surfaces) {
    const c = tryParseColor(s)
    if (!c || c[3] < 1) return null
  }
  for (const tone of TRY[mode]) {
    const hex = ramp[ACCENT_TONES.indexOf(tone)]
    if (surfaces.every((s) => contrast(hex, s) >= MIN_ACCENT_CONTRAST)) return hex
  }
  return null
}

/** Any CSS colour the engine can paint, as an opaque `#rrggbb`, or null when it
 *  cannot be parsed, is not opaque, or there is no canvas (jsdom). A custom
 *  theme's background may be `color-mix()`, `hsl()`, `var()`-substituted text
 *  or a named colour, which `contrast.ts` cannot read. Painting one pixel is
 *  the one place the engine converts it, as ThemeColour.WATCH_SCRIPT does for
 *  the bar colour, including its check that the value parsed at all: an
 *  ignored value leaves the previous fill in place, so two different previous
 *  fills tell it apart. */
export function normaliseColor(css: string): string | null {
  const v = css.trim()
  if (!v) return null
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    ctx.fillStyle = '#000000'
    ctx.fillStyle = v
    const a = ctx.fillStyle
    ctx.fillStyle = '#ffffff'
    ctx.fillStyle = v
    if (ctx.fillStyle !== a) return null
    ctx.clearRect(0, 0, 1, 1)
    ctx.fillRect(0, 0, 1, 1)
    const [r, g, b, alpha] = ctx.getImageData(0, 0, 1, 1).data
    if (alpha !== 255) return null
    return '#' + [r, g, b].map((n) => n.toString(16).padStart(2, '0')).join('')
  } catch {
    return null
  }
}

/** A colour `contrast.ts` can measure: as it is when it reads it, else
 *  normalised by the engine. Never one that uses `currentColor`: that is each
 *  element's own text colour where it is painted, which a detached canvas
 *  resolves to black, so a background mixed from it would be measured as
 *  something it is not, and a tone could pass against it and fail on screen. */
function measurable(css: string): string | null {
  const v = css.trim()
  if (/currentcolor/i.test(v)) return null
  return tryParseColor(v) ? v : normaliseColor(v)
}

/** The three backgrounds as `el` computes them now, each in a form `contrast.ts`
 *  can measure, or null when any of them cannot be. */
function readSurfaces(el: HTMLElement): string[] | null {
  const style = getComputedStyle(el)
  const out: string[] = []
  for (const name of ACCENT_SURFACES) {
    const c = measurable(style.getPropertyValue(name))
    if (c === null) return null
    out.push(c)
  }
  return out
}

/** Paint the wallpaper tone as `--accent` on `el` (the document element), over
 *  whatever the theme put there. Returns the tone written, or null when nothing
 *  is written: no palette, a background that cannot be read, no tone that
 *  clears the floor, or a tone that no longer clears it once painted, in which
 *  case the accent `el` had is put back. Call it after `applyTokens`, which
 *  clears every token first. */
export function applySystemAccent(
  el: HTMLElement, mode: Mode, ramp: readonly string[] | null | undefined,
): string | null {
  if (!ramp) return null
  const before = readSurfaces(el)
  if (!before) return null
  const tone = pickAccent(ramp, mode, before)
  if (!tone || !isValidToken('--accent', tone)) return null
  const previous = el.style.getPropertyValue('--accent')
  el.style.setProperty('--accent', tone)
  // A custom background may itself be defined from the accent (a colour token
  // may alias another), and would have moved with it.
  const after = readSurfaces(el)
  if (after && after.every((s) => contrast(tone, s) >= MIN_ACCENT_CONTRAST)) return tone
  if (previous) el.style.setProperty('--accent', previous)
  else el.style.removeProperty('--accent')
  return null
}

/** Whether this phone has the switch on. Any storage failure reads as off. */
export function readDeviceAccent(): boolean {
  try {
    return localStorage.getItem(DEVICE_ACCENT_KEY) === '1'
  } catch {
    return false
  }
}

export function writeDeviceAccent(on: boolean): void {
  try {
    localStorage.setItem(DEVICE_ACCENT_KEY, on ? '1' : '0')
  } catch {
    // Private mode or quota: the switch holds for this session only.
  }
}

/** main.tsx, before the first render: paint the tone when this phone has the
 *  switch on, so the first frame has it. App paints it again after its own
 *  `applyTokens`. A no-op without a palette. */
export function startSystemAccent(): void {
  if (!readDeviceAccent()) return
  const root = document.documentElement
  applySystemAccent(root, root.dataset.theme === 'dark' ? 'dark' : 'light', hostAccent())
}
