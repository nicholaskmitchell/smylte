import { describe, expect, it } from 'vitest'
import {
  SESSION_CHOICES, SESSION_DEFAULT, SESSION_NEVER,
  isSessionTtl, nextSessionTtl, sessionLabel,
} from './session'

describe('session length choices', () => {
  it('offers exactly the values the server accepts', () => {
    // The server keeps the same allowlist and 422s anything else, so an option
    // here that it refuses would be a control that silently does nothing.
    expect(SESSION_CHOICES.map((c) => c.s)).toEqual([86400, 604800, 2592000, SESSION_NEVER])
  })

  it('calls "never" a long finite life, not an absent one', () => {
    // A JWT with no exp is immortal, and logout's revocation list retires
    // entries by their token's own expiry.
    expect(SESSION_NEVER).toBeGreaterThan(0)
    expect(Number.isFinite(SESSION_NEVER)).toBe(true)
  })

  it('accepts only the offered values', () => {
    expect(isSessionTtl(604800)).toBe(true)
    for (const bad of [1, 0, -604800, 3600, '604800', null, undefined, true, NaN]) {
      expect(isSessionTtl(bad)).toBe(false)
    }
  })

  it('falls back to the shipped default when nothing is stored', () => {
    expect(sessionLabel(null)).toBe(sessionLabel(SESSION_DEFAULT))
    expect(sessionLabel(undefined)).toBe('7 days')
    // …and for a value the server would refuse, rather than showing it back.
    expect(sessionLabel(99)).toBe('7 days')
  })

  it('labels each choice', () => {
    expect(sessionLabel(86400)).toBe('1 day')
    expect(sessionLabel(SESSION_NEVER)).toBe('Never')
  })

  it('cycles through every choice and wraps', () => {
    const seen: number[] = []
    let cur = SESSION_CHOICES[0].s as number
    for (let i = 0; i < SESSION_CHOICES.length; i++) { seen.push(cur); cur = nextSessionTtl(cur) }
    expect(seen).toEqual(SESSION_CHOICES.map((c) => c.s))
    expect(cur).toBe(SESSION_CHOICES[0].s)          // wrapped
  })

  it('starts cycling from the default when nothing is stored', () => {
    expect(nextSessionTtl(null)).toBe(2592000)      // 7 days → 30 days
    expect(nextSessionTtl(99)).toBe(2592000)        // an unusable stored value too
  })
})
