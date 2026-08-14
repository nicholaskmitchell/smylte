// The 12/24-hour choice, handed to the leaves that render a clock.
//
// A context rather than a prop: seven call sites sit in six components, two of
// them (DayPopover, ArchivedCalendarsModal) reachable only through an
// intermediary that has no other use for the value. Threading a display-only
// preference through five parents to reach them would be noise in every
// signature it passed through. Everything else App owns is genuinely the
// caller's business — which list is hidden, which tab is open — and stays a
// prop.
//
// The default is the app's historical behaviour, so a component rendered
// outside the provider (every existing test) formats exactly as it did before.

import { createContext, useContext, type ReactNode } from 'react'
import { DEFAULT_TIME_FORMAT, type TimeFormat } from './time'

const Ctx = createContext<TimeFormat>(DEFAULT_TIME_FORMAT)

export function TimeFormatProvider({ value, children }: {
  value: TimeFormat
  children: ReactNode
}) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTimeFormat(): TimeFormat {
  return useContext(Ctx)
}
