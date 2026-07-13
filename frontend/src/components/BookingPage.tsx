import { useEffect, useMemo, useState } from 'react'
import { api, AuthError, type PublicBookingInfo, type PublicSlot } from '../api'
import { ymd } from '../util'

// The public client-facing page at /book/<token>. Standalone by design: no
// session, no SSE, no imports from the authed shell. Slot ISO strings carry the
// link timezone's offset, so Date() lands them in the visitor's local time and
// everything renders in THEIR timezone (noted in the header).

type Phase = 'loading' | 'notfound' | 'pick' | 'confirm' | 'done'

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

const fmtDay = (key: string) =>
  new Date(`${key}T00:00`).toLocaleDateString(undefined,
    { weekday: 'long', month: 'long', day: 'numeric' })

const localDay = (iso: string) => ymd(new Date(iso))

export function BookingPage({ token }: { token: string }) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [info, setInfo] = useState<PublicBookingInfo | null>(null)
  const [day, setDay] = useState('')
  const [slot, setSlot] = useState<PublicSlot | null>(null)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [busyNow, setBusyNow] = useState(false)      // submit in flight
  const [error, setError] = useState<string | null>(null)
  const [booked, setBooked] = useState<{ start: string; end: string } | null>(null)

  const load = async (): Promise<PublicBookingInfo | null> => {
    try {
      const i = await api.publicBookingInfo(token)
      setInfo(i)
      setPhase('pick')
      return i
    } catch (e) {
      if (!(e instanceof AuthError)) setPhase('notfound')
      return null
    }
  }

  useEffect(() => { load() /* eslint-disable-line */ }, [token])

  // Slots and (redacted) busy blocks grouped by the visitor's local day.
  const slotsByDay = useMemo(() => {
    const m = new Map<string, PublicSlot[]>()
    for (const s of info?.slots ?? []) {
      const k = localDay(s.start)
      m.set(k, [...(m.get(k) ?? []), s])
    }
    return m
  }, [info])

  const busyByDay = useMemo(() => {
    const m = new Map<string, PublicSlot[]>()
    for (const b of info?.busy ?? []) {
      const k = localDay(b.start)
      m.set(k, [...(m.get(k) ?? []), b])
    }
    return m
  }, [info])

  const days = useMemo(() => [...slotsByDay.keys()].sort(), [slotsByDay])
  const selDay = days.includes(day) ? day : days[0] || ''
  const visitorTz = Intl.DateTimeFormat().resolvedOptions().timeZone

  const submit = async () => {
    if (!slot || busyNow) return
    setBusyNow(true)
    setError(null)
    try {
      const r = await api.publicBook(token, {
        start: slot.start, name: name.trim(), email: email.trim(),
        notes: notes.trim() || undefined,
      })
      setBooked({ start: r.start, end: r.end })
      setPhase('done')
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (/not available/i.test(msg)) {
        // Lost the race — refresh the slot list and let them pick again.
        setError('That time was just taken — please pick another.')
        setSlot(null)
        setPhase('pick')
        await load()
      } else {
        setError(msg)
      }
    } finally {
      setBusyNow(false)
    }
  }

  if (phase === 'loading') return null

  if (phase === 'notfound') {
    return (
      <div className="booking-wrap">
        <div className="booking-card">
          <div className="login-brand">Smylte<span className="dot">.</span></div>
          <p className="booking-lead">This booking link is no longer available.</p>
          <p className="hintline">
            It may have been turned off or removed. Ask the person who sent it
            for a fresh link.
          </p>
        </div>
      </div>
    )
  }

  if (phase === 'done' && info && booked) {
    return (
      <div className="booking-wrap">
        <div className="booking-card">
          <div className="label">Confirmed</div>
          <h1 className="booking-title">{info.title}</h1>
          <p className="booking-lead">
            {new Date(booked.start).toLocaleDateString(undefined,
              { weekday: 'long', month: 'long', day: 'numeric' })}
            {' · '}
            {fmtTime(booked.start)}–{fmtTime(booked.end)}
          </p>
          <p className="hintline">
            You're booked, {name.trim()}. Times shown in {visitorTz}.
          </p>
        </div>
      </div>
    )
  }

  if (!info) return null

  return (
    <div className="booking-wrap">
      <div className="booking-card">
        <div className="label">Book a time</div>
        <h1 className="booking-title">{info.title}</h1>
        {info.description && <p className="booking-desc">{info.description}</p>}
        <div className="booking-meta">
          <span className="chip">{info.duration_minutes} min</span>
          <span className="booking-tz">Times shown in {visitorTz}</span>
        </div>

        {error && <div className="booking-err" role="alert">{error}</div>}

        {days.length === 0 && (
          <p className="booking-lead">No open times right now — check back later.</p>
        )}

        {days.length > 0 && phase === 'pick' && (
          <>
            <div className="booking-days">
              {days.map((d) => (
                <button key={d}
                  className={`booking-day ${d === selDay ? 'active' : ''}`}
                  onClick={() => { setDay(d); setSlot(null) }}>
                  <span className="dow">
                    {new Date(`${d}T00:00`).toLocaleDateString(undefined, { weekday: 'short' })}
                  </span>
                  <span className="dnum">
                    {new Date(`${d}T00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  </span>
                </button>
              ))}
            </div>
            <div className="booking-daytitle">{fmtDay(selDay)}</div>
            {(busyByDay.get(selDay) ?? []).length > 0 && (
              <div className="booking-busy">
                {(busyByDay.get(selDay) ?? []).map((b, i) => (
                  <span key={i} className="busy-chip"
                    title="The host is busy during this time">
                    Busy {fmtTime(b.start)}–{fmtTime(b.end)}
                  </span>
                ))}
              </div>
            )}
            <div className="booking-slots">
              {(slotsByDay.get(selDay) ?? []).map((s) => (
                <button key={s.start} className="slot-btn"
                  onClick={() => { setSlot(s); setPhase('confirm') }}>
                  {fmtTime(s.start)}
                </button>
              ))}
            </div>
          </>
        )}

        {phase === 'confirm' && slot && (
          <>
            <div className="booking-picked">
              <span>
                {fmtDay(localDay(slot.start))} · {fmtTime(slot.start)}–{fmtTime(slot.end)}
              </span>
              <button className="btn ghost" onClick={() => { setSlot(null); setPhase('pick') }}>
                Change
              </button>
            </div>
            <div className="field">
              <label className="label">Your name</label>
              <input className="input" autoFocus value={name} maxLength={200}
                onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label className="label">Email</label>
              <input className="input" type="email" value={email} maxLength={320}
                onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label className="label">Notes (optional)</label>
              <textarea className="input" rows={3} value={notes} maxLength={2000}
                placeholder="Anything the host should know?"
                onChange={(e) => setNotes(e.target.value)} />
            </div>
            <div className="modal-actions">
              <button className="btn" disabled={busyNow || !name.trim() || !/^\S+@\S+\.\S+$/.test(email.trim())}
                onClick={submit}>
                {busyNow ? 'Booking…' : 'Confirm booking'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
