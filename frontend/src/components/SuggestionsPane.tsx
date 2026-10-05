// What the email reader suggests, waiting for a yes or a no.
//
// A pane of the Tasks view rather than a modal, for the reason Completed and
// Parked are: this is a place the owner goes to work through a queue, and a
// dialog would make every row a trip. Each row is editable in place — the title
// and the date are the two things a model most often gets slightly wrong, and
// fixing them before approving is cheaper than approving and then opening the
// task.
//
// The row says WHERE the suggestion came from and how sure the model was, and
// does both quietly. Nothing here auto-approves and nothing is ranked by
// confidence: the number is a hint about how closely to read the row, and the
// decision stays with the person reading it.

import { useEffect, useState } from 'react'
import { api, type List, type MailSuggestion, type ApproveSuggestionBody } from '../api'
import { useI18n } from '../i18n'
import { fmtClock, fmtDue, fmtWhen, inputLang } from '../time'
import { useTimeFormat } from '../timeformat'
import { dayKey, makeGuard } from '../util'
import { DateTimeInput } from './DateTimeInput'

export function SuggestionsPane({ onExpire, lists, items, loaded, error, onApprove, onReject }: {
  onExpire: () => void
  /** The owner's task lists, for the "where does this task go" choice. */
  lists: List[]
  items: MailSuggestion[]
  loaded: boolean
  error: string | null
  onApprove: (id: string, body: ApproveSuggestionBody) => Promise<boolean>
  onReject: (id: string) => Promise<boolean>
}) {
  const { t: tr } = useI18n()
  const guard = makeGuard(onExpire)
  const [calendars, setCalendars] = useState<List[] | null>(null)

  // Fetched only once an event is on screen: most owners will never have one,
  // and the list is not needed for anything else in this pane.
  const hasEvent = items.some((s) => s.kind === 'event')
  useEffect(() => {
    if (!hasEvent || calendars) return
    let alive = true
    guard(() => api.calendars()).then((r) => {
      if (alive && Array.isArray(r)) setCalendars(r)
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasEvent, calendars])

  return (
    <div className="scroll">
      {error && <div className="cal-partial" role="status">{error}</div>}
      {loaded && items.length === 0 && (
        <div className="empty">{tr('mail.sug.empty')}</div>
      )}
      {items.map((s) => (
        <Row key={s.id} s={s} lists={lists} calendars={calendars ?? []}
          onApprove={onApprove} onReject={onReject} />
      ))}
    </div>
  )
}

function Row({ s, lists, calendars, onApprove, onReject }: {
  s: MailSuggestion
  lists: List[]
  calendars: List[]
  onApprove: (id: string, body: ApproveSuggestionBody) => Promise<boolean>
  onReject: (id: string) => Promise<boolean>
}) {
  const { locale, lang, t: tr } = useI18n()
  const tf = useTimeFormat()
  // What the owner typed, or null while they have not touched the field. An
  // untouched field shows — and is not sent as — the latest the server said: a
  // later reply can move the date or retitle the row, and a copy taken at mount
  // would put the old one back on approve.
  const [titleEdit, setTitleEdit] = useState<string | null>(null)
  const [dueEdit, setDueEdit] = useState<string | null>(null)
  const title = titleEdit ?? s.title
  const due = dueEdit ?? (s.due ? dayKey(s.due) : '')
  const [list, setList] = useState('')
  const [calendar, setCalendar] = useState('')
  const [busy, setBusy] = useState(false)

  const isEvent = s.kind === 'event'
  const isUpdate = s.kind === 'update'
  const dated = !isEvent

  // A request that fails puts the row back (see `useMailSuggestions`), which
  // arrives as a fresh mount of this component — but only after the await, so
  // the buttons are re-enabled here too rather than relying on that.
  const run = async (send: () => Promise<boolean>) => {
    setBusy(true)
    try { await send() } finally { setBusy(false) }
  }

  const approve = () => {
    // Only what the owner edited is sent, so the server's current values win
    // for the rest. A cleared date is a statement (`null`), not an omission. An
    // event has no date to edit: its time is the email's.
    const body: ApproveSuggestionBody = {}
    if (titleEdit !== null) body.title = titleEdit.trim()
    if (dated && dueEdit !== null) body.due = dueEdit || null
    if (s.kind === 'task' && list) body.list = list
    if (isEvent && calendar) body.calendar = calendar
    return run(() => onApprove(s.id, body))
  }

  const when = s.event ? eventWhen(s.event, tf, locale) : ''
  const sender = s.source.sender_name || s.source.sender
  const sentDate = s.source.sent_at ? fmtDue(s.source.sent_at, true, tf, locale) : ''

  return (
    <div className="mail-sug" data-kind={s.kind}>
      <div className="mail-sug-head">
        <span className="mail-kind">{tr(`mail.sug.kind.${s.kind}`)}</span>
        {isUpdate ? (
          // The title of an update is the task's own and is not changed by
          // approving: only the date and the notes are applied.
          <span className="mail-sug-title">{s.title}</span>
        ) : (
          <input className="input mail-sug-title" value={title}
            aria-label={tr('mail.sug.titleAria')}
            onChange={(e) => setTitleEdit(e.target.value)} />
        )}
        {dated && (
          <DateTimeInput type="date" className="input mail-sug-due"
            lang={inputLang(tf, lang)} value={due}
            aria-label={tr('mail.sug.dueAria')}
            onChange={(e) => setDueEdit(e.target.value)} />
        )}
      </div>

      {isEvent && s.event && (
        <div className="hintline">
          {s.event.location
            ? tr('mail.sug.where', { when, where: s.event.location })
            : tr('mail.sug.when', { when })}
        </div>
      )}
      {s.kind === 'update' && (
        <div className="hintline">
          {tr('mail.sug.updates', { title: s.target?.title ?? '?' })}
        </div>
      )}

      {s.notes && (
        <details className="mail-sug-notes">
          <summary>{tr('mail.sug.notes')}</summary>
          <p>{s.notes}</p>
        </details>
      )}

      {s.updates.length > 0 && (
        <div className="mail-sug-later">
          <div className="hintline">{tr('mail.sug.updatesHead')}</div>
          <ul className="mail-sug-updates">
            {s.updates.map((u, i) => {
              const date = u.sent_at ? fmtDue(u.sent_at, true, tf, locale) : ''
              const head = [u.sender_name || u.sender, date].filter(Boolean).join(' · ')
              return (
                <li key={u.message_key || i}>
                  {u.notes ? `${head} — ${u.notes}` : head}
                  {u.due && ` · ${tr('mail.sug.newDue', { date: fmtDue(u.due, true, tf, locale) })}`}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <div className="mail-sug-src">
        {tr('mail.sug.from', {
          sender, subject: s.source.subject || tr('mail.sug.noSubject'), date: sentDate,
        })}
        {s.updates.length > 0 && ` ${tr('mail.sug.more', { count: s.updates.length })}`}
        {s.confidence != null && (
          <>
            {' '}
            <span className="mono" title={tr('mail.sug.confidence')}>
              {Math.round(s.confidence * 100)}%
            </span>
          </>
        )}
      </div>

      <div className="mail-sug-actions">
        {s.kind === 'task' && (
          <select className="input mail-sug-pick" value={list}
            aria-label={tr('mail.sug.listAria')}
            onChange={(e) => setList(e.target.value)}>
            <option value="">{tr('mail.sug.defaultList')}</option>
            {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        )}
        {isEvent && (
          <select className="input mail-sug-pick" value={calendar}
            aria-label={tr('mail.sug.calendarAria')}
            onChange={(e) => setCalendar(e.target.value)}>
            <option value="">{tr('mail.sug.defaultCalendar')}</option>
            {calendars.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <button className="btn ghost" disabled={busy}
          onClick={() => { void run(() => onReject(s.id)) }}>
          {tr('mail.sug.reject')}
        </button>
        <button className="btn" disabled={busy || !title.trim()}
          onClick={() => { void approve() }}>
          {tr(`mail.sug.approve.${s.kind}`)}
        </button>
      </div>
    </div>
  )
}

/** "Tue, Oct 6, 3:00 PM – 4:00 PM", or the date alone for an all-day event. */
function eventWhen(ev: NonNullable<MailSuggestion['event']>, tf: ReturnType<typeof useTimeFormat>,
  locale: string): string {
  if (ev.all_day) return fmtDue(ev.start, true, tf, locale)
  const start = fmtWhen(ev.start, tf, locale)
  if (!ev.end) return start
  // Only the clock when it ends the same day: repeating the date is noise.
  const sameDay = dayKey(ev.start) === dayKey(ev.end)
  return `${start} – ${sameDay ? fmtClock(ev.end, tf, locale) : fmtWhen(ev.end, tf, locale)}`
}
