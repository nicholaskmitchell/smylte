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

import { useEffect, useState } from 'react'
import { api, type Display, type DisplayInput, type List } from '../api'
import { makeGuard } from '../util'
import { fmtWhen } from '../time'
import { useTimeFormat } from '../timeformat'
import { useI18n } from '../i18n'

const REFRESH_CHOICES = [60, 300, 900, 3600] as const
const ROTATIONS = [0, 90, 180, 270] as const

export function DisplaysSection({ onExpire }: { onExpire: () => void }) {
  const { locale, t: tr } = useI18n()
  const guard = makeGuard(onExpire)
  const tf = useTimeFormat()
  const [rows, setRows] = useState<Display[]>([])
  const [cals, setCals] = useState<List[]>([])
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
      if (Array.isArray(c)) setCals(c)
      if (Array.isArray(l)) setLists(l)
      setLoaded(true)
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const add = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    const made = await guard(() => api.createDisplay({ name: trimmed }))
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
  const patch = async (token: string, body: Partial<DisplayInput>) => {
    const prev = rows
    setRows((r) => r.map((d) => (d.token === token ? { ...d, ...body } as Display : d)))
    const saved = await guard(() => api.patchDisplay(token, body))
    if (saved) setRows((r) => r.map((d) => (d.token === token ? saved : d)))
    else setRows(prev)
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
    const prev = rows
    setRows((r) => r.filter((d) => d.token !== token))
    setConfirming(null)
    if (await guard(() => api.deleteDisplay(token)) === undefined) setRows(prev)
  }

  const urlFor = (d: Display) => `${location.origin}/display/${d.token}`
  const imageUrlFor = (d: Display) => {
    const size = d.panel_width && d.panel_height
      ? '' : '?w=800&h=480'
    return `${location.origin}/api/public/display/${d.token}.png${size}`
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

  const toggleId = (current: string[], id: string): string[] =>
    current.includes(id) ? current.filter((x) => x !== id) : [...current, id]

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
                    <input id={`disp-name-${d.token}`} className="input" value={d.name}
                      maxLength={100}
                      onChange={(e) => setRows((r) => r.map((x) =>
                        x.token === d.token ? { ...x, name: e.target.value } : x))}
                      onBlur={(e) => {
                        const next = e.target.value.trim()
                        if (next && next !== d.name) void patch(d.token, { name: next })
                      }} />
                  </div>

                  <div className="menu-row">
                    <label>{tr('disp.mode')}</label>
                    <button className="menu-toggle"
                      onClick={() => void patch(d.token,
                        { mode: d.mode === 'calendar' ? 'habits' : 'calendar' })}>
                      {tr(`disp.mode.${d.mode}`)}
                    </button>
                  </div>

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
                        const i = REFRESH_CHOICES.indexOf(
                          d.refresh_seconds as typeof REFRESH_CHOICES[number])
                        const next = REFRESH_CHOICES[(i + 1) % REFRESH_CHOICES.length]
                        void patch(d.token, { refresh_seconds: next })
                      }}>
                      {/* A value outside the four choices can only come from
                          the API, and it is shown as a plain number of seconds
                          rather than as a missing catalogue key. */}
                      {(REFRESH_CHOICES as readonly number[]).includes(d.refresh_seconds)
                        ? tr(`disp.refresh.${d.refresh_seconds}`)
                        : tr('disp.refresh.seconds', { n: String(d.refresh_seconds) })}
                    </button>
                  </div>

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
                      const chosen = d.mode === 'calendar' ? d.calendars : d.lists
                      const on = chosen.length === 0 || chosen.includes(c.id)
                      return (
                        <button key={c.id}
                          className={`chip${on ? ' is-on' : ''}`}
                          aria-pressed={on}
                          onClick={() => {
                            const all = (d.mode === 'calendar' ? cals : lists).map((x) => x.id)
                            // An empty allowlist means "everything", so the
                            // first click has to materialize the full set
                            // before removing one — otherwise turning one
                            // calendar off would turn every other one off too.
                            const base = chosen.length === 0 ? all : chosen
                            const next = toggleId(base, c.id)
                            void patch(d.token, d.mode === 'calendar'
                              ? { calendars: next.length === all.length ? [] : next }
                              : { lists: next.length === all.length ? [] : next })
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
                        min={0} max={4096} value={d.panel_width ?? ''}
                        placeholder="800"
                        onChange={(e) => setRows((r) => r.map((x) => x.token === d.token
                          ? { ...x, panel_width: e.target.value === '' ? null
                            : Number(e.target.value) } : x))}
                        onBlur={(e) => void patch(d.token,
                          { panel_width: Number(e.target.value) || 0 })} />
                      <span aria-hidden="true">×</span>
                      <input className="input" type="number"
                        min={0} max={4096} value={d.panel_height ?? ''}
                        placeholder="480"
                        onChange={(e) => setRows((r) => r.map((x) => x.token === d.token
                          ? { ...x, panel_height: e.target.value === '' ? null
                            : Number(e.target.value) } : x))}
                        onBlur={(e) => void patch(d.token,
                          { panel_height: Number(e.target.value) || 0 })} />
                    </span>
                  </div>
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
        <button className="btn" onClick={() => void add()} disabled={!name.trim()}>
          {tr('disp.addButton')}
        </button>
      </div>
      <div className="hintline">{tr('disp.hint')}</div>
    </>
  )
}
