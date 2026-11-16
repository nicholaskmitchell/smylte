// What the phone's coral add button does, view by view.
//
// The button lives in the tab bar (AppNav.tsx), but "add" means something
// different on each view: Today's quick add, the Tasks quick add, a new event.
// Each view says what its own add is with `useAddAction(tab, open)`; the button
// is drawn only for a view that registered one, and calls the open view's.
//
// A registry rather than a prop threaded through App: the add form, its field
// and its open/closed state belong to the view, and the shell has no business
// knowing which input to focus. Outside the provider (unit tests that mount a
// view alone) registration is a no-op.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Tab } from './tabs'

type Register = (tab: Tab, open: (() => void) | null) => void

const AddCtx = createContext<Register>(() => {})

/** The registry itself, for the shell that draws the button: `register` goes
 *  to the provider, `opens[tab]` to the button. */
export function useAddRegistry() {
  const [opens, setOpens] = useState<Partial<Record<Tab, () => void>>>({})
  const register = useCallback<Register>((t, open) => {
    setOpens((cur) => {
      if (open ? cur[t] === open : !(t in cur)) return cur
      const next = { ...cur }
      if (open) next[t] = open
      else delete next[t]
      return next
    })
  }, [])
  return { register, opens }
}

export function AddActionProvider({ register, children }: { register: Register; children: ReactNode }) {
  return <AddCtx.Provider value={register}>{children}</AddCtx.Provider>
}

/** Say what the coral add button does while `tab` is open. `open` may change
 *  every render; the latest is always the one called. */
export function useAddAction(tab: Tab, open: (() => void) | null): void {
  const register = useContext(AddCtx)
  const latest = useRef(open)
  latest.current = open
  const stable = useMemo(() => () => latest.current?.(), [])
  const has = open !== null
  useEffect(() => {
    if (!has) return
    register(tab, stable)
    return () => register(tab, null)
  }, [register, tab, stable, has])
}
