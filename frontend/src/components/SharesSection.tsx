// Settings → Shares: the read-only links given to people who have no account.
//
// The sibling of DisplaysSection, and shaped like it on purpose: the same kind
// of object (a row whose token reaches data without a session) managed the same
// way. The one difference this file is built around is the DEFAULT. A display
// with nothing picked shows everything; a share with nothing picked shows
// nothing. So there is no "materialise the full set before removing one" step
// here, no guard on the last chip, and no collapse of "all of them" to `[]` —
// every one of those would turn a click that narrows the share into a write
// that widens it, on a link that is sent to somebody else.
//
// A section body inside the settings panel: the panel owns the heading, the
// scrolling and the way out, so this renders only the list and its controls.

import { useEffect, useRef, useState } from 'react'
import {
  api, AuthError, type Share, type ShareInput, type ShareView, type List,
} from '../api'
import { makeGuard } from '../util'
import { isOn, seenText } from '../shares'
import { useTimeFormat } from '../timeformat'
import { useI18n } from '../i18n'
import { ShareBody, type Translate } from './SharePage'

// What the agenda may reach, in days. The server accepts exactly these four and
// refuses anything else; this is only what the control offers.
const HORIZONS = [1, 7, 14, 28] as const

// One `switch` with literal keys, so the catalogue scan sees every one.
const horizonLabel = (tr: Translate, n: (typeof HORIZONS)[number]): string => {
  switch (n) {
    case 1: return tr('shares.horizon.1')
    case 7: return tr('shares.horizon.7')
    case 14: return tr('shares.horizon.14')
    case 28: return tr('shares.horizon.28')
  }
}

// How often the list asks again, to keep "Open now" honest while the section is
// on screen. It merges `last_seen_at` and nothing else (see `useEffect` below).
const REFRESH_MS = 30_000

export function SharesSection(
  { onExpire, archived = [] }: { onExpire: () => void; archived?: string[] },
) {
  const { locale, t: tr } = useI18n()
  const guard = makeGuard(onExpire)
  const tf = useTimeFormat()
  const [rows, setRows] = useState<Share[]>([])
  // What is being typed into a name field, before it is written. Held apart from
  // `rows` for the reason DisplaysSection gives: `rows` is what the SERVER has,
  // and a rollback that restores `rows` must not restore a refused draft.
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [allCals, setAllCals] = useState<List[]>([])
  const [lists, setLists] = useState<List[]>([])
  const [loaded, setLoaded] = useState(false)
  // A failed load is not an empty account: `makeGuard` resolves undefined on a
  // 502, and "no shares yet" over one is a confident lie on the only screen that
  // can revoke a link that reaches this calendar.
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [copied, setCopied] = useState<string | null>(null)
  // A preview is the server's own answer for one share, so it is never built
  // here. `'failed'` is kept apart from absent so the button can say what happened.
  const [previews, setPreviews] = useState<Record<string, ShareView | 'failed'>>({})
  // Bumped whenever a share's preview is dropped, so an answer that was already
  // on its way when the share changed does not land afterwards and show the
  // owner a picture of the link as it USED to be.
  const previewSeq = useRef<Record<string, number>>({})

  useEffect(() => {
    let alive = true
    Promise.all([
      guard(() => api.shares()),
      guard(() => api.calendars()),
      guard(() => api.lists()),
    ]).then(([s, c, l]) => {
      if (!alive) return
      if (Array.isArray(s)) setRows(s)
      else setFailed(true)
      if (Array.isArray(c)) setAllCals(c)
      if (Array.isArray(l)) setLists(l)
      setLoaded(true)
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keeps "Open now" and "Last opened" current while somebody watches the other
  // person open the link. Merges ONLY `last_seen_at`: the rest of a row is what
  // the owner is editing, and replacing it from a poll would throw away an
  // optimistic write in flight or a half-typed name. A failure is silent apart
  // from an expired session, since the next tick is only 30 seconds away.
  useEffect(() => {
    if (!loaded || failed) return
    let alive = true
    const id = setInterval(() => {
      api.shares().then((fresh) => {
        if (!alive || !Array.isArray(fresh)) return
        setRows((r) => r.map((d) => {
          const f = fresh.find((x) => x.id === d.id)
          return f && f.last_seen_at !== d.last_seen_at ? { ...d, last_seen_at: f.last_seen_at } : d
        }))
      }).catch((e) => { if (e instanceof AuthError) onExpire() })
    }, REFRESH_MS)
    return () => { alive = false; clearInterval(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, failed])

  // Archived calendars are not offered as sources: the viewer's payload drops
  // them unconditionally, so a chip for one would be lit as something the other
  // person sees when they do not. One that is ALREADY selected stays on offer,
  // muted, so the owner can take it off rather than have it sit in the
  // allowlist where nothing shows it.
  const calsFor = (d: Share) => allCals.filter((c) => !archived.includes(c.id) || d.calendars.includes(c.id))

  // `adding` bounds flight, as it does for a display: every POST mints a new
  // token that reaches the calendar without a session, so a second Enter during
  // the round trip must not mint a second link of the same name.
  const [adding, setAdding] = useState(false)
  const add = async () => {
    const trimmed = name.trim()
    if (!trimmed || adding) return
    setAdding(true)
    let made: Share | undefined
    try {
      // `{ name }` only. A new share shows nothing until the owner picks
      // something, and that is a property of the server, not of what is sent.
      made = await guard(() => api.createShare({ name: trimmed }))
    } finally {
      setAdding(false)
    }
    if (!made) return
    setRows((r) => [...r, made])
    setName('')
    // Opened straight away: a new link is useless until something is picked.
    setOpen(made.id)
  }

  const dropPreview = (id: string) => {
    previewSeq.current[id] = (previewSeq.current[id] ?? 0) + 1
    setPreviews((p) => { const { [id]: _drop, ...rest } = p; return rest })
  }

  // Painted immediately and rolled back on failure, as in every other write in
  // the app. ONE ROW rolls back, not the whole array, so a write elsewhere that
  // landed meanwhile survives; and the row is replaced by the server's DTO,
  // which is the truth about what was stored.
  const patch = async (id: string, body: ShareInput) => {
    const before = rows.find((d) => d.id === id)
    dropPreview(id)
    setRows((r) => r.map((d) => (d.id === id
      ? {
        ...d, ...body,
        // Switching a link on clears the reason it was off; the server's DTO
        // agrees, and until it arrives the row must not say both.
        ...(body.enabled ? { switched_off_by_password: false } : {}),
      } as Share
      : d)))
    const saved = await guard(() => api.patchShare(id, body))
    setRows((r) => r.map((d) => (d.id === id ? (saved ?? before ?? d) : d)))
    // Spent either way: on success the DTO is the truth, and on failure the
    // field has to snap back rather than go on showing the refused value.
    setDrafts((x) => { const { [id]: _drop, ...rest } = x; return rest })
    return saved
  }

  const rotate = async (id: string) => {
    const saved = await guard(() => api.rotateShareToken(id))
    if (!saved) return
    dropPreview(id)
    setRows((r) => r.map((d) => (d.id === id ? saved : d)))
    // Keyed by `id`, not the token, so the open editor stays open across this and
    // the freshly issued URL is on screen where it was minted.
  }

  const remove = async (id: string) => {
    const at = rows.findIndex((d) => d.id === id)
    const before = rows[at]
    setRows((r) => r.filter((d) => d.id !== id))
    setConfirming(null)
    dropPreview(id)
    if (await guard(() => api.deleteShare(id)) !== undefined) return
    // Put back exactly the row that failed to delete, where it was.
    if (before) {
      setRows((r) => {
        if (r.some((d) => d.id === id)) return r
        const next = [...r]
        next.splice(Math.min(at, next.length), 0, before)
        return next
      })
    }
  }

  const togglePreview = async (id: string) => {
    if (previews[id]) return dropPreview(id)
    const seq = previewSeq.current[id] ?? 0
    let view: ShareView | 'failed'
    try {
      view = await api.sharePreview(id)
    } catch (e) {
      if (e instanceof AuthError) { onExpire(); return }
      view = 'failed'
    }
    if ((previewSeq.current[id] ?? 0) !== seq) return
    setPreviews((p) => ({ ...p, [id]: view }))
  }

  // The server's absolute url when it knows its origin; inside the Windows
  // client `location.origin` is http://localhost:<port>, a page only that
  // machine can open.
  const urlFor = (d: Share) => d.url ?? `${location.origin}/share/${d.token}`

  const copy = async (key: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(key)
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 2000)
    } catch {
      // Refused (an insecure origin, a permissions policy). The link is on
      // screen and selectable, so there is nothing to recover.
    }
  }

  const setDraft = (id: string, value: string) => setDrafts((x) => ({ ...x, [id]: value }))
  const clearDraft = (id: string) =>
    setDrafts((x) => { const { [id]: _drop, ...rest } = x; return rest })
  /** Escape on the blur-committed name: drop the draft and keep the sheet open.
   *  `useEscape` is bound to the window and would unmount the settings panel. */
  const escapeReverts = (id: string) => (e: React.KeyboardEvent) => {
    if (e.key !== 'Escape') return
    e.preventDefault(); e.stopPropagation(); clearDraft(id)
  }

  /** Membership toggled, and nothing else: turning the last chip off writes
   *  `[]`, which the server reads as nothing. */
  const toggled = (ids: string[], id: string): string[] =>
    ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]

  if (!loaded) return <div className="empty">{tr('shares.loading')}</div>
  if (failed) return <div className="empty" role="alert">{tr('shares.loadFailed')}</div>

  return (
    <>
      {rows.length === 0 ? (
        <div className="empty">{tr('shares.none')}</div>
      ) : (
        <div className="disp-list">
          {rows.map((d) => {
            const shownCals = calsFor(d)
            const nothing = d.lists.length === 0 && d.calendars.length === 0 && !d.show_focus
            const preview = previews[d.id]
            return (
              <div key={d.id} className="disp">
                <div className="disp-main">
                  <div className="disp-name">{d.name}</div>
                  <div className="disp-meta">
                    {d.lists.length > 0
                      ? <span className="chip">{tr('shares.listsCount', { count: d.lists.length })}</span>
                      : null}
                    {d.calendars.length > 0
                      ? <span className="chip">{tr('shares.calendarsCount', { count: d.calendars.length })}</span>
                      : null}
                    {d.show_focus ? <span className="chip">{tr('shares.focusChip')}</span> : null}
                    {nothing ? <span className="chip warn">{tr('shares.nothingChip')}</span> : null}
                    {!isOn(d) ? <span className="chip">{tr('shares.off')}</span> : null}
                    <span className="mono">{seenText(d, Date.now(), tr, tf, locale)}</span>
                  </div>
                  {d.switched_off_by_password ? (
                    <div className="hintline warn">{tr('shares.offByPassword')}</div>
                  ) : null}
                </div>
                <button className="btn ghost"
                  aria-label={`${copied === d.id ? tr('shares.copied') : tr('shares.copy')} ${d.name}`}
                  onClick={() => void copy(d.id, urlFor(d))}>
                  {copied === d.id ? tr('shares.copied') : tr('shares.copy')}
                </button>
                <button className="btn ghost"
                  onClick={() => setOpen((o) => (o === d.id ? null : d.id))}
                  aria-expanded={open === d.id}>
                  {open === d.id ? tr('shares.done') : tr('shares.edit')}
                </button>

                {open === d.id ? (
                  <div className="disp-editor">
                    <div className="menu-row">
                      <label htmlFor={`share-name-${d.id}`}>{tr('shares.add')}</label>
                      <input id={`share-name-${d.id}`} className="input"
                        value={drafts[d.id] ?? d.name}
                        maxLength={100}
                        onChange={(e) => setDraft(d.id, e.target.value)}
                        onBlur={(e) => {
                          const next = e.target.value.trim()
                          // An empty name is refused, and REVERTING is the half
                          // that keeps the field honest about what the server holds.
                          if (!next || next === d.name) return clearDraft(d.id)
                          void patch(d.id, { name: next })
                        }}
                        onKeyDown={escapeReverts(d.id)} />
                    </div>
                    <div className="hintline">{tr('shares.nameHint')}</div>

                    <div className="menu-head">{tr('shares.whatTheySee')}</div>

                    <div className="menu-head" id={`share-lists-${d.id}`}>{tr('shares.lists')}</div>
                    {lists.length === 0 ? (
                      <div className="hintline">{tr('shares.noLists')}</div>
                    ) : (
                      <div className="disp-picks" role="group" aria-labelledby={`share-lists-${d.id}`}>
                        {lists.map((c) => {
                          const on = d.lists.includes(c.id)
                          return (
                            <button key={c.id}
                              className={`chip${on ? ' is-on' : ''}`}
                              aria-pressed={on}
                              onClick={() => void patch(d.id, { lists: toggled(d.lists, c.id) })}>
                              {c.name}
                            </button>
                          )
                        })}
                      </div>
                    )}

                    <div className="menu-head" id={`share-cals-${d.id}`}>{tr('shares.calendars')}</div>
                    {shownCals.length === 0 ? (
                      <div className="hintline">{tr('shares.noCalendars')}</div>
                    ) : (
                      <div className="disp-picks" role="group" aria-labelledby={`share-cals-${d.id}`}>
                        {shownCals.map((c) => {
                          const on = d.calendars.includes(c.id)
                          const old = archived.includes(c.id)
                          return (
                            <button key={c.id}
                              className={`chip${on ? ' is-on' : ''}${old ? ' is-archived' : ''}`}
                              aria-pressed={on}
                              title={old ? tr('shares.archived') : undefined}
                              onClick={() => void patch(d.id, { calendars: toggled(d.calendars, c.id) })}>
                              {c.name}
                            </button>
                          )
                        })}
                      </div>
                    )}
                    <div className="hintline">{tr('shares.privateHint')}</div>

                    <div className="menu-head" id={`share-horizon-${d.id}`}>{tr('shares.horizon')}</div>
                    <div className="disp-picks" role="group" aria-labelledby={`share-horizon-${d.id}`}>
                      {HORIZONS.map((n) => (
                        <button key={n}
                          className={`chip${d.horizon_days === n ? ' is-on' : ''}`}
                          aria-pressed={d.horizon_days === n}
                          onClick={() => {
                            if (d.horizon_days !== n) void patch(d.id, { horizon_days: n })
                          }}>
                          {horizonLabel(tr, n)}
                        </button>
                      ))}
                    </div>

                    <div className="menu-row">
                      <label htmlFor={`share-focus-${d.id}`}>{tr('shares.focus')}</label>
                      <button id={`share-focus-${d.id}`} className="menu-toggle"
                        aria-pressed={d.show_focus}
                        onClick={() => void patch(d.id, { show_focus: !d.show_focus })}>
                        {tr(d.show_focus ? 'shares.on' : 'shares.off')}
                      </button>
                    </div>
                    <div className="hintline">{tr('shares.focusHint')}</div>

                    {nothing ? (
                      <div className="hintline warn" role="status">{tr('shares.nothingSelected')}</div>
                    ) : null}

                    <div className="menu-row">
                      <label htmlFor={`share-enabled-${d.id}`}>{tr('shares.enabled')}</label>
                      <button id={`share-enabled-${d.id}`} className="menu-toggle"
                        aria-pressed={isOn(d)}
                        onClick={() => void patch(d.id, { enabled: !isOn(d) })}>
                        {tr(isOn(d) ? 'shares.on' : 'shares.off')}
                      </button>
                    </div>
                    <div className="hintline">{tr('shares.enabledHint')}</div>

                    <div className="disp-url">
                      <code className="mono">{urlFor(d)}</code>
                      <button className="btn ghost" onClick={() => void copy(`${d.id}-url`, urlFor(d))}>
                        {copied === `${d.id}-url` ? tr('shares.copied') : tr('shares.copy')}
                      </button>
                    </div>
                    <div className="hintline">{tr('shares.urlHint')}</div>

                    <div className="menu-actions">
                      <button className="btn ghost" aria-expanded={preview !== undefined}
                        onClick={() => void togglePreview(d.id)}>
                        {preview ? tr('shares.hidePreview') : tr('shares.preview')}
                      </button>
                    </div>
                    {preview === 'failed' ? (
                      <div className="hintline" role="alert">{tr('shares.previewFailed')}</div>
                    ) : preview ? (
                      <>
                        <div className="hintline">{tr('shares.previewNote')}</div>
                        <div className="share-preview">
                          <ShareBody view={preview} nowMs={Date.now()} skewMs={0}
                            tr={tr} locale={locale} justDone={new Set()} />
                        </div>
                      </>
                    ) : null}

                    <div className="menu-actions">
                      <button className="btn ghost" onClick={() => void rotate(d.id)}>
                        {tr('shares.rotate')}
                      </button>
                      {confirming === d.id ? (
                        <>
                          <button className="btn ghost" onClick={() => setConfirming(null)}>
                            {tr('shares.keep')}
                          </button>
                          <button className="btn danger" onClick={() => void remove(d.id)}>
                            {tr('shares.deleteConfirm')}
                          </button>
                        </>
                      ) : (
                        <button className="btn danger" onClick={() => setConfirming(d.id)}>
                          {tr('shares.delete')}
                        </button>
                      )}
                    </div>
                    <div className="hintline">{tr('shares.rotateHint')}</div>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      <div className="menu-head">{tr('shares.add')}</div>
      <div className="disp-add">
        <input className="input" value={name} maxLength={100}
          placeholder={tr('shares.add')}
          aria-label={tr('shares.add')}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void add() }} />
        <button className="btn" onClick={() => void add()} disabled={!name.trim() || adding}>
          {tr('shares.addButton')}
        </button>
      </div>
    </>
  )
}
