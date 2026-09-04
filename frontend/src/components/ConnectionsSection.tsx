// Applications connected to this account through the MCP connector.
//
// The consent screen tells the user they can disconnect later, so this is where
// that promise is kept — and it is the only way to end a grant from inside the
// app. Disconnecting revokes the whole rotation family, so the access token and
// every refresh token minted from the same approval stop working at once.
//
// A section body inside the settings panel: the panel owns the heading, the
// scrolling and the way out, so this renders only the list and its caveat.

import { useEffect, useState } from 'react'
import { api, type McpConnection } from '../api'
import { makeGuard } from '../util'
import { fmtWhen } from '../time'
import { useTimeFormat } from '../timeformat'
import { useI18n } from '../i18n'

export function ConnectionsSection({ onExpire }: {
  onExpire: () => void
}) {
  const { locale, t: tr } = useI18n()
  const guard = makeGuard(onExpire)
  const tf = useTimeFormat()
  const [rows, setRows] = useState<McpConnection[]>([])
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)

  // `failed`, distinguished from an empty account — the flag ArchivedCalendarsSection
  // ten lines away in the same settings panel already carries, with the comment
  // saying why: an empty state over a failed fetch is a confident lie about the
  // account. `makeGuard` swallows the rejection and resolves undefined, so a
  // 502 or a timeout landed in the exact same render as "you have connected
  // nothing" — on the ONLY screen that shows which applications hold a live MCP
  // OAuth grant over the whole account, and the only place one can be revoked.
  useEffect(() => {
    let alive = true
    guard(() => api.mcpConnections()).then((r) => {
      if (!alive) return
      if (Array.isArray(r)) setRows(r)
      else setFailed(true)
      setLoaded(true)
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Painted immediately: the request settles behind, and a failure puts the row
  // back rather than leaving the list claiming a disconnection that never landed.
  //
  // ONE ROW goes back, where it was — not a snapshot of the whole array as it
  // looked when the call started. That snapshot carried every other grant that
  // was still listed at the time, so a second Disconnect confirmed while the
  // first DELETE was in flight (seconds, under the service lock) came back as
  // "connected, read and write" when the first one failed — a revoked grant
  // shown live on the only screen that shows which applications hold access.
  // DisplaysSection.remove in the same panel was rewritten this way earlier.
  const disconnect = async (id: string) => {
    const at = rows.findIndex((x) => x.family_id === id)
    const before = rows[at]
    setRows((r) => r.filter((x) => x.family_id !== id))
    setConfirming(null)
    if (await guard(() => api.mcpDisconnect(id)) !== undefined) return
    if (before) {
      setRows((r) => {
        if (r.some((x) => x.family_id === id)) return r
        const next = [...r]
        next.splice(Math.min(at, next.length), 0, before)
        return next
      })
    }
  }

  const what = (scope: string) => {
    const can = scope.split(' ').filter(Boolean)
    if (can.includes('mcp:write')) return tr('conn.readWrite')
    if (can.includes('mcp:read')) return tr('conn.readOnly')
    // A scope the server invented and we have no word for is shown RAW —
    // untranslated, but true. Calling an unknown grant "Kein Zugriff" would
    // be a translation of something we did not read.
    return scope || tr('conn.noAccess')
  }

  return (
    <>
      {!loaded ? (
        <div className="empty">{tr('conn.loading')}</div>
      ) : failed ? (
        <div className="empty" role="alert">{tr('conn.loadFailed')}</div>
      ) : rows.length === 0 ? (
        <div className="empty">{tr('conn.none')}</div>
      ) : (
        <div className="conn-list">
          {rows.map((c) => (
            <div key={c.family_id} className="conn">
              <div className="conn-main">
                <div className="conn-name">{c.client_name || tr('conn.anApplication')}</div>
                <div className="conn-meta">
                  <span className="chip">{what(c.scope)}</span>
                  <span className="mono">{tr('conn.connectedAt', { when: fmtWhen(isoOf(c.granted_at), tf, locale) })}</span>
                </div>
              </div>
              {confirming === c.family_id ? (
                <span className="conn-actions">
                  <button className="btn ghost" onClick={() => setConfirming(null)}>{tr('conn.keep')}</button>
                  <button className="btn danger" onClick={() => disconnect(c.family_id)}>
                    {tr('conn.disconnect')}
                  </button>
                </span>
              ) : (
                <button className="btn ghost" onClick={() => setConfirming(c.family_id)}>
                  {tr('conn.disconnect')}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="hintline">{tr('conn.hint')}</div>
    </>
  )
}

// The API reports these as UNIX seconds (they are OAuth timestamps, not
// iCalendar values), so they need turning into something `fmtWhen` can read.
function isoOf(seconds: number): string {
  const d = new Date(seconds * 1000)
  return isNaN(d.getTime()) ? '' : d.toISOString()
}
