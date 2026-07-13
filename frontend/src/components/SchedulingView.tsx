import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { api, type Availability, type Booking, type BookingLink, type BookingLinkInput,
  type List } from '../api'
import { makeGuard } from '../util'

// Owner side of client scheduling: manage booking links (availability, target
// calendar, redacted-busy toggle) and see who booked. The public counterpart
// lives at /book/<token> (BookingPage).

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const DEFAULT_RANGE = '09:00-17:00'

const COMMON_TZS = [
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Anchorage', 'Pacific/Honolulu', 'UTC', 'Europe/London', 'Europe/Paris',
  'Europe/Berlin', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Kolkata', 'Australia/Sydney',
]

const fmtWhen = (iso: string) =>
  new Date(iso).toLocaleString(undefined,
    { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

export function SchedulingView({ rev, onExpire }: { rev: number; onExpire: () => void }) {
  const guard = makeGuard(onExpire)
  const [links, setLinks] = useState<BookingLink[]>([])
  const [cals, setCals] = useState<List[]>([])
  const [bookings, setBookings] = useState<Booking[]>([])
  const [editing, setEditing] = useState<BookingLink | 'new' | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    guard(async () => {
      const [ls, cs, bs] = await Promise.all([
        api.schedulingLinks(), api.calendars(), api.schedulingBookings(),
      ])
      setLinks(ls); setCals(cs); setBookings(bs)
    })
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

  const toggleEnabled = async (l: BookingLink) => {
    const prev = links
    setLinks(links.map((x) => (x.token === l.token ? { ...x, enabled: !l.enabled } : x)))
    const updated = await guard(() => api.patchSchedulingLink(l.token, { enabled: !l.enabled }))
    if (!updated) setLinks(prev)
  }

  const remove = async (l: BookingLink) => {
    const prev = links
    setLinks(links.filter((x) => x.token !== l.token))
    if ((await guard(() => api.deleteSchedulingLink(l.token))) === undefined) setLinks(prev)
  }

  const save = async (body: BookingLinkInput, token?: string) => {
    const saved = await guard(() => token
      ? api.patchSchedulingLink(token, body)
      : api.createSchedulingLink(body))
    if (saved) {
      setLinks((ls) => token ? ls.map((x) => (x.token === token ? saved : x)) : [...ls, saved])
      setEditing(null)
    }
  }

  return (
    <div className="work">
      <div className="content">
        <div className="content-head">
          <span className="content-title">Scheduling</span>
          <span className="spacer" />
          <button className="btn" onClick={() => setEditing('new')}>New link</button>
        </div>
        <div className="scroll">
          {links.length === 0 && (
            <div className="empty" style={{ padding: '18px 26px' }}>
              Create a booking link, share it with a client, and their pick lands
              on your calendar.
            </div>
          )}
          <div className="sched-list">
            {links.map((l) => (
              <div key={l.token} className={`sched-card ${l.enabled ? '' : 'off'}`}>
                <div className="sched-card-head">
                  <span className="sched-card-title">{l.title}</span>
                  <label className="sched-toggle" title={l.enabled ? 'Link is live' : 'Link is off'}>
                    <input type="checkbox" checked={l.enabled} onChange={() => toggleEnabled(l)} />
                    <span>{l.enabled ? 'Live' : 'Off'}</span>
                  </label>
                </div>
                <div className="sched-card-meta">
                  {l.duration_minutes} min · {l.calendar_name || l.calendar} · {l.timezone}
                  {l.show_busy ? ' · shows busy times' : ''}
                </div>
                <div className="sched-card-meta">
                  {l.booking_count} booking{l.booking_count === 1 ? '' : 's'} ·{' '}
                  <span className="mono">/book/{l.token}</span>
                </div>
                <div className="sched-card-actions">
                  <button className="btn ghost" onClick={() => copyLink(l)}>
                    {copied === l.token ? 'Copied ✓' : 'Copy link'}
                  </button>
                  <button className="btn ghost" onClick={() => setEditing(l)}>Edit</button>
                </div>
              </div>
            ))}
          </div>

          <div className="section-label label" style={{ padding: '22px 26px 4px' }}>
            Upcoming bookings
          </div>
          {upcoming.length === 0 && (
            <div className="empty" style={{ padding: '8px 26px' }}>Nothing booked yet.</div>
          )}
          <div className="sched-bookings">
            {upcoming.map((b) => (
              <div key={b.id} className="sched-booking">
                <span className="when mono">{fmtWhen(b.start)}</span>
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
  WEEKDAYS.map((_, i) => {
    const ranges = (av[String(i)] ?? []).map((r) => r.split('-') as [string, string])
    return { on: ranges.length > 0, ranges: ranges.length ? ranges : [DEFAULT_RANGE.split('-') as [string, string]] }
  })

const daysToAvail = (days: DayRanges[]): Availability => {
  const av: Availability = {}
  days.forEach((d, i) => {
    if (!d.on) return
    const rs = d.ranges.filter(([s, e]) => s && e && s < e).map(([s, e]) => `${s}-${e}`)
    if (rs.length) av[String(i)] = rs
  })
  return av
}

function LinkModal({ link, cals, onClose, onSave, onDelete }: {
  link: BookingLink | null
  cals: List[]
  onClose: () => void
  onSave: (body: BookingLinkInput, token?: string) => void
  onDelete: (l: BookingLink) => void
}) {
  const [title, setTitle] = useState(link?.title ?? '')
  const [description, setDescription] = useState(link?.description ?? '')
  const [calendar, setCalendar] = useState(link?.calendar ?? cals[0]?.id ?? '')
  const [duration, setDuration] = useState(link?.duration_minutes ?? 30)
  const [tz, setTz] = useState(
    link?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC')
  const [days, setDays] = useState<DayRanges[]>(() => availToDays(
    link?.availability ?? { '0': [DEFAULT_RANGE], '1': [DEFAULT_RANGE], '2': [DEFAULT_RANGE], '3': [DEFAULT_RANGE], '4': [DEFAULT_RANGE] }))
  const [showBusy, setShowBusy] = useState(link?.show_busy ?? false)
  const [buffer, setBuffer] = useState(link?.buffer_minutes ?? 0)
  const [notice, setNotice] = useState(link?.min_notice_hours ?? 24)
  const [horizon, setHorizon] = useState(link?.horizon_days ?? 30)
  const [confirming, setConfirming] = useState(false)

  const patchDay = (i: number, d: Partial<DayRanges>) =>
    setDays(days.map((x, j) => (j === i ? { ...x, ...d } : x)))

  const patchRange = (i: number, r: number, pos: 0 | 1, v: string) =>
    patchDay(i, {
      ranges: days[i].ranges.map((x, k) =>
        (k === r ? (pos === 0 ? [v, x[1]] : [x[0], v]) : x) as [string, string]),
    })

  const valid = title.trim() && calendar && tz.trim()
    && Object.keys(daysToAvail(days)).length > 0

  const save = () => {
    if (!valid) return
    onSave({
      title: title.trim(),
      description: description.trim() || null,
      calendar,
      duration_minutes: duration,
      timezone: tz.trim(),
      availability: daysToAvail(days),
      show_busy: showBusy,
      buffer_minutes: buffer,
      min_notice_hours: notice,
      horizon_days: horizon,
    }, link?.token)
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal sched-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{link ? 'Edit booking link' : 'New booking link'}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="field">
          <label className="label">Title</label>
          <input className="input" autoFocus value={title} maxLength={200}
            placeholder="30-minute intro call"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') save() }} />
        </div>
        <div className="field">
          <label className="label">Description (shown to clients)</label>
          <textarea className="input" rows={2} value={description} maxLength={2000}
            onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="field-row">
          <div className="field">
            <label className="label">Calendar</label>
            <select className="input" value={calendar} onChange={(e) => setCalendar(e.target.value)}>
              {cals.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="label">Duration (min)</label>
            <input className="input" type="number" min={5} max={480} step={5} value={duration}
              onChange={(e) => setDuration(Math.max(5, Math.min(480, Number(e.target.value) || 30)))} />
          </div>
        </div>
        <div className="field">
          <label className="label">Timezone (your availability is in this zone)</label>
          <input className="input" list="sched-tzs" value={tz} onChange={(e) => setTz(e.target.value)} />
          <datalist id="sched-tzs">
            {COMMON_TZS.map((z) => <option key={z} value={z} />)}
          </datalist>
        </div>
        <div className="field">
          <label className="label">Weekly availability</label>
          <div className="sched-week">
            {WEEKDAYS.map((name, i) => (
              <div key={name} className={`sched-day ${days[i].on ? '' : 'off'}`}>
                <label className="sched-day-name">
                  <input type="checkbox" checked={days[i].on}
                    onChange={(e) => patchDay(i, { on: e.target.checked })} />
                  <span>{name.slice(0, 3)}</span>
                </label>
                {days[i].on ? (
                  <div className="sched-ranges">
                    {days[i].ranges.map((r, k) => (
                      <span key={k} className="sched-range">
                        <input className="input" type="time" value={r[0]}
                          onChange={(e) => patchRange(i, k, 0, e.target.value)} />
                        –
                        <input className="input" type="time" value={r[1]}
                          onChange={(e) => patchRange(i, k, 1, e.target.value)} />
                        {days[i].ranges.length > 1 && (
                          <button className="icon-btn" title="Remove range"
                            onClick={() => patchDay(i, { ranges: days[i].ranges.filter((_, j) => j !== k) })}>
                            ✕
                          </button>
                        )}
                      </span>
                    ))}
                    <button className="sched-add-range" title="Add another range"
                      onClick={() => patchDay(i, { ranges: [...days[i].ranges, ['', '']] })}>
                      + range
                    </button>
                  </div>
                ) : (
                  <span className="sched-unavail">Unavailable</span>
                )}
              </div>
            ))}
          </div>
        </div>
        <div className="field">
          <label className="sched-check">
            <input type="checkbox" checked={showBusy} onChange={(e) => setShowBusy(e.target.checked)} />
            <span>Show my busy times on the booking page</span>
          </label>
          <div className="hintline">
            Clients see unlabeled “Busy” blocks — never event names or details.
            Booked and existing timed events always block slots; all-day events
            (birthdays, trips) don't.
          </div>
        </div>
        <div className="field-row">
          <div className="field">
            <label className="label">Buffer (min)</label>
            <input className="input" type="number" min={0} max={240} step={5} value={buffer}
              onChange={(e) => setBuffer(Math.max(0, Math.min(240, Number(e.target.value) || 0)))} />
          </div>
          <div className="field">
            <label className="label">Min notice (hrs)</label>
            <input className="input" type="number" min={0} max={720} value={notice}
              onChange={(e) => setNotice(Math.max(0, Math.min(720, Number(e.target.value) || 0)))} />
          </div>
          <div className="field">
            <label className="label">Days ahead</label>
            <input className="input" type="number" min={1} max={180} value={horizon}
              onChange={(e) => setHorizon(Math.max(1, Math.min(180, Number(e.target.value) || 30)))} />
          </div>
        </div>
        <div className="modal-actions">
          {link && (
            <button className={`btn ghost ${confirming ? 'danger' : ''}`}
              onClick={() => (confirming ? onDelete(link) : setConfirming(true))}>
              {confirming ? 'Really delete?' : 'Delete'}
            </button>
          )}
          <span className="spacer" />
          <button className="btn" disabled={!valid} onClick={save}>
            {link ? 'Save' : 'Create link'}
          </button>
        </div>
      </div>
    </div>
  )
}
