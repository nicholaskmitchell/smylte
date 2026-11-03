// The wallpaper accent (system-accent.ts), in real browser engines.
//
// What jsdom cannot say: that the engine converts a background in any syntax to
// something measurable (jsdom has no canvas), that the shipped designs' real
// backgrounds clear 3:1 against the tone picked for them, and that a control
// drawn in the accent really takes it in the real cascade. Chromium AND WebKit,
// against the real tokens.css.
import { afterEach, describe, expect, it } from 'vitest'
import { applySystemAccent, normaliseColor, pickAccent } from './system-accent'
import { RAMP } from './test/accent'

const root = document.documentElement
const added: Element[] = []

afterEach(() => {
  root.removeAttribute('style')
  delete root.dataset.theme
  delete root.dataset.preset
  for (const el of added.splice(0)) el.remove()
})

const computedAccent = () => getComputedStyle(root).getPropertyValue('--accent').trim()

describe('the wallpaper accent in a browser engine', () => {
  it('reads a background in any syntax the engine paints', () => {
    const mixed = normaliseColor('color-mix(in oklab, #000000 50%, #ffffff)')
    expect(mixed).toMatch(/^#[0-9a-f]{6}$/)
    for (let i = 1; i < 7; i += 2) {
      const channel = parseInt(mixed!.slice(i, i + 2), 16)
      expect(channel).toBeGreaterThanOrEqual(95)
      expect(channel).toBeLessThanOrEqual(103)
    }
    expect(normaliseColor('hsl(120 50% 50%)')).toBe('#40bf40')
    for (const bad of ['notacolour', 'rgba(255, 255, 255, 0.5)', 'transparent', '']) {
      expect(normaliseColor(bad), bad).toBeNull()
    }
  })

  const designs: [string, string | null][] = [['Smylte', null], ['Workspace', 'workspace'], ['Classic', 'classic']]
  const cases = designs.flatMap(([name, preset]) => (
    [['light', '#005ac1'], ['dark', '#adc6ff']] as const).map(([mode, tone]) => ({ name, preset, mode, tone })))

  it.each(cases)('takes $tone on $name in $mode', ({ preset, mode, tone }) => {
    if (preset) root.dataset.preset = preset
    root.dataset.theme = mode
    expect(applySystemAccent(root, mode, RAMP)).toBe(tone)
    expect(computedAccent()).toBe(tone)
  })

  it('a control drawn in the accent takes the tone', () => {
    root.dataset.theme = 'light'
    expect(applySystemAccent(root, 'light', RAMP)).toBe('#005ac1')
    // Appended after the accent is applied, so there is no transition to wait out.
    const btn = document.createElement('button')
    btn.className = 'icon-btn active'
    btn.textContent = 'x'
    document.body.appendChild(btn)
    added.push(btn)
    expect(getComputedStyle(btn).backgroundColor).toBe('rgb(0, 90, 193)')
  })

  it('reads a custom theme\'s color-mix() and var() backgrounds', () => {
    root.dataset.theme = 'light'
    root.style.setProperty('--bg', 'color-mix(in oklab, #FBFAF7 50%, #FFFFFF)')
    root.style.setProperty('--paper', 'var(--bg)')
    expect(applySystemAccent(root, 'light', RAMP)).toBe('#005ac1')
  })

  it('puts the accent back when the tone would change a background drawn from it', () => {
    // Anti-vacuity: on the backgrounds as they are, a darker tone is picked, so
    // the restore below is the check at work and not a pick that found nothing.
    expect(pickAccent(RAMP, 'light', ['oklch(0.60 0.19 42)', '#FFFFFF', '#F2F0EA'])).toBe('#002e69')
    root.dataset.theme = 'light'
    root.style.setProperty('--bg', 'var(--accent)')
    expect(applySystemAccent(root, 'light', RAMP)).toBeNull()
    expect(root.style.getPropertyValue('--accent')).toBe('')
  })

  it('paints nothing over a background drawn from currentColor', () => {
    // A canvas resolves currentColor to black, where a dark-mode tone clears
    // 3:1 easily; on the page the background takes each element's own text
    // colour, against which the same tone can fall below the floor.
    root.dataset.theme = 'dark'
    root.style.setProperty('--paper', 'color-mix(in srgb, currentColor 50%, black)')
    expect(applySystemAccent(root, 'dark', RAMP)).toBeNull()
    expect(root.style.getPropertyValue('--accent')).toBe('')
  })

  it('puts back an accent the theme had set inline, not just the stylesheet\'s', () => {
    // A custom theme's accent is inline on the root (applyTokens), and a
    // background drawn from it is the case the check after painting exists for.
    root.dataset.theme = 'light'
    root.style.setProperty('--accent', '#f59e0b')
    root.style.setProperty('--bg', 'var(--accent)')
    // Anti-vacuity: on those backgrounds a tone is picked, so the null below is
    // the check after painting at work.
    expect(pickAccent(RAMP, 'light', ['#f59e0b', '#FFFFFF', '#F2F0EA'])).not.toBeNull()
    expect(applySystemAccent(root, 'light', RAMP)).toBeNull()
    expect(root.style.getPropertyValue('--accent')).toBe('#f59e0b')
  })
})
