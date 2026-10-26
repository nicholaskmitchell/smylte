import { useEffect, useMemo, useRef, useState } from 'react'
import { api, HttpError, type ShareEvent, type ShareFocus, type ShareList, type ShareRow, type ShareTask, type ShareView } from '../api'
import { syncThemeColor } from '../appearance'
import { bucketByDay, shiftYmd } from '../calendar'
import { deviceLanguage, localeFor } from '../lang'
import { translate, type Vars } from '../i18n/index'
import {
  agendaDays, fmtDayLabel, fmtTime, FETCH_TIMEOUT_MS, isStale, localState, nextPollDelay,
  ongoingEvent, progress, remainingS, skewOf, toBucket,
} from '../share'
import { fmtCountdown } from '../time'
import { parseDate, textDir, ymd } from '../util'

// The public page at /share/<token>: somebody else's tasks, events and focus
// session, read-only, for a person who has no account here.
//
// Standalone by design, as BookingPage and DisplayView are: no session, no SSE,
// no DataProvider and no imports from the authed shell. `focus.ts` is left out
// on purpose, because it pulls TodayView in with it; the clock math this page
// needs lives in `share.ts`.
//
// It speaks the VIEWER's language and shows times in the VIEWER's zone and
// 12/24-hour convention. The owner's settings belong to the owner, and none of
// them is sent. What is sent is already allowlisted on the server, field by
// field; this page's part is to draw it as inert text and to forget it the
// moment the link stops working.

// 'gone' is terminal in the sense that matters: nothing polls, and the view is
// dropped from memory and from the DOM. 'unavailable' is not: a rate limit, a
// 5xx or a dropped connection says nothing about the link, and it is retried.
type Phase = 'loading' | 'ready' | 'gone' | 'unavailable'

export type Translate = (key: string, vars?: Vars) => string

/** Longest a freshly ticked row keeps its highlight. Matched by the CSS. */
const JUST_DONE_MS = 1_300

/** A wake-up (the tab becoming visible, the network returning) fetches at once
 *  unless a fetch has just been made, in which case it only re-arms the timer. */
const REFETCH_AFTER_MS = 5_000

/** The clock repaints every second while a countdown is running and the page is
 *  in front of someone; otherwise every half minute is enough to keep the stale
 *  strip and the agenda's now and past markers honest. */
const TICK_FAST_MS = 1_000
const TICK_SLOW_MS = 30_000

const NONE: ReadonlySet<string> = new Set()

/** Keys of today's rows that were open in `prev` and are done in `next`. */
function flippedKeys(prev: ShareView | null, next: ShareView): ReadonlySet<string> {
  const before = new Map((prev?.focus?.today.rows ?? []).map((r) => [r.key, r.done]))
  const out = new Set<string>()
  for (const r of next.focus?.today.rows ?? []) {
    if (r.done && before.get(r.key) === false) out.add(r.key)
  }
  return out.size ? out : NONE
}

export function SharePage({ token }: { token: string }) {
  // The browser's language and region, not an account setting: nobody on this
  // page is signed in. See BookingPage for the same argument.
  const lang = useMemo(() => deviceLanguage(), [])
  const locale = useMemo(() => localeFor(lang), [lang])
  const tr = useMemo<Translate>(() => (key, vars) => translate(lang, key, vars), [lang])

  const [phase, setPhase] = useState<Phase>('loading')
  const [view, setView] = useState<ShareView | null>(null)
  const [skewMs, setSkewMs] = useState(0)
  const [fetchedAt, setFetchedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [justDone, setJustDone] = useState<ReadonlySet<string>>(NONE)
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden')
  const [awake, setAwake] = useState(false)
  // What the Check again and Try again buttons call. The loop below owns its
  // state in locals so a timer never reads a stale render; the buttons reach it
  // through here.
  const retry = useRef<(showLoading: boolean) => void>(() => {})

  // The fetch loop. Everything it decides on lives in locals (the view, the
  // etag, the failure count) rather than in state: a timer callback closing over
  // state would read the render it was armed in, and every one of these changes
  // on each response.
  useEffect(() => {
    let alive = true
    let cur: ShareView | null = null
    let curPhase: Phase = 'loading'
    let etag: string | null = null
    let skew = 0
    let failures = 0
    let lastAttempt = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let doneTimer: ReturnType<typeof setTimeout> | undefined
    let inflight: AbortController | null = null

    const hidden = () => document.visibilityState === 'hidden'

    const schedule = () => {
      clearTimeout(timer)
      if (!alive || curPhase === 'gone') return
      const delay = nextPollDelay({
        view: cur, failures, hidden: hidden(), nowMs: Date.now(), skewMs: skew,
      })
      if (delay !== null) timer = setTimeout(() => { void load() }, delay)
    }

    const load = async () => {
      // One request at a time. A wake-up landing on top of a slow fetch would
      // otherwise race it, and the loser's etag could overwrite the winner's.
      if (inflight) return
      clearTimeout(timer)
      lastAttempt = Date.now()
      const mine = new AbortController()
      inflight = mine
      // A half-open socket never settles, and a page that waits on one forever
      // never tells the viewer it has stopped updating.
      const cut = setTimeout(() => mine.abort(), FETCH_TIMEOUT_MS)
      try {
        const got = await api.publicShareView(token, etag, mine.signal)
        if (!alive) return
        const received = Date.now()
        if (got.status === 'fresh') {
          const flipped = flippedKeys(cur, got.body)
          cur = got.body
          etag = got.etag
          skew = skewOf(got.body.generated_at, received)
          setView(got.body)
          setSkewMs(skew)
          if (flipped.size) {
            setJustDone(flipped)
            clearTimeout(doneTimer)
            doneTimer = setTimeout(() => setJustDone(NONE), JUST_DONE_MS)
          }
        }
        failures = 0
        curPhase = 'ready'
        setPhase('ready')
        setFetchedAt(received)
        setNow(received)
      } catch (e) {
        if (!alive) return
        if (e instanceof HttpError && e.status === 404) {
          // The link is off, rotated or deleted, and the server says all three
          // the same way. Drop everything the page was holding and stop: nothing
          // polls from here, and only the button asks again.
          cur = null
          etag = null
          failures = 0
          curPhase = 'gone'
          setView(null)
          setPhase('gone')
          return
        }
        // A proxy's 401, a 429, a 5xx, a timeout, a dropped connection. None of
        // them says anything about the link, so what is on screen stays.
        failures += 1
        if (!cur && curPhase !== 'gone') {
          curPhase = 'unavailable'
          setPhase('unavailable')
        }
      } finally {
        clearTimeout(cut)
        if (inflight === mine) inflight = null
      }
      schedule()
    }

    // The tab coming back, the network returning and a page restored from the
    // back-forward cache all say the same thing: what is on screen may be old.
    // A dead link ignores all three. Only the button asks again there, so a
    // revoked page does not quietly resume the moment someone switches tabs.
    const wake = () => {
      if (curPhase === 'gone' || hidden()) return
      if (Date.now() - lastAttempt > REFETCH_AFTER_MS) void load()
      else schedule()
    }
    const onVisibility = () => {
      setVisible(!hidden())
      if (curPhase === 'gone') return
      if (hidden()) { clearTimeout(timer); return }
      setNow(Date.now())
      wake()
    }
    const onPageShow = (e: PageTransitionEvent) => { if (e.persisted) wake() }

    retry.current = (showLoading) => {
      if (showLoading) { curPhase = 'loading'; setPhase('loading') }
      void load()
    }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pageshow', onPageShow)
    window.addEventListener('online', wake)
    void load()
    return () => {
      alive = false
      clearTimeout(timer)
      clearTimeout(doneTimer)
      inflight?.abort()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pageshow', onPageShow)
      window.removeEventListener('online', wake)
    }
  }, [token])

  const liveState = view?.focus ? localState(view.focus, now, skewMs) : 'idle'
  const counting = liveState === 'focusing' || liveState === 'break'
  const fast = counting && visible
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), fast ? TICK_FAST_MS : TICK_SLOW_MS)
    return () => clearInterval(id)
  }, [fast])

  // The tab title carries the countdown so a pinned tab shows it. It never
  // carries owner text: a title is in history, in screenshots of a tab strip
  // and in a window switcher, all of which are wider than this page.
  const left = view?.focus && counting ? remainingS(view.focus, now, skewMs) : null
  useEffect(() => {
    const base = `${tr('share.pageTitle')} · Smylte`
    document.title = left !== null ? `${fmtCountdown(left)} · ${base}` : base
  }, [left, tr])

  useEffect(() => { document.documentElement.lang = lang }, [lang])

  // The viewer's theme, which is the system's unless they have chosen one in
  // the app on this device. index.html has already applied a stored choice
  // before the bundle loaded, so only the unset case is handled here. Read, and
  // never written: this page has nothing of its own to remember.
  useEffect(() => {
    let stored: string | null = null
    try { stored = localStorage.getItem('smylte-theme') } catch { /* storage may be blocked */ }
    if (stored === 'dark' || stored === 'light') return
    const root = document.documentElement
    const dark = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      root.dataset.theme = dark.matches ? 'dark' : 'light'
      syncThemeColor()
    }
    apply()
    dark.addEventListener('change', apply)
    return () => {
      dark.removeEventListener('change', apply)
      delete root.dataset.theme
    }
  }, [])

  // Keep the screen on, for a tablet propped on a desk. Local only: nothing
  // about it is sent anywhere. A wake lock is released by the browser whenever
  // the page is hidden, so it is asked for again on coming back.
  useEffect(() => {
    if (!awake) return
    let on = true
    let sentinel: WakeLockSentinel | null = null
    const acquire = async () => {
      if (sentinel && !sentinel.released) return
      try {
        const got = await navigator.wakeLock.request('screen')
        if (!on) { void got.release(); return }
        sentinel = got
      } catch {
        // Refused (low battery, a policy): the switch goes back off rather than
        // claim a state it is not in.
        if (on) setAwake(false)
      }
    }
    const again = () => { if (document.visibilityState === 'visible') void acquire() }
    document.addEventListener('visibilitychange', again)
    void acquire()
    return () => {
      on = false
      document.removeEventListener('visibilitychange', again)
      void sentinel?.release()
    }
  }, [awake])

  if (phase === 'loading') {
    // Not `null`: a blank white document for the whole round trip looks broken
    // to a stranger who was sent a link. The card is empty on purpose, because
    // anything it could say would be a guess about what is behind the link.
    return (
      <div className="share-wrap">
        <div className="share-card" aria-busy="true" />
      </div>
    )
  }

  if (phase === 'gone') {
    return (
      <div className="share-wrap">
        <div className="share-card share-gone">
          <p className="share-gone__title">{tr('share.gone')}</p>
          <p className="hintline">{tr('share.goneHint')}</p>
          <button className="btn" onClick={() => retry.current(false)}>{tr('share.checkAgain')}</button>
        </div>
      </div>
    )
  }

  if (phase === 'unavailable' || !view) {
    return (
      <div className="share-wrap">
        <div className="share-card share-unavailable">
          <p className="share-gone__title">{tr('share.unavailable')}</p>
          <p className="hintline">{tr('share.unavailableHint')}</p>
          <button className="btn" onClick={() => retry.current(true)}>{tr('share.tryAgain')}</button>
        </div>
      </div>
    )
  }

  const stale = isStale(fetchedAt, view, now)
  const canWake = typeof navigator !== 'undefined' && 'wakeLock' in navigator

  return (
    <div className="share-wrap">
      <main className="share">
        <header className="share-head">
          <h1 className="share-head__title">{tr('share.heading')}</h1>
          <div className="share-head__day">
            {parseDate(view.day).toLocaleDateString(locale,
              { weekday: 'long', month: 'long', day: 'numeric' })}
          </div>
          <div className="share-head__meta">
            {stale
              ? <span className="share-stale">{tr('share.stale')}</span>
              : <span className="share-live"><span className="share-live__dot" aria-hidden="true" />{tr('share.live')}</span>}
            <span className="share-readonly">{tr('share.readOnly')}</span>
          </div>
        </header>
        <ShareBody view={view} nowMs={now} skewMs={skewMs} tr={tr} locale={locale} justDone={justDone} />
        <footer className="share-foot">
          <span>{tr('share.footer')}</span>
          {canWake && (
            <button className="btn ghost" aria-pressed={awake} onClick={() => setAwake((a) => !a)}>
              {awake ? tr('share.keepAwakeOn') : tr('share.keepAwake')}
            </button>
          )}
        </footer>
      </main>
    </div>
  )
}

// ── the body ─────────────────────────────────────────────────────────────────

/** What a task or today's row is called on screen. A private item has an empty
 *  title already; the flag is what lets this say "Busy" for it and "(no title)"
 *  for a task its owner simply never named. */
const itemTitle = (tr: Translate, title: string, priv: boolean) =>
  priv ? tr('share.busy') : (title || tr('share.untitled'))

/** An event with nothing to show is busy, whether the owner marked it private or
 *  the link a booking came through was deleted. */
const eventTitle = (tr: Translate, e: Pick<ShareEvent, 'title' | 'private'>) =>
  e.private || !e.title ? tr('share.busy') : e.title

/** The reader's own "when" for a due date: a word for today and tomorrow, a short
 *  date otherwise, and the time of day when the task has one. A standalone word,
 *  for a chip; a sentence about a due date is `dueLabel`. */
function whenLabel(tr: Translate, locale: string, today: string, due: string, allDay: boolean): string {
  const day = ymd(parseDate(due))
  const word = day === today ? tr('share.today')
    : day === shiftYmd(today, 1) ? tr('share.tomorrow')
      : parseDate(day).toLocaleDateString(locale, { month: 'short', day: 'numeric' })
  return allDay ? word : `${word} ${fmtTime(due, locale)}`
}

/** "Due today", "Due tomorrow, 9:00 AM", "Due Nov 5": the whole phrase, because
 *  "Due Today" with a capital in the middle of it reads as a heading's word put
 *  in a sentence. Today and tomorrow are written out as phrases of their own, so
 *  each language places its word and its comma where it wants them. */
function dueLabel(tr: Translate, locale: string, today: string, due: string, allDay: boolean): string {
  const day = ymd(parseDate(due))
  const time = allDay ? '' : fmtTime(due, locale)
  if (day === today) return allDay ? tr('share.dueToday') : tr('share.dueTodayAt', { time })
  if (day === shiftYmd(today, 1)) return allDay ? tr('share.dueTomorrow') : tr('share.dueTomorrowAt', { time })
  const date = parseDate(day).toLocaleDateString(locale, { month: 'short', day: 'numeric' })
  return tr('share.due', { when: allDay ? date : `${date} ${time}` })
}

/** What the page draws for a share. Presentational, so the owner's preview in
 *  Settings shows exactly what the other person sees. Every time that is
 *  compared with "now" is read on the SERVER's clock (`nowMs + skewMs`): a
 *  device an hour off would otherwise mark the wrong event as under way. */
export function ShareBody({ view, nowMs, skewMs, tr, locale, justDone }: {
  view: ShareView
  nowMs: number
  skewMs: number
  tr: Translate
  locale: string
  justDone: ReadonlySet<string>
}) {
  if (!view.focus && view.lists.length === 0 && view.calendars.length === 0) {
    return (
      <section className="share-card">
        <p className="share-muted">{tr('share.empty')}</p>
      </section>
    )
  }
  return (
    <>
      {view.focus && (
        <Presence view={view} focus={view.focus} nowMs={nowMs} skewMs={skewMs}
          tr={tr} locale={locale} justDone={justDone} />
      )}
      {view.calendars.length > 0 && (
        <Agenda view={view} nowMs={nowMs} skewMs={skewMs} tr={tr} locale={locale} />
      )}
      {view.lists.map((list, i) => (
        <TaskList key={i} list={list} single={view.lists.length === 1}
          nowMs={nowMs} skewMs={skewMs} tr={tr} locale={locale} />
      ))}
    </>
  )
}

function Presence({ view, focus, nowMs, skewMs, tr, locale, justDone }: {
  view: ShareView
  focus: ShareFocus
  nowMs: number
  skewMs: number
  tr: Translate
  locale: string
  justDone: ReadonlySet<string>
}) {
  const state = localState(focus, nowMs, skewMs)
  const left = remainingS(focus, nowMs, skewMs)
  const showClock = (state === 'focusing' || state === 'break' || state === 'paused') && left !== null
  const today = ymd(new Date(nowMs + skewMs))
  const { rows, now: nowKey, next } = focus.today
  const byKey = new Map(rows.map((r) => [r.key, r]))
  const rowOf = (key: string | null): ShareRow | undefined => (key ? byKey.get(key) : undefined)
  const nowRow = state === 'idle' ? undefined : rowOf(nowKey)
  const nextRows = next.map(rowOf).filter((r): r is ShareRow => !!r)
  const rowName = (r: ShareRow) => itemTitle(tr, r.title, r.private)

  // One `switch` with literal keys, so the catalogue scan sees every one.
  let label: string
  switch (state) {
    case 'focusing': label = tr('share.state.focusing'); break
    case 'break':
      label = focus.phase === 'long_break' ? tr('share.state.longBreak') : tr('share.state.break')
      break
    case 'paused': label = tr('share.state.paused'); break
    case 'between':
      label = focus.phase === 'break' || focus.phase === 'long_break'
        ? tr('share.state.breakOver') : tr('share.state.between')
      break
    default: label = tr('share.state.idle')
  }

  const ongoing = state === 'idle' ? ongoingEvent(view.events, nowMs + skewMs) : null
  const done = rows.filter((r) => r.done).length
  const nowName = nowRow ? rowName(nowRow) : ''
  const thenName = state !== 'idle' && nextRows[0] ? rowName(nextRows[0]) : ''
  // "Then" follows a "Working on" or an "Up next" line. With no row above it to
  // follow, the next task is the first thing said, and "Then" would dangle.
  const thenLabel = nowRow ? tr('share.then') : tr('share.upNext')
  const ongoingBusy = !!ongoing && (ongoing.private || !ongoing.title)

  return (
    <section className="share-card share-presence" data-state={state} data-phase={focus.phase ?? undefined}>
      <div className="share-presence__eyebrow" role="status" aria-live="polite">{label}</div>
      {showClock && (
        <>
          <div className="share-presence__clock" aria-live="off">{fmtCountdown(left)}</div>
          <span className="share-sr">{tr('share.left', { count: Math.ceil(left / 60) })}</span>
          <div className="share-presence__bar" aria-hidden="true">
            <span style={{ width: `${Math.round(progress(focus, nowMs, skewMs) * 100)}%` }} />
          </div>
        </>
      )}
      {nowRow && (
        <div className="share-now">
          <div className="share-now__label">
            {state === 'focusing' || state === 'paused' ? tr('share.workingOn') : tr('share.upNext')}
          </div>
          <h2 className="share-now__title" dir={textDir(nowName)}>{nowName}</h2>
        </div>
      )}
      {thenName && (
        <p className="share-then">
          <span className="share-then__label">{thenLabel}</span>{' '}
          <span className="share-then__text" dir={textDir(thenName)}>{thenName}</span>
        </p>
      )}
      {state === 'idle' && (ongoing ? (
        <p className="share-then" dir={textDir(eventTitle(tr, ongoing))}>
          {ongoingBusy
            ? tr('share.busyUntil', { time: fmtTime(ongoing.end!, locale) })
            : tr('share.inEvent', { title: eventTitle(tr, ongoing), time: fmtTime(ongoing.end!, locale) })}
        </p>
      ) : nextRows.length > 0 && (
        <p className="share-then">
          <span className="share-then__label">{tr('share.upNext')}</span>
          {nextRows.map((r) => (
            <span key={r.key} className="share-then__text" dir={textDir(rowName(r))}>{' '}{rowName(r)}</span>
          ))}
        </p>
      ))}
      {view.lists.length > 0 && (
        <div className="share-today">
          <div className="share-today__head">
            <span className="share-label">{tr('share.today')}</span>
            {rows.length > 0 && (
              <span className="share-today__count">
                {tr('share.todayCount', { done, total: rows.length })}
              </span>
            )}
          </div>
          {rows.length === 0 && <p className="share-muted">{tr('share.todayEmpty')}</p>}
          {rows.length > 0 && done === rows.length && <p className="share-muted">{tr('share.allDone')}</p>}
          {rows.length > 0 && (
            <ul className="share-rows">
              {rows.map((r) => {
                const name = rowName(r)
                return (
                  <li key={r.key}
                    className={`share-row${r.done ? ' is-done' : ''}${r.key === nowKey && state !== 'idle' ? ' is-now' : ''}${justDone.has(r.key) ? ' just-done' : ''}`}>
                    <span className="share-row__mark" aria-hidden="true" />
                    <span className="share-row__text" dir={textDir(name)}>
                      {name}
                      {r.done && <span className="share-sr"> {tr('share.done')}</span>}
                    </span>
                    {r.due && (
                      <span className="share-row__due">
                        {whenLabel(tr, locale, today, r.due, r.all_day)}
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

function Agenda({ view, nowMs, skewMs, tr, locale }: {
  view: ShareView
  nowMs: number
  skewMs: number
  tr: Translate
  locale: string
}) {
  const serverNow = nowMs + skewMs
  // The VIEWER's local today, on the server's clock. The server sends a window a
  // day wider on each side, so whichever side of the date line this is, every
  // one of these days has its events.
  const today = ymd(new Date(serverNow))
  const days = agendaDays(today, view.days)
  const buckets = bucketByDay(view.events.map(toBucket), days.map((d) => parseDate(d)))
  const hasAny = days.some((d) => (buckets.get(d)?.length ?? 0) > 0)
  // Seven days of headings over nothing is as empty as four weeks of them. Today
  // and tomorrow always show, because "nothing today" is information; beyond
  // that, only days that have something, whatever the horizon.
  const shown = days.filter((d, i) => i < 2 || (buckets.get(d)?.length ?? 0) > 0)
  return (
    <section className="share-card share-agenda">
      <div className="share-label">{tr('share.comingUp')}</div>
      {!hasAny ? (
        <p className="share-muted">{tr('share.eventsEmpty')}</p>
      ) : shown.map((d) => {
        const evs = buckets.get(d) ?? []
        const when = fmtDayLabel(d, today, locale)
        return (
          <div key={d} className="share-day">
            <h2 className="share-day__label">
              {when === 'today' ? tr('share.today') : when === 'tomorrow' ? tr('share.tomorrow') : when}
            </h2>
            {evs.length > 0 && (
              <ul className="share-evs">
                {evs.map((e, i) => {
                  const startMs = e.all_day ? NaN : parseDate(e.start).getTime()
                  const endMs = e.all_day ? NaN : parseDate(e.end ?? e.start).getTime()
                  const isNow = startMs <= serverNow && serverNow < endMs
                  const isPast = endMs <= serverNow
                  const name = eventTitle(tr, e)
                  const color = view.calendars[e.calendar]?.color ?? null
                  return (
                    <li key={`${i}-${e.start}-${e.calendar}`}
                      className={`share-ev${isPast ? ' is-past' : ''}${isNow ? ' is-now' : ''}`}>
                      <time className="share-ev__time" dateTime={e.start}>
                        {e.all_day ? tr('share.allDay')
                          : e.cont ? tr('share.continued')
                            : e.end ? `${fmtTime(e.start, locale)}–${fmtTime(e.end, locale)}`
                              : fmtTime(e.start, locale)}
                      </time>
                      <span className="share-ev__dot" aria-hidden="true"
                        style={color ? { background: color } : undefined} />
                      <span className="share-ev__title" dir={textDir(name)}>{name}</span>
                      {isNow && <span className="share-ev__now">{tr('share.now')}</span>}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )
      })}
      {view.events_more > 0 && <p className="share-more">{tr('share.more', { count: view.events_more })}</p>}
    </section>
  )
}

function TaskList({ list, single, nowMs, skewMs, tr, locale }: {
  list: ShareList
  single: boolean
  nowMs: number
  skewMs: number
  tr: Translate
  locale: string
}) {
  const serverNow = nowMs + skewMs
  const today = ymd(new Date(serverNow))
  const name = list.name || tr('share.untitledList')
  const overdue = (t: ShareTask) => !!t.due && (t.all_day
    ? ymd(parseDate(t.due)) < today
    : parseDate(t.due).getTime() < serverNow)
  return (
    <details className="share-card share-list" open={single && list.tasks.length <= 8 && list.more === 0}>
      <summary className="share-list__sum">
        <span className="share-list__dot" aria-hidden="true"
          style={list.color ? { background: list.color } : undefined} />
        <span className="share-list__name" dir={textDir(name)}>{name}</span>
        <span className="share-list__count">{list.tasks.length + list.more}</span>
      </summary>
      {list.tasks.length > 0 && (
        <ul className="share-tasks">
          {list.tasks.map((t, i) => {
            const title = itemTitle(tr, t.title, t.private)
            return (
              <li key={i} className="share-task" data-depth={t.depth}>
                <span className="share-task__text" dir={textDir(title)}>{title}</span>
                {t.due && (
                  <span className={`share-task__due${overdue(t) ? ' is-late' : ''}`}>
                    {dueLabel(tr, locale, today, t.due, t.all_day)}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {list.more > 0 && <p className="share-more">{tr('share.more', { count: list.more })}</p>}
      {list.tasks.length === 0 && list.more === 0 && <p className="share-muted">{tr('share.listEmpty')}</p>}
    </details>
  )
}
