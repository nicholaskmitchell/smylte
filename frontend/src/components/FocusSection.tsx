// The focus clock's settings: how long its phases are, what happens when one
// ends, whether a row stops at its estimate unless it says otherwise, and the
// two ways an interval's end reaches the owner.
//
// A section body inside the settings panel, not a dialog of its own — the
// panel column owns the scrolling, the heading and the way out, so this
// renders only its own rows. Controlled the way `CapacitySection` is: the
// value arrives as a prop, changes leave through one callback with a partial,
// and `App.tsx` owns the write.
//
// The lengths are in minutes, typed, and committed on blur or Enter rather
// than on every keystroke — a half-typed "2" on the way to "25" is a
// two-minute interval the server would happily accept. A session freezes the
// lengths it started with, so nothing here moves a phase that is running.

import { useEffect, useState } from 'react'
import { FOCUS_BOUNDS, type FocusSettings } from '../focus'
import { useT } from '../i18n'
import { notifyPermission, requestNotify } from '../notify'

export function FocusSection({ value, onChange }: {
  value: FocusSettings
  onChange: (patch: Partial<FocusSettings>) => void
}) {
  const tr = useT()
  // Re-read after the ask, and on every render otherwise: the browser can
  // change its answer behind the page's back (site settings), and a stale
  // "allowed" beside a switch that will never fire is the one thing this row
  // must not say.
  const [asked, setAsked] = useState(0)
  const perm = notifyPermission()
  void asked
  return (
    <>
      <div className="menu-head">{tr('settings.focus.clock')}</div>
      <MinutesRow id="focus-interval" label={tr('settings.focus.interval')}
        value={value.interval} bounds={FOCUS_BOUNDS.interval}
        unit={tr('settings.focus.minutes')} onCommit={(n) => onChange({ interval: n })} />
      <MinutesRow id="focus-break" label={tr('settings.focus.break')}
        value={value.brk} bounds={FOCUS_BOUNDS.brk}
        unit={tr('settings.focus.minutes')} onCommit={(n) => onChange({ brk: n })} />
      <MinutesRow id="focus-long-break" label={tr('settings.focus.longBreak')}
        value={value.longBrk} bounds={FOCUS_BOUNDS.longBrk}
        unit={tr('settings.focus.minutes')} onCommit={(n) => onChange({ longBrk: n })} />
      <MinutesRow id="focus-long-every" label={tr('settings.focus.longEvery')}
        value={value.longEvery} bounds={FOCUS_BOUNDS.longEvery}
        unit={tr('settings.focus.intervals')} zero={tr('settings.focus.longEvery.never')}
        onCommit={(n) => onChange({ longEvery: n })} />
      <div className="hintline">{tr('settings.focus.clock.hint')}</div>

      <div className="menu-head">{tr('settings.focus.end')}</div>
      <div className="menu-row">
        <label htmlFor="focus-auto">{tr('settings.focus.end')}</label>
        <button className="menu-toggle" id="focus-auto" aria-pressed={value.autoContinue}
          onClick={() => onChange({ autoContinue: !value.autoContinue })}>
          {tr(value.autoContinue ? 'settings.focus.end.roll' : 'settings.focus.end.wait')}
        </button>
      </div>
      <div className="hintline">{tr('settings.focus.end.hint')}</div>

      <div className="menu-row">
        <label htmlFor="focus-cap">{tr('settings.focus.cap')}</label>
        <button className="menu-toggle" id="focus-cap" aria-pressed={value.capDefault}
          onClick={() => onChange({ capDefault: !value.capDefault })}>
          {tr(value.capDefault ? 'settings.focus.cap.capped' : 'settings.focus.cap.open')}
        </button>
      </div>
      <div className="hintline">{tr('settings.focus.cap.hint')}</div>

      <div className="menu-head">{tr('settings.focus.alerts')}</div>
      <div className="menu-row">
        <label htmlFor="focus-chime">{tr('settings.focus.chime')}</label>
        <button className="menu-toggle" id="focus-chime" aria-pressed={value.chime}
          onClick={() => onChange({ chime: !value.chime })}>
          {tr(value.chime ? 'settings.focus.on' : 'settings.focus.off')}
        </button>
      </div>
      <div className="menu-row">
        <label htmlFor="focus-notify">{tr('settings.focus.notify')}</label>
        <button className="menu-toggle" id="focus-notify" aria-pressed={value.notify}
          onClick={() => onChange({ notify: !value.notify })}>
          {tr(value.notify ? 'settings.focus.on' : 'settings.focus.off')}
        </button>
      </div>
      {value.notify && (
        <div className="menu-row">
          {/* The permission is the browser's, not the account's: it is asked
              for here, inside a click, and reported as it stands. */}
          <span className="hintline">
            {perm === 'granted' ? tr('settings.focus.notifyGranted')
              : perm === 'denied' ? tr('settings.focus.notifyDenied')
                : perm === 'unsupported' ? tr('settings.focus.notifyUnsupported')
                  : tr('settings.focus.notify.hint')}
          </span>
          {perm === 'default' && (
            <button className="btn ghost"
              onClick={() => { void requestNotify().then(() => setAsked((n) => n + 1)) }}>
              {tr('settings.focus.notifyAllow')}
            </button>
          )}
        </div>
      )}
    </>
  )
}

/** One length, in whole minutes (or intervals), committed on blur or Enter and
 *  clamped to its bounds the way the server clamps a stored value. */
function MinutesRow({ id, label, value, bounds, unit, zero, onCommit }: {
  id: string
  label: string
  value: number
  bounds: readonly [number, number]
  unit: string
  /** What 0 means, when 0 is allowed ("never"). */
  zero?: string
  onCommit: (next: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => { setDraft(String(value)) }, [value])
  const commit = () => {
    const n = Math.round(Number(draft))
    if (!Number.isFinite(n)) { setDraft(String(value)); return }
    const [lo, hi] = bounds
    const clamped = Math.min(hi, Math.max(lo, n))
    setDraft(String(clamped))
    if (clamped !== value) onCommit(clamped)
  }
  return (
    <div className="menu-row">
      <label htmlFor={id}>{label}</label>
      <span className="focus-set-field">
        <input className="input focus-set-input" id={id} type="number" inputMode="numeric"
          min={bounds[0]} max={bounds[1]} value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit() } }} />
        <span className="hintline">{zero && value === 0 ? zero : unit}</span>
      </span>
    </div>
  )
}
