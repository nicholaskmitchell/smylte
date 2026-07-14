import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthError } from './api'
import {
  addDays, dayKey, fmtDue, isOverdue, makeGuard, pad, parseDate,
  setErrorNotifier, toLocalInput, ymd,
} from './util'

describe('parseDate', () => {
  it('parses date-only strings as LOCAL midnight, not UTC', () => {
    const d = parseDate('2026-07-11')
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 6, 11])
    expect(d.getHours()).toBe(0)
  })

  it('parses datetimes through Date', () => {
    const d = parseDate('2026-07-11T14:30:00')
    expect(d.getHours()).toBe(14)
    expect(d.getMinutes()).toBe(30)
  })
})

describe('day/formatting helpers', () => {
  it('dayKey maps date and datetime to the local calendar day', () => {
    expect(dayKey('2026-07-11')).toBe('2026-07-11')
    expect(dayKey('2026-07-11T23:59:00')).toBe('2026-07-11')
  })

  it('toLocalInput produces a datetime-local value', () => {
    expect(toLocalInput('2026-07-11T09:05:00')).toBe('2026-07-11T09:05')
  })

  it('fmtDue is empty for null and echoes garbage instead of NaN', () => {
    expect(fmtDue(null, false)).toBe('')
    expect(fmtDue('not-a-date', false)).toBe('not-a-date')
  })

  it('ymd/pad/addDays roll over month boundaries', () => {
    expect(pad(3)).toBe('03')
    expect(ymd(addDays(new Date(2026, 0, 31), 1))).toBe('2026-02-01')
    expect(ymd(addDays(new Date(2026, 2, 1), -1))).toBe('2026-02-28')
  })
})

describe('isOverdue', () => {
  it('treats an all-day item as due until its whole day has passed', () => {
    expect(isOverdue(ymd(new Date()), true)).toBe(false)   // today: not yet
    expect(isOverdue(ymd(addDays(new Date(), -1)), true)).toBe(true)
    expect(isOverdue(ymd(addDays(new Date(), 1)), true)).toBe(false)
  })

  it('compares timed items against now', () => {
    const past = new Date(Date.now() - 3600_000)
    const future = new Date(Date.now() + 3600_000)
    expect(isOverdue(`${ymd(past)}T${pad(past.getHours())}:${pad(past.getMinutes())}:00`)).toBe(true)
    expect(isOverdue(`${ymd(future)}T${pad(future.getHours())}:${pad(future.getMinutes())}:00`)).toBe(false)
  })

  it('is false for null/garbage', () => {
    expect(isOverdue(null)).toBe(false)
    expect(isOverdue('garbage')).toBe(false)
  })
})

describe('makeGuard', () => {
  afterEach(() => setErrorNotifier(null))

  it('passes values through on success', async () => {
    const guard = makeGuard(() => {})
    await expect(guard(async () => 42)).resolves.toBe(42)
  })

  it('logs out on AuthError (session expiry)', async () => {
    const onExpire = vi.fn()
    const guard = makeGuard(onExpire)
    await expect(guard(async () => { throw new AuthError('unauthenticated') }))
      .resolves.toBeUndefined()
    expect(onExpire).toHaveBeenCalledOnce()
  })

  it('surfaces other errors to the notifier without throwing', async () => {
    const onExpire = vi.fn()
    const notify = vi.fn()
    setErrorNotifier(notify)
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const guard = makeGuard(onExpire)
    await expect(guard(async () => { throw new Error('server exploded') }))
      .resolves.toBeUndefined()
    expect(notify).toHaveBeenCalledWith('server exploded')
    expect(onExpire).not.toHaveBeenCalled()
  })
})
