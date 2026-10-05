// What the email reader has proposed and the owner has not yet decided.
//
// A hook rather than state inside TasksView because the sidebar needs two
// things from it before the pane is ever opened — whether to offer the button
// at all, and how many are waiting — and the pane needs the same list. One
// fetch, read by both.
//
// Re-read on `mailRev`, which App bumps on a `mail_updated` event, and never
// polled: a scan finishing and a suggestion being decided (here or on another
// device) are the only things that change this, and the server announces both.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, AuthError, type ApproveSuggestionBody, type MailSuggestion } from './api'

export interface MailSuggestions {
  items: MailSuggestion[]
  /** Email reading is switched on, here and for the deployment. Off with
   *  nothing pending means there is no pane to offer. */
  enabled: boolean
  /** The first answer has arrived (or failed), so "nothing waiting" is not
   *  just "nothing asked yet". */
  loaded: boolean
  error: string | null
  reload: () => void
  /** Resolve true when it was saved, false when it was refused and the row has
   *  been put back. */
  approve: (id: string, body: ApproveSuggestionBody) => Promise<boolean>
  reject: (id: string) => Promise<boolean>
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useMailSuggestions(mailRev: number, onExpire: () => void): MailSuggestions {
  const [items, setItemsState] = useState<MailSuggestion[]>([])
  // The same list, readable synchronously: a decision needs the row it is
  // about to remove, and a state updater only runs at the next render — after
  // a request that fails at once has already been handled.
  const rows = useRef(items)
  const setItems = useCallback((next: MailSuggestion[]) => {
    rows.current = next
    setItemsState(next)
  }, [])
  const [enabled, setEnabled] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  // Held in a ref so a parent that builds a fresh `onExpire` each render does
  // not re-run the fetch below on every one of them.
  const expire = useRef(onExpire)
  expire.current = onExpire

  useEffect(() => {
    let alive = true
    // The api call sits inside the try: a test that mocks the module wholesale
    // has no such method, and a missing one is "nothing to show", not a crash.
    ;(async () => {
      try {
        const r = await api.mailSuggestions('pending')
        if (!alive) return
        setEnabled(!!r?.enabled)
        setItems(Array.isArray(r?.suggestions) ? r.suggestions : [])
        setError(null)
      } catch (e) {
        if (!alive) return
        if (e instanceof AuthError) { expire.current(); return }
        // Keep whatever is already shown: a failed refresh is not evidence the
        // list is empty.
        setError(message(e))
      } finally {
        if (alive) setLoaded(true)
      }
    })()
    return () => { alive = false }
  }, [mailRev, tick, setItems])

  const reload = useCallback(() => setTick((n) => n + 1), [])

  // The row leaves at once and comes back, where it was, if the request fails.
  // ONE row goes back rather than a snapshot of the whole list, so a second
  // decision made while the first is in flight is not undone with it.
  const decide = useCallback(async (id: string, send: () => Promise<unknown>) => {
    const at = rows.current.findIndex((s) => s.id === id)
    const before = rows.current[at]
    setItems(rows.current.filter((s) => s.id !== id))
    setError(null)
    try {
      await send()
      return true
    } catch (e) {
      if (e instanceof AuthError) { expire.current(); return false }
      if (before && !rows.current.some((s) => s.id === id)) {
        const next = [...rows.current]
        next.splice(Math.min(at, next.length), 0, before)
        setItems(next)
      }
      setError(message(e))
      return false
    }
  }, [setItems])

  const approve = useCallback(
    (id: string, body: ApproveSuggestionBody) => decide(id, () => api.approveSuggestion(id, body)),
    [decide])
  const reject = useCallback(
    (id: string) => decide(id, () => api.rejectSuggestion(id)),
    [decide])

  return { items, enabled, loaded, error, reload, approve, reject }
}
