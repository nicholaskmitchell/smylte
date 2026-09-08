import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthError } from './api'
import { addDays, cssColor, dayKey, daysPastDue, hasZone, instantFromLocal, isOverdue, makeGuard, pad, parseDate, setErrorNotifier, textDir, toLocalInput, ymd } from './util'

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

  // fmtDue moved to time.ts with the rest of the clock formatting — see
  // time.test.ts for its null/garbage handling and both clock formats.

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

describe('hasZone', () => {
  it.each([
    ['2026-08-10T09:30:00+02:00', true],
    ['2026-08-10T09:30:00-04:00', true],
    ['2026-08-10T09:30:00+0200', true],
    ['2026-08-10T09:30:00Z', true],
    ['2026-08-10T09:30:00', false],      // floating — what the app writes itself
    ['2026-08-10T09:30', false],
    ['2026-08-10', false],               // all-day
    [null, false],
    [undefined, false],
  ])('%s -> %s', (iso, expected) => {
    expect(hasZone(iso as string | null | undefined)).toBe(expected)
  })

  it('is not fooled by the dashes in the date half', () => {
    expect(hasZone('2026-08-10T09:30:00')).toBe(false)
  })
})

describe('instantFromLocal', () => {
  it('names the instant the local wall clock picks out', () => {
    // The suite runs in America/New_York, so 04:30 local is 08:30Z.
    expect(instantFromLocal('2026-08-10', '04:30')).toBe('2026-08-10T08:30:00.000Z')
  })

  it('hands an unparseable pair straight back rather than inventing a date', () => {
    expect(instantFromLocal('nonsense', '04:30')).toBe('nonsenseT04:30')
  })
})

// ── a wire color must never reach the CSSOM unchecked ───────────────────────
// `List.color` is served from whatever another CalDAV client wrote into the
// collection's `ical:calendar-color` — an Apple dead property anything sharing
// the collection can PROPPATCH — and the SPA writes it into element styles, as
// a `background` and as the `--ev-c` custom property that app.css resolves into
// `background: var(--ev-c, var(--accent))`. So `url(...)` on a rendered 3-5px
// dot makes the browser fetch it, a beacon that fires whenever the owner opens
// the Calendar tab. There is no CSP in this app to stop it.

describe('cssColor', () => {
  it.each([
    ['a url() beacon', 'url(https://evil.example/x.png)'],
    ['a protocol-relative url()', 'url(//evil.example/x)'],
    ['a value escaping the declaration', 'red; background: url(//evil.example/x)'],
    ['an image()', 'image(//evil.example/x)'],
    ['a legacy expression()', 'expression(alert(1))'],
    ['a var() reference', 'var(--bg)'],
    ['a named color', 'red'],
    ['an rgb() call', 'rgb(1,2,3)'],
    ['a short hex', '#123'],
    ['a malformed hex', '#GGGGGG'],
    ['an empty string', ''],
    ['null', null],
    ['undefined', undefined],
  ])('refuses %s', (_label, value) => {
    expect(cssColor(value)).toBeNull()
  })

  it.each([
    ['#D9480F', '#D9480F'],
    ['#d9480f', '#d9480f'],
    ['#D9480F80', '#D9480F80'],     // RRGGBBAA, which the app writes
    ['  #D9480F  ', '#D9480F'],     // trimmed, like the backend does
  ])('passes %s through', (input, expected) => {
    expect(cssColor(input)).toBe(expected)
  })

  it('agrees with the shape the backend enforces on both paths', async () => {
    // dav/xml.py's COLOR_PATTERN. Pinned by reading it off disk, the way
    // appearance.test.ts pins the pre-paint script — a divergence here means
    // one layer accepts what the other refuses.
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const src = readFileSync(
      resolve(process.cwd(), '../backend/tasksd/dav/xml.py'), 'utf8')
    const m = /COLOR_PATTERN = r"([^"]+)"/.exec(src)
    expect(m).not.toBeNull()
    // Python's (?:…) is a non-capturing group; JS spells it the same way.
    const backend = new RegExp(m![1])
    for (const v of ['#D9480F', '#d9480f80']) expect(backend.test(v)).toBe(true)
    for (const v of ['url(//x)', 'red', '#123']) expect(backend.test(v)).toBe(false)
  })
})

describe('textDir', () => {
  // Which end of a title an ellipsis eats follows the direction of the box, not
  // the text — so a chip holding an Arabic title has to be marked rtl or it
  // gets clipped at the beginning, the half you need to recognise it by.
  it('marks a title that begins in a right-to-left script', () => {
    expect(textDir('اجتماع الفريق الأسبوعي')).toBe('rtl')
    expect(textDir('פגישת צוות')).toBe('rtl')
  })

  it('leaves a left-to-right title alone', () => {
    expect(textDir('Weekly standup')).toBeUndefined()
    expect(textDir('会議')).toBeUndefined()
  })

  it('reads the FIRST strong character, skipping what has no direction', () => {
    // Leading digits and punctuation belong to whatever follows them.
    expect(textDir('١٢٣ اجتماع')).toBe('rtl')
    expect(textDir('— اجتماع')).toBe('rtl')
    expect(textDir('123 Standup')).toBeUndefined()
    // …and a Latin lead keeps the chip ltr however much Arabic follows it.
    expect(textDir('Re: اجتماع الفريق')).toBeUndefined()
  })

  it('has no opinion about a title that is not there', () => {
    expect(textDir('')).toBeUndefined()
    expect(textDir(null)).toBeUndefined()
    expect(textDir(undefined)).toBeUndefined()
  })
})

describe('daysPastDue', () => {
  // Fixed, so the reading is decidable without the wall clock — the same
  // bargain every date function in this module strikes.
  const DAY = '2026-09-06'

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(`${DAY}T09:00:00`))
  })
  afterEach(() => vi.useRealTimers())

  it('counts whole days, not hours', () => {
    // The threshold is a claim about days. One that flipped at some hour of the
    // morning would be a rule nobody could predict from the row.
    expect(daysPastDue('2026-09-03', true, DAY)).toBe(3)
    expect(daysPastDue('2026-09-05', true, DAY)).toBe(1)
  })

  it('is null for anything the app does not already call overdue', () => {
    // Lateness comes from `isOverdue` and nothing else, so this can never
    // disagree with the badge on the same row.
    expect(daysPastDue(null, true, DAY)).toBeNull()
    expect(daysPastDue('2026-09-20', true, DAY)).toBeNull()
    // Today's own deadline is not late, whichever shape it is in.
    expect(daysPastDue(DAY, true, DAY)).toBeNull()
    expect(daysPastDue(`${DAY}T08:00`, false, DAY)).toBeNull()
  })

  it('gives an all-day deadline its whole day before counting it', () => {
    // `isOverdue`'s rule, inherited rather than restated: yesterday's all-day
    // task became overdue at midnight and is one day late, not two.
    expect(daysPastDue('2026-09-05', true, DAY)).toBe(1)
  })

  it('crosses a month boundary as arithmetic rather than as a special case', () => {
    expect(daysPastDue('2026-08-30', true, DAY)).toBe(7)
  })
})
