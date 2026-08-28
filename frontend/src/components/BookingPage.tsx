import { useEffect, useMemo, useState } from 'react'
import { api, AuthError, clientId, HttpError, type PublicBookingInfo, type PublicSlot } from '../api'
import { ymd } from '../util'

// The public client-facing page at /book/<token>. Standalone by design: no
// session, no SSE, no imports from the authed shell. Slot ISO strings carry the
// link timezone's offset, so Date() lands them in the visitor's local time and
// everything renders in THEIR timezone (noted in the header).

// 'notfound' is terminal — the link really is gone. 'unavailable' is not: a
// rate-limit, a 5xx or a dropped connection says nothing about the link, and
// telling a visitor to go ask for a fresh one is both wrong and unrecoverable.
type Phase = 'loading' | 'notfound' | 'unavailable' | 'pick' | 'confirm' | 'done'

// `undefined` — the VISITOR's locale — and deliberately not the app's Language
// setting, for the same reason the times are in the visitor's timezone: nobody
// on this page is signed in. The setting belongs to the owner of the link, who
// is not the person reading it, and formatting a stranger's calendar in a
// language they may not read would be the owner's preference leaking onto
// somebody else's screen.
const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

/** The same time, named unambiguously — "1:00 AM CDT" rather than "1:00 AM".
 *
 * On the fall-back day the hour repeats, and `generate_slots` deliberately
 * offers BOTH passes of it (see test_fall_back_offers_the_repeated_hour). For a
 * visitor in a zone with the same transition — most of them, since a link is
 * usually shared within a country — the two slots printed the same label, on
 * the buttons, on the confirm bar and on the confirmation card. Nothing
 * anywhere told them which hour they were booking. */
const fmtTimeZoned = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined,
    { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })

const fmtDay = (key: string) =>
  new Date(`${key}T00:00`).toLocaleDateString(undefined,
    { weekday: 'long', month: 'long', day: 'numeric' })

const localDay = (iso: string) => ymd(new Date(iso))

export function BookingPage({ token }: { token: string }) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [info, setInfo] = useState<PublicBookingInfo | null>(null)
  const [day, setDay] = useState('')
  const [slot, setSlot] = useState<PublicSlot | null>(null)
  // The idempotency key for the slot currently chosen, minted ONCE when it is
  // chosen rather than per request. api.publicBook used to mint one inline on
  // every call, so a retry after a lost response replayed the same intent under
  // a different key — and the server's replay path (get_booking_by_event on
  // `{client_id}@tasksd`) was unreachable from the real client. `fetch` rejects
  // both when the write never landed and when the response was lost after the
  // CalDAV PUT committed, and the page keeps the slot selected and re-enables
  // the button, so retrying is the obvious move: one booking became two, and
  // the visitor was told their own slot "was just taken". Re-minted only when
  // they pick a different slot, which is a different intent.
  const [cid, setCid] = useState(() => clientId())
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [busyNow, setBusyNow] = useState(false)      // submit in flight
  const [error, setError] = useState<string | null>(null)
  // `zoned` records the decision made at confirm time: whether this slot's
  // label repeated on its day. The card is written after the slot list has been
  // refreshed away, so it cannot re-derive that — and it has to say the same
  // thing the button the visitor clicked said.
  const [booked, setBooked] =
    useState<{ start: string; end: string; zoned: boolean } | null>(null)

  const load = async (opts: { keepPhase?: boolean } = {}): Promise<PublicBookingInfo | null> => {
    try {
      const i = await api.publicBookingInfo(token)
      setInfo(i)
      if (!opts.keepPhase) setPhase('pick')
      return i
    } catch (e) {
      if (e instanceof AuthError) {
        // NOT a bare `return`. This endpoint needs no session, so a 401 here
        // means something in front of it is asking for one — an Access policy or
        // a proxy auth layer that swept /api/public/* in with the rest. Leaving
        // `phase` on 'loading' rendered a permanently blank white document to a
        // stranger, with nothing to read and nothing to click.
        if (!opts.keepPhase) setPhase('unavailable')
        return null
      }
      // Only a 404 means the link is gone. The backend rate-limits this exact
      // endpoint and counts every request, not just failures, so 121 loads in
      // five minutes from one address — a shared office NAT, or one visitor
      // reloading — used to tell everyone behind it that the host had removed
      // the link. A refresh that fails behind an already-shown message (the
      // race-recovery path) must not replace it either.
      if (!opts.keepPhase) {
        setPhase(e instanceof HttpError && e.status === 404 ? 'notfound' : 'unavailable')
      }
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

  // Which slot starts share a printed label with another slot the same day.
  // Only those get the zone suffix: adding it everywhere would put "CDT" on
  // every button on the page to solve a problem that exists twice a year.
  const ambiguous = useMemo(() => {
    const out = new Set<string>()
    for (const slots of slotsByDay.values()) {
      const seen = new Map<string, string>()
      for (const s of slots) {
        const label = fmtTime(s.start)
        const first = seen.get(label)
        if (first === undefined) seen.set(label, s.start)
        else { out.add(first); out.add(s.start) }
      }
    }
    return out
  }, [slotsByDay])
  // Used everywhere a slot time is shown — the buttons, the confirm bar and the
  // confirmation card — so the visitor sees the same unambiguous label at every
  // step of the one booking.
  const fmtSlot = (iso: string) => (ambiguous.has(iso) ? fmtTimeZoned(iso) : fmtTime(iso))

  const days = useMemo(() => [...slotsByDay.keys()].sort(), [slotsByDay])
  const selDay = days.includes(day) ? day : days[0] || ''
  const visitorTz = Intl.DateTimeFormat().resolvedOptions().timeZone

  const submit = async () => {
    if (!slot || busyNow) return
    setBusyNow(true)
    setError(null)
    try {
      const r = await api.publicBook(token, {
        client_id: cid,
        start: slot.start, name: name.trim(), email: email.trim(),
        notes: notes.trim() || undefined,
      })
      setBooked({ start: r.start, end: r.end, zoned: ambiguous.has(slot.start) })
      setPhase('done')
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (/not available/i.test(msg)) {
        // Lost the race — refresh the slot list and let them pick again.
        setError('That time was just taken — please pick another.')
        setSlot(null)
        setPhase('pick')
        await load({ keepPhase: true })
      } else {
        setError(msg)
      }
    } finally {
      setBusyNow(false)
    }
  }

  if (phase === 'loading') {
    // Not `null`. This is the one page an anonymous stranger opens, mounted by
    // main.tsx with no shell or spinner around it — so returning nothing was a
    // blank white document for the whole round trip. That is not a fast round
    // trip either: `public_link_info` runs slot generation and busy expansion
    // inside the global service lock. A visitor on a slow connection saw a page
    // that looked broken, and "Try again" on the error card sets `phase` back to
    // 'loading', so a retry replaced a readable error with the same blank.
    return (
      <div className="booking-wrap">
        <div className="booking-card">
          <div className="login-brand">Smylte<span className="dot">.</span></div>
          <p className="booking-lead" role="status" aria-live="polite">Loading the available times…</p>
        </div>
      </div>
    )
  }

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

  if (phase === 'unavailable') {
    return (
      <div className="booking-wrap">
        <div className="booking-card">
          <div className="login-brand">Smylte<span className="dot">.</span></div>
          <p className="booking-lead">Couldn’t load this page just now.</p>
          <p className="hintline">
            The link is probably fine — something went wrong on the way. Try again
            in a moment.
          </p>
          <button className="btn" onClick={() => { setPhase('loading'); load() }}>
            Try again
          </button>
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
            {booked.zoned
              ? `${fmtTimeZoned(booked.start)}–${fmtTimeZoned(booked.end)}`
              : `${fmtTime(booked.start)}–${fmtTime(booked.end)}`}
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
                // The warning is cleared where the INTENT changes. "That time
                // was just taken — pick another" stood over the visitor's next
                // pick, so the page told them off for doing exactly what it had
                // asked, and on a link whose whole audience is people the owner
                // does not get to explain the UI to.
                <button key={s.start} className="slot-btn"
                  onClick={() => {
                    setError(null); setSlot(s); setCid(clientId()); setPhase('confirm')
                  }}>
                  {fmtSlot(s.start)}
                </button>
              ))}
            </div>
          </>
        )}

        {phase === 'confirm' && slot && (
          <>
            <div className="booking-picked">
              <span>
                {fmtDay(localDay(slot.start))} · {fmtSlot(slot.start)}–{fmtSlot(slot.end)}
              </span>
              <button className="btn ghost"
                onClick={() => { setError(null); setSlot(null); setPhase('pick') }}>
                Change
              </button>
            </div>
            {/* htmlFor/id, the pair every other form in the app uses — Login's
                own comment calls it that. These three labels neither wrapped
                their control nor carried htmlFor, so none of the inputs had an
                accessible name, on the one form in the app an anonymous visitor
                fills in, often on a phone with a screen reader. */}
            <div className="field">
              <label className="label" htmlFor="booking-name">Your name</label>
              <input className="input" id="booking-name" name="name" autoComplete="name"
                autoFocus value={name} maxLength={200}
                onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="booking-email">Email</label>
              <input className="input" id="booking-email" name="email" type="email"
                autoComplete="email" value={email} maxLength={320}
                onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="booking-notes">Notes (optional)</label>
              <textarea className="input" id="booking-notes" name="notes" rows={3}
                value={notes} maxLength={2000}
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
