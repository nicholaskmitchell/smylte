// The sanitizers, which are the part that has to survive a hand-edited or
// out-of-date settings blob.
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_EVENT_LEAD_MINUTES, DEFAULT_OFF, DEFAULT_ON, MAX_EVENT_LEAD_MINUTES,
  MIN_EVENT_LEAD_MINUTES, TRIGGERS, TRIGGER_DEFAULTS, TRIGGER_HINTS,
  TRIGGER_IS_EVENING, TRIGGER_IS_LOUD, TRIGGER_LABELS, isDigestTime, isTrigger,
  sanitizeEventLead, sanitizeTriggers, triggerEnabled,
} from './notifications'

describe('the trigger vocabulary', () => {
  it('labels, hints, volumes and defaults cover exactly the same rules', () => {
    // Four maps keyed by the same union is four chances to add a rule to three
    // of them. TypeScript catches a missing key; this catches a stray one.
    for (const map of [TRIGGER_LABELS, TRIGGER_HINTS, TRIGGER_IS_LOUD,
                       TRIGGER_DEFAULTS, TRIGGER_IS_EVENING]) {
      expect(Object.keys(map).sort()).toEqual([...TRIGGERS].sort())
    }
  })

  it('puts the rules that buzz first WITHIN each tier', () => {
    // Whether a notification interrupts you is the thing worth knowing before
    // you read what it is about. Across the whole list it no longer holds —
    // the two tiers are rendered as separate blocks — so the ordering claim is
    // per tier, which is what the reader actually sees.
    for (const tier of [DEFAULT_ON, DEFAULT_OFF]) {
      const loud = tier.map((t) => TRIGGER_IS_LOUD[t])
      expect(loud, tier.join(',')).toEqual([...loud].sort((a, b) => Number(b) - Number(a)))
    }
  })

  it('ships exactly the five that clear the bar, and nothing else', () => {
    expect(DEFAULT_ON).toEqual([
      'daily_digest', 'event_starting', 'item_reminder',
      'booking_created', 'sync_stalled',
    ])
    // Everything else is available and off — the app has a position, and the
    // position is not a lock.
    expect(DEFAULT_OFF.length).toBeGreaterThan(0)
    expect([...DEFAULT_ON, ...DEFAULT_OFF].sort()).toEqual([...TRIGGERS].sort())
  })

  it('never lets a rule the outside world drives buzz', () => {
    // The property that makes a quiet-hours setting unnecessary. A rule may
    // buzz only if its timing is the owner's — an hour they set, or a moment in
    // their own calendar or task list.
    const OWNER_TIMED = new Set([
      'daily_digest', 'task_overdue', 'day_unplanned', 'capacity_overcommitted',
      'day_not_shut_down', 'habits_outstanding',
      'event_starting', 'item_reminder', 'task_due_soon',
    ])
    for (const t of TRIGGERS) {
      if (TRIGGER_IS_LOUD[t]) expect(OWNER_TIMED.has(t), t).toBe(true)
    }
  })

  it('agrees with the backend about which rules fire in the evening', () => {
    // Only these two, and both are opt-in — so the evening hour is a setting
    // that means nothing until one of them is switched on.
    const evening = TRIGGERS.filter((t) => TRIGGER_IS_EVENING[t])
    expect(evening).toEqual(['day_not_shut_down', 'habits_outstanding'])
    for (const t of evening) expect(TRIGGER_DEFAULTS[t]).toBe(false)
  })

  it('recognises only rules this build has', () => {
    expect(isTrigger('daily_digest')).toBe(true)
    expect(isTrigger('from_the_future')).toBe(false)
    expect(isTrigger(null)).toBe(false)
    expect(isTrigger(7)).toBe(false)
  })
})

describe('sanitizeTriggers', () => {
  it('keeps known rules carrying a real boolean', () => {
    expect(sanitizeTriggers({ daily_digest: false, sync_stalled: true }))
      .toEqual({ daily_digest: false, sync_stalled: true })
  })

  it('drops a rule this build does not know', () => {
    // Rendering it would be a row nothing can turn off.
    expect(sanitizeTriggers({ daily_digest: false, from_the_future: true }))
      .toEqual({ daily_digest: false })
  })

  it('drops a value that is not a boolean', () => {
    expect(sanitizeTriggers({ daily_digest: 'yes', sync_stalled: 1 })).toEqual({})
  })

  it('survives a blob holding anything at all', () => {
    for (const junk of [null, undefined, 'broken', 42, [], [1, 2]]) {
      expect(sanitizeTriggers(junk)).toEqual({})
    }
  })
})

describe('triggerEnabled', () => {
  it('falls back to the rule\'s own default when absent', () => {
    // Sparse on purpose: a rule added later is then governed by its own
    // declaration, not by whatever the blob happened to contain before it
    // existed.
    expect(triggerEnabled({}, 'daily_digest')).toBe(true)
    expect(triggerEnabled({ sync_stalled: false }, 'daily_digest')).toBe(true)
  })

  it('honours an explicit override in both directions', () => {
    expect(triggerEnabled({ daily_digest: false }, 'daily_digest')).toBe(false)
    expect(triggerEnabled({ daily_digest: true }, 'daily_digest')).toBe(true)
  })
})

describe('isDigestTime', () => {
  it('accepts HH:MM on a 24-hour clock', () => {
    for (const ok of ['00:00', '07:30', '23:59', '09:05']) {
      expect(isDigestTime(ok), ok).toBe(true)
    }
  })

  it('refuses anything the server would 422', () => {
    // The server REJECTS a malformed digest time rather than filtering it, so
    // one of these reaching a PUT takes the whole settings write with it.
    for (const bad of ['7:30', '24:00', '23:60', '07:5', 'noon', '', '07:30:00', null, 730]) {
      expect(isDigestTime(bad), String(bad)).toBe(false)
    }
  })
})

describe('sanitizeEventLead', () => {
  it('clamps to the range the pipeline can actually deliver', () => {
    expect(sanitizeEventLead(1)).toBe(MIN_EVENT_LEAD_MINUTES)
    expect(sanitizeEventLead(9999)).toBe(MAX_EVENT_LEAD_MINUTES)
    expect(sanitizeEventLead(20)).toBe(20)
  })

  it('rounds and falls back rather than storing something unusable', () => {
    expect(sanitizeEventLead(12.6)).toBe(13)
    for (const junk of [NaN, Infinity, '10', null, undefined]) {
      expect(sanitizeEventLead(junk)).toBe(DEFAULT_EVENT_LEAD_MINUTES)
    }
  })
})
