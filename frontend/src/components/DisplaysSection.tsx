// Settings → Displays: the passive screens paired with this account.
//
// A display takes no input, so everything about it is configured here and
// nowhere else. That is the whole reason this section exists rather than the
// panel itself carrying a mode switch: the screen in the kitchen and the one in
// the hallway want different things, and neither of them has a settings button.
//
// Shaped like the scheduling links it sits beside, because it is the same kind
// of object: a row whose primary key is a token that reaches data without a
// session. The difference is what the token reaches, and the section says so
// out loud — a booking link shows a stranger a redacted busy grid, and this one
// shows the calendar itself.
//
// A section body inside the settings panel: the panel owns the heading, the
// scrolling and the way out, so this renders only the list and its controls.

import { useEffect, useMemo, useState } from 'react'
import { api, type Display, type DisplayInput, type DisplayMode, type List } from '../api'
import { makeGuard } from '../util'
import { fmtWhen } from '../time'
import { useTimeFormat } from '../timeformat'
import { useI18n } from '../i18n'

// What a display may be set to refresh at, by palette.
//
// An e-ink panel is not offered a minute, and that is its GLASS talking rather
// than our taste: Waveshare's documentation for these screens says to refresh no
// more often than every 180 seconds and to sleep the panel in between, or it is
// damaged beyond repair. A colour display — an old tablet, an LCD — has none of
// that and keeps the minute. The server enforces the same two floors; this is
// only what the control offers.
const REFRESH_CHOICES = {
  color: [60, 300, 900, 3600],
  eink: [180, 300, 900, 3600],
} as const
const ROTATIONS = [0, 90, 180, 270] as const

// The order the mode control cycles in, which is also the order they are worth
// hanging on a wall in: the month is what most people mount one for, habits is
// what earns a kitchen, and now + next is the one that fits a panel too small
// for either.
const DISPLAY_MODES: readonly DisplayMode[] = ['calendar', 'habits', 'now']

/** What is being typed into a row's text fields, before it is written.
 *
 *  Held apart from `rows` rather than in it, and that separation is the whole
 *  point: `rows` is what the SERVER has. When the draft lived in `rows`, the
 *  optimistic-write rollback restored the value the server had just refused —
 *  it snapshotted `rows` after `onChange` had already put the typed value
 *  there — so a rejected panel size stayed on screen with no way back but a
 *  reload. Rendering `draft ?? row` keeps both facts available at once. */
type Draft = { name?: string; panel_width?: string; panel_height?: string }

export function DisplaysSection(
  { onExpire, archived = [] }: { onExpire: () => void; archived?: string[] },
) {
  const { locale, t: tr } = useI18n()
  const guard = makeGuard(onExpire)
  const tf = useTimeFormat()
  const [rows, setRows] = useState<Display[]>([])
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [allCals, setAllCals] = useState<List[]>([])
  const [lists, setLists] = useState<List[]>([])
  const [loaded, setLoaded] = useState(false)
  // Distinguished from an empty account, the same way ConnectionsSection and
  // ArchivedCalendarsSection do it and for the same reason: `makeGuard`
  // resolves undefined on a failure, so a 502 and "you have no displays" would
  // otherwise land in the identical render — on the only screen that can revoke
  // a token that reaches this calendar.
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [name, setName] = useState('')

  // Archived calendars are NOT offered as display sources. `api.calendars()`
  // returns them — the backend never filters, which is what
  // ArchivedCalendarsSection relies on — but the frame builder drops archived
  // calendars unconditionally. Offering them here drew a chip lit up as
  // something the wall panel was showing when it was not, and let the owner
  // build an allowlist that resolved to nothing at all.
  const cals = useMemo(
    () => allCals.filter((c) => !archived.includes(c.id)),
    [allCals, archived])
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    Promise.all([
      guard(() => api.displays()),
      guard(() => api.calendars()),
      guard(() => api.lists()),
    ]).then(([d, c, l]) => {
      if (!alive) return
      if (Array.isArray(d)) setRows(d)
      else setFailed(true)
      if (Array.isArray(c)) setAllCals(c)
      if (Array.isArray(l)) setLists(l)
      setLoaded(true)
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // `adding` bounds flight, as `saving` does for a booking link and `creating`
  // for a sidebar list. Without it a second Enter during the round trip — which
  // under the service lock can be seconds — POSTed a second display with the
  // same name, and every POST mints a fresh token that reads the whole calendar
  // without a session. Two rows called "Kitchen" are indistinguishable, so the
  // one deleted as the duplicate could be the one the panel was paired to.
  const [adding, setAdding] = useState(false)
  const add = async () => {
    const trimmed = name.trim()
    if (!trimmed || adding) return
    setAdding(true)
    // Cleared in a `finally` rather than on failure only: unlike the booking
    // link modal, this section stays mounted after a success, and its Add
    // button has to come back for the next display.
    let made: Display | undefined
    try {
      made = await guard(() => api.createDisplay({ name: trimmed }))
    } finally {
      setAdding(false)
    }
    if (!made) return
    setRows((r) => [...r, made])
    setName('')
    // Opened straight away. A display is useless until it has been pointed at a
    // panel, and the URL to point it at is inside the editor.
    setOpen(made.token)
  }

  // Painted immediately and rolled back on failure, matching every other write
  // in the app. The row is replaced rather than merged: the server's DTO is the
  // truth about what was stored, including a value it clamped.
  //
  // ONE ROW rolls back, not the whole array. Restoring a snapshot of `rows`
  // discarded every unrelated change that landed while the write was in flight
  // — another row's successful edit, a delete, a token rotation. The rotation
  // was the worst of them: the snapshot carried the dead pre-rotate token while
  // `open` had already moved to the new one, so the editor collapsed and the
  // freshly issued URL disappeared off the screen that had just minted it.
  const patch = async (token: string, body: Partial<DisplayInput>) => {
    const before = rows.find((d) => d.token === token)
    setRows((r) => r.map((d) => (d.token === token ? { ...d, ...body } as Display : d)))
    const saved = await guard(() => api.patchDisplay(token, body))
    setRows((r) => r.map((d) => (d.token === token ? (saved ?? before ?? d) : d)))
    // Either way the draft is spent: on success the server's DTO is the truth,
    // and on failure the field must snap back to it rather than go on showing
    // the value that was just refused.
    setDrafts((x) => { const { [token]: _drop, ...rest } = x; return rest })
    return saved
  }

  const rotate = async (token: string) => {
    const saved = await guard(() => api.rotateDisplayToken(token))
    if (!saved) return
    setRows((r) => r.map((d) => (d.token === token ? saved : d)))
    // The row's identity IS the token, so the open editor has to follow it or
    // the panel would collapse the moment someone rotated a key.
    setOpen((o) => (o === token ? saved.token : o))
  }

  const remove = async (token: string) => {
    const at = rows.findIndex((d) => d.token === token)
    const before = rows[at]
    setRows((r) => r.filter((d) => d.token !== token))
    setConfirming(null)
    if (await guard(() => api.deleteDisplay(token)) !== undefined) return
    // Put back exactly the row that failed to delete, where it was — rather
    // than the whole array as it looked when the call started, which would
    // resurrect anything else deleted in the meantime.
    if (before) {
      setRows((r) => {
        if (r.some((d) => d.token === token)) return r
        const next = [...r]
        next.splice(Math.min(at, next.length), 0, before)
        return next
      })
    }
  }

  const urlFor = (d: Display) => `${location.origin}/display/${d.token}`
  // The format that matches the screen. An e-ink panel driven by a
  // microcontroller wants `.bin` — the packed framebuffer, which it writes
  // straight to its glass — and handing it the `.png` instead means asking a
  // board with no decoder to grow a zlib inflater and five PNG unfilters first.
  // A colour panel is something with a browser or an image library, so it gets
  // the PNG. Both suffixes work on every display; this is just the useful one.
  const imageUrlFor = (d: Display) => {
    const size = d.panel_width && d.panel_height
      ? '' : '?w=800&h=480'
    const ext = d.palette === 'eink' ? 'bin' : 'png'
    return `${location.origin}/api/public/display/${d.token}.${ext}${size}`
  }

  const copy = async (token: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(token)
      setTimeout(() => setCopied((c) => (c === token ? null : c)), 2000)
    } catch {
      // Clipboard access can be refused (an insecure origin, a permissions
      // policy). The URL is on screen and selectable, so there is nothing to
      // recover — and an error toast about a convenience would be louder than
      // the convenience.
    }
  }

  const setDraft = (token: string, part: Draft) =>
    setDrafts((x) => ({ ...x, [token]: { ...x[token], ...part } }))
  const clearDraft = (token: string) =>
    setDrafts((x) => { const { [token]: _drop, ...rest } = x; return rest })
  /** Escape on a blur-committed field: drop the draft, visibly, and keep the
   *  sheet open. `useEscape` is bound to the window and unmounts the whole
   *  settings panel; a removed element never blurs, so without the propagation
   *  stop a half-typed name or panel size was simply gone. */
  const escapeReverts = (token: string) => (e: React.KeyboardEvent) => {
    if (e.key !== 'Escape') return
    e.preventDefault(); e.stopPropagation(); clearDraft(token)
  }

  const toggleId = (current: string[], id: string): string[] =>
    current.includes(id) ? current.filter((x) => x !== id) : [...current, id]

  /** What an allowlist should be WRITTEN as, given the set it now holds.
   *
   *  Collapse to `[]` — which the backend reads as "everything", so a display
   *  made in March shows a calendar made in April — only when the set really
   *  does cover everything on offer. It used to collapse whenever the LENGTHS
   *  matched, which is not the same claim: an allowlist carrying an id that is
   *  no longer on offer (a deleted calendar, or one since archived) could match
   *  the length while excluding a calendar the owner had turned off, and the
   *  click then turned every excluded calendar back on. On an unauthenticated
   *  display URL that is a widening, and the chip stayed lit as if nothing had
   *  happened. */
  const asAllowlist = (next: string[], all: string[]): string[] =>
    all.every((id) => next.includes(id)) ? [] : next

  /** The ids a display is actually drawing right now. `[]` means everything. */
  const effective = (chosen: string[], all: string[]): string[] =>
    chosen.length === 0 ? all : chosen

  if (!loaded) return <div className="empty">{tr('disp.loading')}</div>
  if (failed) return <div className="empty" role="alert">{tr('disp.loadFailed')}</div>

  return (
    <>
      {rows.length === 0 ? (
        <div className="empty">{tr('disp.none')}</div>
      ) : (
        <div className="disp-list">
          {rows.map((d) => (
            <div key={d.token} className="disp">
              <div className="disp-main">
                <div className="disp-name">{d.name}</div>
                <div className="disp-meta">
                  <span className="chip">{tr(`disp.mode.${d.mode}`)}</span>
                  <span className="chip">{tr(`disp.palette.${d.palette}`)}</span>
                  {!d.enabled ? <span className="chip">{tr('disp.off')}</span> : null}
                  <span className="mono">
                    {d.last_seen_at
                      ? tr('disp.lastSeen', { when: fmtWhen(d.last_seen_at, tf, locale) })
                      : tr('disp.neverSeen')}
                  </span>
                </div>
              </div>
              <button className="btn ghost"
                onClick={() => setOpen((o) => (o === d.token ? null : d.token))}
                aria-expanded={open === d.token}>
                {open === d.token ? tr('disp.done') : tr('disp.setUp')}
              </button>

              {open === d.token ? (
                <div className="disp-editor">
                  <div className="menu-row">
                    <label htmlFor={`disp-name-${d.token}`}>{tr('disp.name')}</label>
                    <input id={`disp-name-${d.token}`} className="input"
                      value={drafts[d.token]?.name ?? d.name}
                      maxLength={100}
                      onChange={(e) => setDraft(d.token, { name: e.target.value })}
                      onBlur={(e) => {
                        const next = e.target.value.trim()
                        // An empty name is refused, and REVERTING is the half
                        // that was missing: without it the field and the list
                        // row both went on showing nothing while the server
                        // still held the old name, so the owner was left
                        // believing they had wiped the label that is drawn on
                        // the panel itself.
                        if (!next || next === d.name) return clearDraft(d.token)
                        void patch(d.token, { name: next })
                      }}
                      onKeyDown={escapeReverts(d.token)} />
                  </div>

                  <div className="menu-row">
                    <label>{tr('disp.mode')}</label>
                    <button className="menu-toggle"
                      onClick={() => {
                        // Cycled, exactly as rotation and the refresh interval
                        // are cycled two rows below — one `.menu-toggle`
                        // showing the current value. A mode this build does not
                        // know (an older row, an API write) is not a missing
                        // catalogue key here: `indexOf` returns -1 and the next
                        // press lands on the first mode, which is the same
                        // recovery the refresh button already offers.
                        const i = DISPLAY_MODES.indexOf(d.mode)
                        void patch(d.token,
                          { mode: DISPLAY_MODES[(i + 1) % DISPLAY_MODES.length] })
                      }}>
                      {tr(`disp.mode.${d.mode}`)}
                    </button>
                  </div>

                  {d.mode === 'now' ? (
                    <div className="hintline">{tr('disp.modeNowHint')}</div>
                  ) : null}

                  <div className="menu-row">
                    <label>{tr('disp.palette')}</label>
                    <button className="menu-toggle"
                      onClick={() => void patch(d.token,
                        { palette: d.palette === 'color' ? 'eink' : 'color' })}>
                      {tr(`disp.palette.${d.palette}`)}
                    </button>
                  </div>
                  <div className="hintline">{tr('disp.paletteHint')}</div>

                  <div className="menu-row">
                    <label>{tr('disp.refresh')}</label>
                    <button className="menu-toggle"
                      onClick={() => {
                        const choices: readonly number[] = REFRESH_CHOICES[d.palette]
                        const i = choices.indexOf(d.refresh_seconds)
                        // `indexOf` of a value not in the list is -1, so the
                        // next one is choices[0] — which is what should happen
                        // to a display carrying an interval the API set.
                        const next = choices[(i + 1) % choices.length]
                        void patch(d.token, { refresh_seconds: next })
                      }}>
                      {/* A value outside the four choices can only come from
                          the API, and it is shown as a plain number of seconds
                          rather than as a missing catalogue key. */}
                      {(REFRESH_CHOICES[d.palette] as readonly number[])
                        .includes(d.refresh_seconds)
                        ? tr(`disp.refresh.${d.refresh_seconds}`)
                        : tr('disp.refresh.seconds', { n: d.refresh_seconds })}
                    </button>
                  </div>
                  {d.palette === 'eink' ? (
                    <div className="hintline">{tr('disp.refreshEinkHint')}</div>
                  ) : null}

                  {d.mode === 'habits' ? (
                    <>
                      <div className="menu-row">
                        <label>{tr('disp.hideDoneHabits')}</label>
                        <button className="menu-toggle"
                          onClick={() => void patch(d.token,
                            { hide_done_habits: !d.hide_done_habits })}>
                          {tr(d.hide_done_habits ? 'disp.on' : 'disp.off')}
                        </button>
                      </div>
                      <div className="hintline">{tr('disp.hideDoneHabitsHint')}</div>
                      <div className="menu-row">
                        <label>{tr('disp.hideDoneTasks')}</label>
                        <button className="menu-toggle"
                          onClick={() => void patch(d.token,
                            { hide_done_tasks: !d.hide_done_tasks })}>
                          {tr(d.hide_done_tasks ? 'disp.on' : 'disp.off')}
                        </button>
                      </div>
                    </>
                  ) : null}

                  {/* The allowlists. Empty means everything — a display made in
                      March should show a calendar made in April without being
                      edited, which is the same default `hidden_calendars` takes. */}
                  <div className="menu-head">
                    {tr(d.mode === 'calendar' ? 'disp.whichCalendars' : 'disp.whichLists')}
                  </div>
                  <div className="disp-picks">
                    {(d.mode === 'calendar' ? cals : lists).map((c) => {
                      const all = (d.mode === 'calendar' ? cals : lists).map((x) => x.id)
                      const chosen = d.mode === 'calendar' ? d.calendars : d.lists
                      // An empty allowlist means "everything", so the first
                      // click has to materialize the full set before removing
                      // one — otherwise turning one calendar off would turn
                      // every other one off too.
                      const now = effective(chosen, all)
                      const on = now.includes(c.id)
                      // The LAST one on cannot be turned off. An emptied
                      // allowlist is indistinguishable from an unset one, so
                      // writing it would mean "everything" — the click would do
                      // the exact opposite of what it says, and light every
                      // chip the owner had just finished turning off.
                      const last = on && now.length === 1
                      return (
                        <button key={c.id}
                          className={`chip${on ? ' is-on' : ''}`}
                          aria-pressed={on}
                          disabled={last}
                          title={last ? tr('disp.needOneSource') : undefined}
                          onClick={() => {
                            if (last) return
                            const next = asAllowlist(toggleId(now, c.id), all)
                            void patch(d.token, d.mode === 'calendar'
                              ? { calendars: next } : { lists: next })
                          }}>
                          {c.name}
                        </button>
                      )
                    })}
                  </div>

                  <div className="menu-head">{tr('disp.url')}</div>
                  <div className="disp-url">
                    <code className="mono">{urlFor(d)}</code>
                    <button className="btn ghost" onClick={() => void copy(d.token, urlFor(d))}>
                      {copied === d.token ? tr('disp.copied') : tr('disp.copy')}
                    </button>
                  </div>
                  <div className="hintline">{tr('disp.urlHint')}</div>

                  <div className="menu-head">{tr('disp.panel')}</div>
                  <div className="hintline">{tr('disp.panelHint')}</div>
                  {/* Held locally and written on BLUR, not on every keystroke.
                      Typing "800" passes through 8 and 80 on the way, and the
                      server floors a panel at 100 — so a per-keystroke PATCH
                      422'd twice and rolled the field back under the cursor,
                      making the number literally untypeable. The name field
                      above takes the same shape for the same reason. */}
                  <div className="menu-row">
                    <label htmlFor={`disp-w-${d.token}`}>{tr('disp.panelSize')}</label>
                    <span className="disp-size">
                      <input id={`disp-w-${d.token}`} className="input" type="number"
                        min={0} max={4096} placeholder="800"
                        aria-label={tr('disp.panelWidth')}
                        value={drafts[d.token]?.panel_width ?? (d.panel_width ?? '')}
                        onChange={(e) => setDraft(d.token, { panel_width: e.target.value })}
                        onBlur={(e) => void patch(d.token,
                          { panel_width: Number(e.target.value) || 0 })}
                        onKeyDown={escapeReverts(d.token)} />
                      <span aria-hidden="true">×</span>
                      {/* Its own accessible name. The width field borrows the
                          "Panel size" label through `htmlFor`; this one had
                          nothing, so a screen reader announced "spin button" on
                          the field that decides the byte width of the buffer a
                          panel paints. */}
                      <input className="input" type="number"
                        min={0} max={4096} placeholder="480"
                        aria-label={tr('disp.panelHeight')}
                        value={drafts[d.token]?.panel_height ?? (d.panel_height ?? '')}
                        onChange={(e) => setDraft(d.token, { panel_height: e.target.value })}
                        onBlur={(e) => void patch(d.token,
                          { panel_height: Number(e.target.value) || 0 })}
                        onKeyDown={escapeReverts(d.token)} />
                    </span>
                  </div>
                  {d.panel_too_small ? (
                    // Said HERE, beside the size that caused it, at the moment
                    // it is typed. The panel itself says the same thing when it
                    // renders, but finding out there means walking to the other
                    // room to read it.
                    <div className="hintline" role="alert">{tr('disp.panelTooSmall')}</div>
                  ) : null}
                  <div className="menu-row">
                    <label>{tr('disp.rotation')}</label>
                    <button className="menu-toggle"
                      onClick={() => {
                        const i = ROTATIONS.indexOf(d.rotation)
                        void patch(d.token, { rotation: ROTATIONS[(i + 1) % ROTATIONS.length] })
                      }}>
                      {d.rotation}°
                    </button>
                  </div>
                  <div className="disp-url">
                    <code className="mono">{imageUrlFor(d)}</code>
                    <button className="btn ghost"
                      onClick={() => void copy(`${d.token}-img`, imageUrlFor(d))}>
                      {copied === `${d.token}-img` ? tr('disp.copied') : tr('disp.copy')}
                    </button>
                  </div>
                  <div className="hintline">{tr('disp.imageHint')}</div>

                  <div className="menu-row">
                    <label>{tr('disp.enabled')}</label>
                    <button className="menu-toggle"
                      onClick={() => void patch(d.token, { enabled: !d.enabled })}>
                      {tr(d.enabled ? 'disp.on' : 'disp.off')}
                    </button>
                  </div>
                  <div className="hintline">{tr('disp.enabledHint')}</div>

                  <div className="menu-actions">
                    <button className="btn ghost" onClick={() => void rotate(d.token)}>
                      {tr('disp.rotateToken')}
                    </button>
                    {confirming === d.token ? (
                      <>
                        <button className="btn ghost" onClick={() => setConfirming(null)}>
                          {tr('disp.keep')}
                        </button>
                        <button className="btn danger" onClick={() => void remove(d.token)}>
                          {tr('disp.deleteConfirm')}
                        </button>
                      </>
                    ) : (
                      <button className="btn danger" onClick={() => setConfirming(d.token)}>
                        {tr('disp.delete')}
                      </button>
                    )}
                  </div>
                  <div className="hintline">{tr('disp.rotateHint')}</div>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}

      <div className="menu-head">{tr('disp.add')}</div>
      <div className="disp-add">
        <input className="input" value={name} maxLength={100}
          placeholder={tr('disp.namePlaceholder')}
          aria-label={tr('disp.name')}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void add() }} />
        <button className="btn" onClick={() => void add()} disabled={!name.trim() || adding}>
          {tr('disp.addButton')}
        </button>
      </div>
      <div className="hintline">{tr('disp.hint')}</div>
    </>
  )
}
