import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEFAULTS } from './appearance'
import {
  DEVICE_ACCENT_KEY, applySystemAccent, pickAccent, readDeviceAccent, writeDeviceAccent,
} from './system-accent'
import { RAMP } from './test/accent'

afterEach(() => {
  document.documentElement.removeAttribute('style')
  localStorage.clear()
  vi.restoreAllMocks()
})

const surfaces = (mode: 'light' | 'dark') =>
  (['--bg', '--bg-elev', '--paper'] as const).map((k) => DEFAULTS[mode][k])

describe('pickAccent', () => {
  it('takes tone 600 on the shipped light backgrounds and 200 on the dark', () => {
    expect(pickAccent(RAMP, 'light', surfaces('light'))).toBe('#005ac1')
    expect(pickAccent(RAMP, 'dark', surfaces('dark'))).toBe('#adc6ff')
  })

  it('steps darker on a stricter light background, and lighter on a dark one', () => {
    expect(pickAccent(RAMP, 'light', ['#a0a0a0'])).toBe('#004494')
    expect(pickAccent(RAMP, 'dark', ['#767676'])).toBe('#d8e2ff')
  })

  it('needs every background to clear 3:1', () => {
    expect(pickAccent(RAMP, 'light', ['#FFFFFF', '#a0a0a0'])).toBe('#004494')
  })

  it('gives null when no tone clears it', () => {
    expect(pickAccent(RAMP, 'light', ['#5a5a5a'])).toBeNull()
    expect(pickAccent(RAMP, 'dark', ['#ffffff'])).toBeNull()
  })

  it('never offers white or black', () => {
    // Tone 600 clears 3:1 on black, so light mode still gets a tone, but never
    // the palette's own white or black; on white, dark mode's tones all fail.
    const onBlack = pickAccent(RAMP, 'light', ['#000000'])
    expect(onBlack).toBe('#005ac1')
    expect([RAMP[0], RAMP[12]]).not.toContain(onBlack)
    expect(pickAccent(RAMP, 'dark', ['#ffffff'])).toBeNull()
  })

  it('never offers white or black on any grey, in either mode', () => {
    // A sweep, because the greys where only white (or only black) would clear
    // 3:1 are a narrow band that no single surface above lands in.
    for (let v = 0; v <= 255; v++) {
      const grey = `#${v.toString(16).padStart(2, '0').repeat(3)}`
      for (const mode of ['light', 'dark'] as const) {
        expect([RAMP[0], RAMP[12]], `${mode} on ${grey}`).not.toContain(pickAccent(RAMP, mode, [grey]))
      }
    }
  })

  it.each([
    [[DEFAULTS.light['--bg'], 'color-mix(in oklab, red 50%, blue)']],
    [['var(--paper)']],
    [['']],
    [['rgba(255, 255, 255, 0.5)']],
    [[]],
  ])('gives null for a background it cannot read: %j', (bad) => {
    expect(pickAccent(RAMP, 'light', bad)).toBeNull()
  })

  it.each([
    ['too few tones', RAMP.slice(0, 12)],
    ['too many tones', [...RAMP, '#000000']],
    ['an uppercase colour', RAMP.map((c, i) => (i === 0 ? c.toUpperCase() : c))],
    ['a short colour', RAMP.map((c, i) => (i === 8 ? '#05ac1' : c))],
    ['a named colour', RAMP.map((c, i) => (i === 8 ? 'red' : c))],
  ])('gives null for a palette that is not one #rrggbb per tone: %s', (_name, ramp) => {
    expect(pickAccent(ramp, 'light', surfaces('light'))).toBeNull()
  })
})

describe('the switch', () => {
  it('is off until this phone turns it on, and is stored on this phone', () => {
    expect(readDeviceAccent()).toBe(false)
    writeDeviceAccent(true)
    expect(localStorage.getItem(DEVICE_ACCENT_KEY)).toBe('1')
    expect(readDeviceAccent()).toBe(true)
    writeDeviceAccent(false)
    expect(localStorage.getItem(DEVICE_ACCENT_KEY)).toBe('0')
    expect(readDeviceAccent()).toBe(false)
  })

  it('reads any other stored value as off', () => {
    for (const v of ['true', 'on']) {
      localStorage.setItem(DEVICE_ACCENT_KEY, v)
      expect(readDeviceAccent(), v).toBe(false)
    }
  })

  it('reads as off, and writes nothing, when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    expect(readDeviceAccent()).toBe(false)
    expect(() => writeDeviceAccent(true)).not.toThrow()
  })
})

describe('applySystemAccent', () => {
  const root = document.documentElement
  const inline = () => root.style.getPropertyValue('--accent')
  const paint = (bg: readonly string[] = surfaces('light')) => {
    root.style.setProperty('--bg', bg[0])
    root.style.setProperty('--bg-elev', bg[1] ?? bg[0])
    root.style.setProperty('--paper', bg[2] ?? bg[0])
    root.style.setProperty('--accent', '#aa3300')
  }

  it('writes the tone over the theme\'s accent', () => {
    paint()
    expect(applySystemAccent(root, 'light', RAMP)).toBe('#005ac1')
    expect(inline()).toBe('#005ac1')
  })

  it('writes nothing without a palette', () => {
    paint()
    expect(applySystemAccent(root, 'light', null)).toBeNull()
    expect(applySystemAccent(root, 'light', undefined)).toBeNull()
    expect(inline()).toBe('#aa3300')
  })

  it('writes nothing when a background cannot be read', () => {
    root.style.setProperty('--accent', '#aa3300')
    expect(applySystemAccent(root, 'light', RAMP)).toBeNull()
    expect(inline()).toBe('#aa3300')
  })

  it('writes nothing on a background no tone clears', () => {
    paint(['#5a5a5a', '#5a5a5a', '#5a5a5a'])
    expect(applySystemAccent(root, 'light', RAMP)).toBeNull()
    expect(inline()).toBe('#aa3300')
  })

  // Each of the three backgrounds must be measured: the others clear tone 600
  // here, so only the one strict background can move the pick.
  it.each([
    ['--bg', ['#a0a0a0', '#ffffff', '#ffffff']],
    ['--bg-elev', ['#ffffff', '#a0a0a0', '#ffffff']],
    ['--paper', ['#ffffff', '#ffffff', '#a0a0a0']],
  ])('steps darker when only %s is strict', (_name, bg) => {
    paint(bg)
    expect(applySystemAccent(root, 'light', RAMP)).toBe('#004494')
    expect(inline()).toBe('#004494')
  })

  it.each([
    ['--bg', ['#5a5a5a', '#ffffff', '#ffffff']],
    ['--bg-elev', ['#ffffff', '#5a5a5a', '#ffffff']],
    ['--paper', ['#ffffff', '#ffffff', '#5a5a5a']],
  ])('writes nothing when only %s has no tone that clears it', (_name, bg) => {
    paint(bg)
    expect(applySystemAccent(root, 'light', RAMP)).toBeNull()
    expect(inline()).toBe('#aa3300')
  })
})
