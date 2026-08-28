import { useEffect, useMemo, useState, type KeyboardEvent, useRef } from 'react'
import { api, type Availability, type Booking, type BookingLink, type BookingLinkInput,
  type List } from '../api'
import { makeGuard } from '../util'
import { fmtWhen, inputLang } from '../time'
import { useTimeFormat } from '../timeformat'
import { useEscape } from '../hooks'
import { DateTimeInput } from './DateTimeInput'
import { useI18n } from '../i18n'
import { weekdayNames } from '../names'

// Owner side of client scheduling: manage booking links (availability, target
// calendar, redacted-busy toggle) and see who booked. The public counterpart
// lives at /book/<token> (BookingPage).

// The availability map's keys are "0".."6", Monday-first — `parse_availability`
// in backend/tasksd/scheduling.py. The NAMES for those seven slots are not
// spelled here any more: they come from `weekdayNames`, which reads them out of
// the platform in whatever language the app is set to.
const DAYS_IN_WEEK = 7
const DEFAULT_RANGE = '09:00-17:00'

const COMMON_TZS = [
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Anchorage', 'Pacific/Honolulu', 'UTC', 'Europe/London', 'Europe/Paris',
  'Europe/Berlin', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Kolkata', 'Australia/Sydney',
]

/** A typed number field's value, bounded. The fields hold a STRING while they
 *  are being edited (see the Duration input), so every reader of one has to
 *  agree on how an empty or half-typed value resolves. */
function clamp(raw: string, lo: number, hi: number, fallback: number): number {
  const n = Number(raw)
  if (raw.trim() === '' || !Number.isFinite(n)) return fallback
  return Math.max(lo, Math.min(hi, n))
}

export function SchedulingView({ rev, onExpire }: { rev: number; onExpire: () => void }) {
  const guard = makeGuard(onExpire)
  const tf = useTimeFormat()
  const { locale, t: tr } = useI18n()
  const [links, setLinks] = useState<BookingLink[]>([])
  const [cals, setCals] = useState<List[]>([])
  const [bookings, setBookings] = useState<Booking[]>([])
  const [editing, setEditing] = useState<BookingLink | 'new' | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)

  // `makeGuard` swallows every non-401 failure and RESOLVES undefined, so none
  // of the setState calls below used to run and `links`/`bookings` stayed at
  // their initial `[]` — which this view renders as its empty copy. A 502, a 429
  // or a timeout therefore told the owner, in prose, that they had never created
  // a booking link and that nothing was booked, with no error and no retry.
  // ArchivedCalendarsSection carries this exact flag for the same reason, and
  // its comment says why: an empty state over a failed fetch is a confident lie
  // about the account.
  useEffect(() => {
    let alive = true
    setFailed(false)
    guard(async () => {
      const [ls, cs, bs] = await Promise.all([
        api.schedulingLinks(), api.calendars(), api.schedulingBookings(),
      ])
      return { ls, cs, bs }
    }).then((r) => {
      if (!alive) return
      if (r) { setLinks(r.ls); setCals(r.cs); setBookings(r.bs) }
      else setFailed(true)
      setLoaded(true)
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev])

  const upcoming = useMemo(() => {
    const now = Date.now()
    return bookings.filter((b) => new Date(b.end).getTime() >= now)
  }, [bookings])

  const copyLink = async (l: BookingLink) => {
    try {
      await navigator.clipboard.writeText(`${location.origin}/book/${l.token}`)
      setCopied(l.token)
      setTimeout(() => setCopied((c) => (c === l.token ? null : c)), 1600)
    } catch {
      /* clipboard unavailable (http, permissions) — the URL is still visible */
    }
  }

  // Both writes below roll back ONLY the row that failed, functionally — never a
  // whole-array snapshot. `data.tsx` carries this lesson twice, at `patchLocal`
  // and at the reorder: "restore only the affected task — never a whole-array
  // snapshot, which would clobber interleaved changes to other tasks". Here the
  // interleaved change is another link's toggle, and the array captured at
  // render holds it in its OLD state. Rolling that back left the owner looking
  // at a link marked Live that the server had switched off — and "fixing" it by
  // tapping the toggle turns it back on, publishing a URL they had disabled.
  //
  // Functional, not just narrow: `links` inside these closures is the value from
  // the render the tap came from, so two writes in flight would each compute
  // their `map` over a stale array and the later setState would win outright.

  const toggleEnabled = async (l: BookingLink) => {
    setLinks((ls) => ls.map((x) => (x.token === l.token ? { ...x, enabled: !l.enabled } : x)))
    const updated = await guard(() => api.patchSchedulingLink(l.token, { enabled: !l.enabled }))
    // Only the FIELD this write touched is restored, not the whole row `l`: an
    // edit to the same link can land while the toggle is in flight (the editor
    // replaces the row with the server's DTO), and putting `l` back wholesale
    // reverts that title the same way the array snapshot reverted the other
    // link. `l.enabled` is the value from before the tap, not a negation of
    // whatever is there now, so a second failure cannot leave it flipped.
    if (!updated) {
      setLinks((ls) => ls.map((x) => (x.token === l.token ? { ...x, enabled: l.enabled } : x)))
    }
  }

  const remove = async (l: BookingLink) => {
    // Its position is remembered rather than the array, so a failed delete puts
    // one link back where it was instead of resurrecting links deleted since.
    const at = links.findIndex((x) => x.token === l.token)
    setLinks((ls) => ls.filter((x) => x.token !== l.token))
    if ((await guard(() => api.deleteSchedulingLink(l.token))) === undefined) {
      setLinks((ls) => {
        if (ls.some((x) => x.token === l.token)) return ls   // a refetch beat us to it
        const back = [...ls]
        back.splice(Math.min(at < 0 ? back.length : at, back.length), 0, l)
        return back
      })
    }
  }

  /** Whether the write landed — the modal needs it to clear its in-flight guard.
   *
   *  Typed `=> void` before, so the modal set `saving` and could never observe
   *  the outcome: `guard` swallows the failure, the modal is deliberately left
   *  open so the user can fix and retry, and `disabled={!valid || saving}` then
   *  kept Create dead forever. The only way out was Escape, which discards the
   *  whole seven-day grid they had just filled in. */
  const save = async (body: BookingLinkInput, token?: string): Promise<boolean> => {
    const saved = await guard(() => token
      ? api.patchSchedulingLink(token, body)
      : api.createSchedulingLink(body))
    if (!saved) return false
    setLinks((ls) => token ? ls.map((x) => (x.token === token ? saved : x)) : [...ls, saved])
    setEditing(null)
    return true
  }

  return (
    <div className="work">
      <div className="content">
        <div className="content-head">
          <span className="content-title">{tr('sched.title')}</span>
          <span className="spacer" />
          <button className="btn" onClick={() => setEditing('new')}>{tr('sched.newLink')}</button>
        </div>
        <div className="scroll">
          {!loaded ? (
            <div className="empty" style={{ padding: '18px 26px' }}>{tr('common.loading')}</div>
          ) : failed ? (
            <div className="empty" style={{ padding: '18px 26px' }} role="alert">
              {tr('sched.loadFailed')}
            </div>
          ) : links.length === 0 ? (
            <div className="empty" style={{ padding: '18px 26px' }}>
              {tr('sched.empty')}
            </div>
          ) : null}
          <div className="sched-list">
            {links.map((l) => (
              <div key={l.token} className={`sched-card ${l.enabled ? '' : 'off'}`}>
                <div className="sched-card-head">
                  <span className="sched-card-title">{l.title}</span>
                  {/* A link whose calendar is gone was disabled server-side and
                      cannot be switched back on until it is repointed, so the
                      toggle says why rather than sitting there inert. */}
                  <label className="sched-toggle"
                    title={l.calendar_missing
                      ? tr('sched.calendarGone')
                      : l.enabled ? tr('sched.linkLive') : tr('sched.linkOff')}>
                    <input type="checkbox" checked={l.enabled} disabled={l.calendar_missing}
                      onChange={() => toggleEnabled(l)} />
                    <span>
                      {l.calendar_missing
                        ? tr('sched.noCalendar') : l.enabled ? tr('sched.live') : tr('sched.off')}
                    </span>
                  </label>
                </div>
                <div className="sched-card-meta">
                  {tr('sched.minutes', { n: l.duration_minutes })} ·{' '}
                  {l.calendar_missing
                    ? <span className="warn">{tr('sched.calendarDeleted')}</span>
                    : (l.calendar_name || l.calendar)} · {l.timezone}
                  {l.show_busy ? tr('sched.showsBusy') : ''}
                </div>
                <div className="sched-card-meta">
                  {tr('sched.bookingCount', { count: l.booking_count })} ·{' '}
                  <span className="mono">/book/{l.token}</span>
                </div>
                <div className="sched-card-actions">
                  <button className="btn ghost" onClick={() => copyLink(l)}>
                    {copied === l.token ? tr('sched.copied') : tr('sched.copyLink')}
                  </button>
                  <button className="btn ghost" onClick={() => setEditing(l)}>{tr('common.edit')}</button>
                </div>
              </div>
            ))}
          </div>

          <div className="section-label label" style={{ padding: '22px 26px 4px' }}>
            {tr('sched.upcoming')}
          </div>
          {loaded && !failed && upcoming.length === 0 && (
            <div className="empty" style={{ padding: '8px 26px' }}>{tr('sched.nothingBooked')}</div>
          )}
          <div className="sched-bookings">
            {upcoming.map((b) => (
              <div key={b.id} className="sched-booking">
                <span className="when mono">{fmtWhen(b.start, tf, locale)}</span>
                <span className="who">
                  {b.name} <span className="email">{b.email}</span>
                </span>
                <span className="via">{b.link_title || b.link}</span>
                {b.notes && <span className="notes">{b.notes}</span>}
              </div>
            ))}
          </div>
        </div>
      </div>
      {editing && (
        <LinkModal
          link={editing === 'new' ? null : editing}
          cals={cals.filter((c) => c.is_calendar)}
          onClose={() => setEditing(null)}
          onSave={save}
          onDelete={(l) => { setEditing(null); remove(l) }}
        />
      )}
    </div>
  )
}

// ── create/edit modal ────────────────────────────────────────────────────────

interface DayRanges { on: boolean; ranges: [string, string][] }

const availToDays = (av: Availability): DayRanges[] =>
  Array.from({ length: DAYS_IN_WEEK }, (_, i) => {
    const ranges = (av[String(i)] ?? []).map((r) => r.split('-') as [string, string])
    return { on: ranges.length > 0, ranges: ranges.length ? ranges : [DEFAULT_RANGE.split('-') as [string, string]] }
  })

/** A wholly-untouched pair — what "+ range" appends and the user never filled
 *  in. Dropped rather than complained about, the way the server omits an empty
 *  day rather than rejecting it. */
const isBlankRange = ([s, e]: [string, string]) => !s && !e

/**
 * Why the server would refuse each day, keyed by weekday index.
 *
 * A mirror of `parse_availability` (backend/tasksd/scheduling.py:60), which is
 * where the rules actually live, and it is deliberately exact:
 *   - both fields filled;
 *   - `s < e` STRICTLY — equal endpoints are illegal there too;
 *   - no overlap once the day's ranges are SORTED, so submission order does not
 *     matter and exactly adjacent ranges (`…-12:00` then `12:00-…`) are LEGAL.
 *     A `<=` here would refuse a lunch break the server accepts.
 *
 * The client used to implement the first rule as a silent FILTER and not the
 * second at all: two ranges on one day were serialized verbatim and came back
 * as a raw 422 the UI had no way to anticipate, while a range typed backwards
 * was dropped without a word — the link then advertised no availability that
 * day, and reopening the editor showed it as "Unavailable" with no record the
 * range had ever been typed.
 */
export function availErrors(days: DayRanges[]): Map<number, string> {
  // Catalogue KEYS, not sentences. This function is a mirror of the server's
  // `parse_availability` and belongs beside it rather than beside a translator;
  // the component that shows a message looks it up. Same call `sessionKey` and
  // `timeFormatKey` make.
  const out = new Map<number, string>()
  days.forEach((d, i) => {
    if (!d.on) return
    const filled = d.ranges.filter((r) => !isBlankRange(r))
    if (filled.some(([s, e]) => !s || !e)) {
      out.set(i, 'sched.err.bothTimes')
      return
    }
    if (filled.some(([s, e]) => s >= e)) {
      out.set(i, 'sched.err.startBeforeEnd')
      return
    }
    const sorted = [...filled].sort((a, b) => a[0].localeCompare(b[0]))
    if (sorted.some((r, k) => k > 0 && r[0] < sorted[k - 1][1])) {
      out.set(i, 'sched.err.overlap')
    }
  })
  return out
}

const daysToAvail = (days: DayRanges[]): Availability => {
  const av: Availability = {}
  days.forEach((d, i) => {
    if (!d.on) return
    // Only the untouched "+ range" placeholder is dropped. Everything else is
    // the user's, and `availErrors` decides whether it may be submitted —
    // filtering here is what silently discarded an inverted range.
    const rs = d.ranges.filter((r) => !isBlankRange(r)).map(([s, e]) => `${s}-${e}`)
    if (rs.length) av[String(i)] = rs
  })
  return av
}

function LinkModal({ link, cals, onClose, onSave, onDelete }: {
  link: BookingLink | null
  cals: List[]
  onClose: () => void
  onSave: (body: BookingLinkInput, token?: string) => Promise<boolean>
  onDelete: (l: BookingLink) => void
}) {
  const { lang: appLang, locale, t: tr } = useI18n()
  const lang = inputLang(useTimeFormat(), appLang)
  const modalTitle = link ? tr('sched.editLink') : tr('sched.newLinkTitle')
  const [title, setTitle] = useState(link?.title ?? '')
  const [description, setDescription] = useState(link?.description ?? '')
  const [calendar, setCalendar] = useState(link?.calendar ?? cals[0]?.id ?? '')
  // Held as a STRING while the user types — see the Duration input for why.
  const [duration, setDuration] = useState(String(link?.duration_minutes ?? 30))
  const [tz, setTz] = useState(
    link?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC')
  const [days, setDays] = useState<DayRanges[]>(() => availToDays(
    link?.availability ?? { '0': [DEFAULT_RANGE], '1': [DEFAULT_RANGE], '2': [DEFAULT_RANGE], '3': [DEFAULT_RANGE], '4': [DEFAULT_RANGE] }))
  const [showBusy, setShowBusy] = useState(link?.show_busy ?? false)
  const [buffer, setBuffer] = useState(String(link?.buffer_minutes ?? 0))
  const [notice, setNotice] = useState(String(link?.min_notice_hours ?? 24))
  const [horizon, setHorizon] = useState(String(link?.horizon_days ?? 30))
  const [confirming, setConfirming] = useState(false)

  const patchDay = (i: number, d: Partial<DayRanges>) =>
    setDays(days.map((x, j) => (j === i ? { ...x, ...d } : x)))

  const patchRange = (i: number, r: number, pos: 0 | 1, v: string) =>
    patchDay(i, {
      ranges: days[i].ranges.map((x, k) =>
        (k === r ? (pos === 0 ? [v, x[1]] : [x[0], v]) : x) as [string, string]),
    })

  const scrimPress = useRef(false)          // see the overlay below

  const dayErrors = availErrors(days)
  const noDays = Object.keys(daysToAvail(days)).length === 0
  const valid = title.trim() && calendar && tz.trim() && !noDays && dayErrors.size === 0

  // Why the button is dead, when it is dead for a reason nothing on screen shows.
  // `dayErrors` renders a message per malformed RANGE, so a bad time gets an
  // explanation — but turning every day off produced no error at all: Create/Save
  // simply stayed disabled forever with the form looking complete. It is easy to
  // arrive at, because clearing the shipped Mon-Fri defaults is the first thing
  // someone does when their week is not Mon-Fri.
  const blockedBecause = !title.trim() ? tr('sched.err.title')
    : !calendar ? tr('sched.err.calendar')
    : !tz.trim() ? tr('sched.err.tz')
    : noDays ? tr('sched.err.noDays')
    : dayErrors.size ? tr('sched.err.ranges')
    : null

  // `valid` bounds validity, not flight. Without this a double-click — or a
  // second Enter in any field, which also calls save() — published TWO live
  // booking links with two public URLs, one of which nobody knows exists.
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!valid || saving) return
    setSaving(true)
    // Cleared on FAILURE only. A `finally` would set state on a modal the
    // success path has already unmounted, and — worse — it invites `save` to
    // return true unconditionally, which puts the button back while leaving the
    // editor exactly as broken as before.
    const ok = await onSave({
      title: title.trim(),
      description: description.trim() || null,
      calendar,
      // Clamped HERE as well as on blur: Enter submits without ever firing a
      // blur, so the wire value must not depend on the field having been left.
      duration_minutes: clamp(duration, 5, 480, 30),
      timezone: tz.trim(),
      availability: daysToAvail(days),
      show_busy: showBusy,
      buffer_minutes: clamp(buffer, 0, 240, 0),
      min_notice_hours: clamp(notice, 0, 720, 0),
      horizon_days: clamp(horizon, 1, 180, 30),
    }, link?.token)
    if (!ok) setSaving(false)
  }

  // The modal contract every other dialog here keeps (see TabsModal): Escape
  // closes it, and a screen reader is told it is a dialog rather than a div.
  useEscape(onClose)

  return (
    /* Escape and role="dialog" landed when this was last fixed; the SCRIM did
       not, so the app's longest form still discarded itself when a drag-select
       released outside it. See TaskModal for why a bare onClick is not enough. */
    <div className="overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal sched-modal" role="dialog" aria-modal="true"
        aria-label={modalTitle}
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{modalTitle}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="field">
          <label className="label" htmlFor="sched-title">{tr('sched.titleField')}</label>
          <input className="input" id="sched-title" autoFocus value={title} maxLength={200}
            placeholder={tr('sched.titlePlaceholder')}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') void save() }} />
        </div>
        <div className="field">
          <label className="label" htmlFor="sched-desc">{tr('sched.description')}</label>
          <textarea className="input" id="sched-desc" rows={2} value={description} maxLength={2000}
            onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="field-row">
          <div className="field">
            <label className="label" htmlFor="sched-calendar">{tr('sched.calendarField')}</label>
            <select className="input" id="sched-calendar" value={calendar} onChange={(e) => setCalendar(e.target.value)}>
              {cals.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="label" htmlFor="sched-duration">{tr('sched.duration')}</label>
            {/* Clamped on BLUR, not on change. Clamping the MINIMUM per keystroke
                destroyed the first digit of every two-digit value under 50: type
                `4` and it became `5`, so `45` came out `55` and `15` came out
                `55`. `Number('') || 30` also made the field unclearable, so it
                could not be emptied and retyped. `<input type=number>` has no
                spinner in iOS Safari or Chrome on Android, which left no way at
                all on a phone to set a 15-, 20-, 30- or 45-minute link — the
                four values this feature exists for. The max still clamps on
                change (typing past it is never a step towards a valid value),
                and the element's own min/max keep the browser-level guard. */}
            <input className="input" id="sched-duration" type="number" min={5} max={480}
              step={5} value={duration}
              onChange={(e) => setDuration(e.target.value === '' ? '' : String(Math.min(480, Number(e.target.value) || 0)))}
              onBlur={() => setDuration(String(Math.max(5, Math.min(480, Number(duration) || 30))))} />
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="sched-tz">{tr('sched.timezone')}</label>
          <input className="input" id="sched-tz" list="sched-tzs" value={tz} onChange={(e) => setTz(e.target.value)} />
          <datalist id="sched-tzs">
            {COMMON_TZS.map((z) => <option key={z} value={z} />)}
          </datalist>
        </div>
        <div className="field">
          <label className="label">{tr('sched.weekly')}</label>
          <div className="sched-week">
            {weekdayNames(locale, 'short').map((name, i) => (
              <div key={name} className={`sched-day ${days[i].on ? '' : 'off'}`}>
                <label className="sched-day-name">
                  <input type="checkbox" checked={days[i].on}
                    onChange={(e) => patchDay(i, { on: e.target.checked })} />
                  {/* The platform's own abbreviation, not the first three
                      letters of the long name: German shortens Mittwoch to
                      "Mi.", and slicing would have given "Mit". */}
                  <span>{name}</span>
                </label>
                {days[i].on ? (
                  <div className="sched-ranges" aria-invalid={dayErrors.has(i) || undefined}>
                    {dayErrors.has(i) && (
                      <span className="sched-err" role="alert">{tr(dayErrors.get(i)!)}</span>
                    )}
                    {days[i].ranges.map((r, k) => (
                      <span key={k} className="sched-range">
                        <DateTimeInput className="input" type="time" value={r[0]} lang={lang}
                          onChange={(e) => patchRange(i, k, 0, e.target.value)} />
                        –
                        <DateTimeInput className="input" type="time" value={r[1]} lang={lang}
                          onChange={(e) => patchRange(i, k, 1, e.target.value)} />
                        {days[i].ranges.length > 1 && (
                          <button className="icon-btn" title={tr('sched.removeRange')}
                            onClick={() => patchDay(i, { ranges: days[i].ranges.filter((_, j) => j !== k) })}>
                            ✕
                          </button>
                        )}
                      </span>
                    ))}
                    <button className="sched-add-range" title={tr('sched.addRange')}
                      onClick={() => patchDay(i, { ranges: [...days[i].ranges, ['', '']] })}>
                      {tr('sched.addRangeShort')}
                    </button>
                  </div>
                ) : (
                  <span className="sched-unavail">{tr('sched.unavailable')}</span>
                )}
              </div>
            ))}
          </div>
        </div>
        <div className="field">
          <label className="sched-check">
            <input type="checkbox" checked={showBusy} onChange={(e) => setShowBusy(e.target.checked)} />
            <span>{tr('sched.showBusy')}</span>
          </label>
          <div className="hintline">
            {tr('sched.showBusyHint')}
          </div>
        </div>
        <div className="field-row">
          <div className="field">
            <label className="label" htmlFor="sched-buffer">{tr('sched.buffer')}</label>
            <input className="input" id="sched-buffer" type="number" min={0} max={240}
              step={5} value={buffer}
              onChange={(e) => setBuffer(e.target.value === '' ? '' : String(Math.min(240, Number(e.target.value) || 0)))}
              onBlur={() => setBuffer(String(Math.max(0, Math.min(240, Number(buffer) || 0))))} />
          </div>
          <div className="field">
            <label className="label" htmlFor="sched-notice">{tr('sched.notice')}</label>
            <input className="input" id="sched-notice" type="number" min={0} max={720} value={notice}
              onChange={(e) => setNotice(e.target.value === '' ? '' : String(Math.min(720, Number(e.target.value) || 0)))}
              onBlur={() => setNotice(String(Math.max(0, Math.min(720, Number(notice) || 0))))} />
          </div>
          <div className="field">
            <label className="label" htmlFor="sched-horizon">{tr('sched.horizon')}</label>
            {/* Same shape: `|| 30` made this jump to 30 the moment a leading `0`
                was typed on the way to `7`. */}
            <input className="input" id="sched-horizon" type="number" min={1} max={180} value={horizon}
              onChange={(e) => setHorizon(e.target.value === '' ? '' : String(Math.min(180, Number(e.target.value) || 0)))}
              onBlur={() => setHorizon(String(Math.max(1, Math.min(180, Number(horizon) || 30))))} />
          </div>
        </div>
        <div className="modal-actions">
          {link && (
            <button className={`btn ghost ${confirming ? 'danger' : ''}`}
              onClick={() => (confirming ? onDelete(link) : setConfirming(true))}>
              {confirming ? tr('side.reallyDelete') : tr('common.delete')}
            </button>
          )}
          {blockedBecause && (
            <span className="sched-err" role="status">{blockedBecause}</span>
          )}
          <span className="spacer" />
          <button className="btn" disabled={!valid || saving} onClick={save}>
            {link ? tr('common.save') : tr('sched.createLink')}
          </button>
        </div>
      </div>
    </div>
  )
}
