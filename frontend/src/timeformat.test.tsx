// The wiring between the stored 12/24-hour setting and a rendered clock.
//
// `time.test.ts` covers the formatters thoroughly in both formats, and
// `App.test.tsx` covers the setting's round trip — but nothing joined the two.
// timeformat.tsx says why that matters in its own header: "a component rendered
// outside the provider (every existing test) formats exactly as it did before",
// i.e. always 12-hour. So an edit replacing `const tf = useTimeFormat()` /
// `fmtClock(iso, tf)` with `fmtClock(iso, DEFAULT_TIME_FORMAT)` — the easy
// outcome of untangling a prop-drilling refactor, and one `tsc --noEmit` accepts
// because both are `TimeFormat` — left all 1115 frontend tests green while an
// account set to 24-hour saw `2:05 PM` on every chip and the Settings screen
// went on reading "24-hour".
//
// Two halves, because neither alone is enough. The render half proves the
// context actually reaches a leaf and changes what it prints. The source half
// proves the other seventeen call sites still ASK for it, which no render can
// check without mounting all of them.

import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { TimeFormatProvider } from './timeformat'
import { AgendaEvent, AgendaTask } from './components/DayPopover'
import type { CalEvent, Task } from './api'

// 18:05Z is 14:05 in America/New_York, the zone vite.config.ts pins the
// suite to — so the expected strings are stable on any machine.
const AFTERNOON = '2026-08-21T18:05:00Z'

const ev = {
  uid: 'e1', calendar: 'work', summary: 'Standup',
  start: AFTERNOON, end: '2026-08-21T18:35:00Z',
  start_is_date: false, end_is_date: false,
} as unknown as CalEvent

const task = {
  uid: 't1', list: 'work', summary: 'Invoice',
  due: AFTERNOON, due_is_date: false,
} as unknown as Task

const inProvider = (value: '12h' | '24h', node: ReactNode) =>
  render(<TimeFormatProvider value={value}>{node}</TimeFormatProvider>)

describe('the 12/24-hour setting reaches what is rendered', () => {
  it('prints a 24-hour clock on an event chip when the account chose 24h', () => {
    inProvider('24h', <AgendaEvent ev={ev as never} day="2026-08-21" />)
    const row = screen.getByText('Standup').closest('.agenda-ev')!
    expect(row.textContent).toMatch(/14:05/)
    expect(row.textContent).not.toMatch(/[AP]M/i)
  })

  it('prints a 12-hour clock on the same chip when the account chose 12h', () => {
    inProvider('12h', <AgendaEvent ev={ev as never} day="2026-08-21" />)
    const row = screen.getByText('Standup').closest('.agenda-ev')!
    expect(row.textContent).toMatch(/2:05/)
    expect(row.textContent).toMatch(/PM/i)
  })

  it('applies to a task due time as well as an event span', () => {
    inProvider('24h', <AgendaTask task={task as never} />)
    const row = screen.getByText('Invoice').closest('.agenda-ev')!
    expect(row.textContent).toMatch(/14:05/)
    expect(row.textContent).not.toMatch(/[AP]M/i)
  })
})

// ── every other consumer still asks the context for it ──────────────────────

const SRC = resolve(process.cwd(), 'src')

function componentSources(): [string, string][] {
  const dir = resolve(SRC, 'components')
  return readdirSync(dir)
    .filter((f) => f.endsWith('.tsx') && !f.includes('.test.'))
    .map((f) => [f, readFileSync(resolve(dir, f), 'utf8')] as [string, string])
}

/** Source with comments stripped, so prose naming a symbol is never mistaken
 *  for a call to it — the same rule mobile-layout.test.ts applies to CSS. */
const stripped = (s: string) =>
  s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

const FORMATTERS = ['fmtClock', 'fmtDue', 'fmtWhen', 'inputLang']

describe('no component hardcodes a time format', () => {
  it('every component that formats a clock reads the setting from the context', () => {
    const offenders: string[] = []
    for (const [name, raw] of componentSources()) {
      const src = stripped(raw)
      const formats = FORMATTERS.some((f) => new RegExp(`\\b${f}\\s*\\(`).test(src))
      if (!formats) continue
      if (!/\buseTimeFormat\s*\(\s*\)/.test(src)) {
        offenders.push(`${name} formats a time but never calls useTimeFormat()`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('no formatter call site is handed DEFAULT_TIME_FORMAT instead', () => {
    const offenders: string[] = []
    for (const [name, raw] of componentSources()) {
      const src = stripped(raw)
      for (const f of FORMATTERS) {
        // `fmtClock(x, DEFAULT_TIME_FORMAT)` — the exact regression this file
        // exists for. The default belongs in timeformat.tsx's createContext and
        // in time.ts, and nowhere a component can reach past the setting with it.
        if (new RegExp(`\\b${f}\\s*\\([^)]*DEFAULT_TIME_FORMAT`).test(src)) {
          offenders.push(`${name} passes DEFAULT_TIME_FORMAT to ${f}()`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('App is the one place that mounts the provider', () => {
    const app = stripped(readFileSync(resolve(SRC, 'App.tsx'), 'utf8'))
    expect(app).toMatch(/<TimeFormatProvider/)
  })
})
