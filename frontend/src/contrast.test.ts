import { describe, expect, it } from 'vitest'
import { contrast, parseColor, tryParseColor } from './contrast'

describe('contrast.ts', () => {
  it('reads the three syntaxes tokens.css uses, and trims', () => {
    expect(tryParseColor(' #FBFAF7 ')).toEqual([251, 250, 247, 1])
    expect(tryParseColor('rgba(20, 19, 26, 0.6)')).toEqual([20, 19, 26, 0.6])
    const ok = tryParseColor('oklch(0.60 0.19 42)')
    expect(ok).not.toBeNull()
    expect(ok![3]).toBe(1)
  })

  it('gives null for anything else, where parseColor throws', () => {
    for (const css of ['color-mix(in oklab, red 50%, blue)', 'var(--bg)', 'red', '#fff', '']) {
      expect(tryParseColor(css), css).toBeNull()
      expect(() => parseColor(css), css).toThrow()
    }
  })

  it('test/contrast.ts re-exports the same functions', async () => {
    expect((await import('./test/contrast')).contrast).toBe(contrast)
  })
})
