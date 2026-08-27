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

export function ConnectionsSection({ onExpire }: {
  onExpire: () => void
}) {
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
  const disconnect = async (id: string) => {
    const prev = rows
    setRows((r) => r.filter((x) => x.family_id !== id))
    setConfirming(null)
    if (await guard(() => api.mcpDisconnect(id)) === undefined) setRows(prev)
  }

  const what = (scope: string) => {
    const can = scope.split(' ').filter(Boolean)
    if (can.includes('mcp:write')) return 'Read and write'
    if (can.includes('mcp:read')) return 'Read only'
    return scope || 'No access'
  }

  return (
    <>
      {!loaded ? (
        <div className="empty">Loading…</div>
      ) : failed ? (
        <div className="empty" role="alert">
          Couldn&rsquo;t load your connected applications. Any grants you have
          are still live — this list could not be read, not emptied.
        </div>
      ) : rows.length === 0 ? (
        <div className="empty">
          Nothing is connected. Applications you connect through the MCP
          endpoint appear here.
        </div>
      ) : (
        <div className="conn-list">
          {rows.map((c) => (
            <div key={c.family_id} className="conn">
              <div className="conn-main">
                <div className="conn-name">{c.client_name || 'An application'}</div>
                <div className="conn-meta">
                  <span className="chip">{what(c.scope)}</span>
                  <span className="mono">Connected {fmtWhen(isoOf(c.granted_at), tf)}</span>
                </div>
              </div>
              {confirming === c.family_id ? (
                <span className="conn-actions">
                  <button className="btn ghost" onClick={() => setConfirming(null)}>Keep</button>
                  <button className="btn danger" onClick={() => disconnect(c.family_id)}>
                    Disconnect
                  </button>
                </span>
              ) : (
                <button className="btn ghost" onClick={() => setConfirming(c.family_id)}>
                  Disconnect
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="hintline">
        Disconnecting takes effect at once — the application has to be
        reconnected, and approved again, before it can read anything.
      </div>
    </>
  )
}

// The API reports these as UNIX seconds (they are OAuth timestamps, not
// iCalendar values), so they need turning into something `fmtWhen` can read.
function isoOf(seconds: number): string {
  const d = new Date(seconds * 1000)
  return isNaN(d.getTime()) ? '' : d.toISOString()
}
