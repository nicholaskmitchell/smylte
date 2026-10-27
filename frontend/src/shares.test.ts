// What the owner is told about a link: whether it is on, and whether anybody has
// it open. The Settings section and the Home module both read these.
import { describe, expect, it } from 'vitest'
import type { Share } from './api'
import { isOn, openNow, seenText } from './shares'
import { translate } from './i18n/index'
import { fmtWhen } from './time'

const share = (over: Partial<Share> = {}): Share => ({
  id: 'a'.repeat(32), name: 'Mum', token: 'tok-mum', url: null,
  lists: [], calendars: [], show_focus: false, horizon_days: 7,
  enabled: true, switched_off_by_password: false, last_seen_at: null,
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
  ...over,
})

const NOW = Date.parse('2026-10-05T12:00:00Z')
const secondsAgo = (n: number) => new Date(NOW - n * 1000).toISOString()
const tr = (k: string, v?: Record<string, string | number>) => translate('en', k, v)

describe('isOn', () => {
  it('is on for an enabled link', () => {
    expect(isOn(share())).toBe(true)
  })

  it('is off for a link switched off', () => {
    expect(isOn(share({ enabled: false }))).toBe(false)
  })

  it('is off for a link a password change switched off, even if the flag still says enabled', () => {
    expect(isOn(share({ enabled: true, switched_off_by_password: true }))).toBe(false)
  })
})

describe('openNow', () => {
  it('is open 119 seconds after the last view', () => {
    expect(openNow(share({ last_seen_at: secondsAgo(119) }), NOW)).toBe(true)
  })

  it('is not open 121 seconds after it', () => {
    expect(openNow(share({ last_seen_at: secondsAgo(121) }), NOW)).toBe(false)
  })

  it('is not open for a link that was never opened', () => {
    expect(openNow(share({ last_seen_at: null }), NOW)).toBe(false)
  })
})

describe('seenText', () => {
  it('says Open now while it is open', () => {
    expect(seenText(share({ last_seen_at: secondsAgo(30) }), NOW, tr, '24h', 'en'))
      .toBe('Open now')
  })

  it('says when it was last opened once the window has passed', () => {
    const seen = secondsAgo(600)
    expect(seenText(share({ last_seen_at: seen }), NOW, tr, '24h', 'en'))
      .toBe(`Last opened ${fmtWhen(seen, '24h', 'en')}`)
  })

  it('says it has not been opened when it has not', () => {
    expect(seenText(share(), NOW, tr, '24h', 'en')).toBe('Not opened yet')
  })
})
