// Applications connected to this account through the MCP connector.
//
// The consent screen tells the user they can disconnect later, so this is where
// that promise is kept — and it is the only way to end a grant from inside the
// app. Disconnecting revokes the whole rotation family, so the access token and
// every refresh token minted from the same approval stop working at once.

import { useEffect, useState } from 'react'
import { api, type McpConnection } from '../api'
import { makeGuard } from '../util'
import { fmtWhen } from '../time'
import { useTimeFormat } from '../timeformat'

export function ConnectionsModal({ onExpire, onClose }: {
  onExpire: () => void
  onClose: () => void
}) {
  const guard = makeGuard(onExpire)
  const tf = useTimeFormat()
  const [rows, setRows] = useState<McpConnection[]>([])
  const [loaded, setLoaded] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    guard(async () => { setRows(await api.mcpConnections()); setLoaded(true) })
      .finally(() => setLoaded(true))
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
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Connected applications"
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">Connected applications</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {!loaded ? (
          <div className="empty">Loading…</div>
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
      </div>
    </div>
  )
}

// The API reports these as UNIX seconds (they are OAuth timestamps, not
// iCalendar values), so they need turning into something `fmtWhen` can read.
function isoOf(seconds: number): string {
  const d = new Date(seconds * 1000)
  return isNaN(d.getTime()) ? '' : d.toISOString()
}
