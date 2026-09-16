// WHAT IT WAS PROMISED FOR, beside whatever it is scheduled for now.
//
// `original_due` is the deadline a task was moved off AFTER that deadline had
// already passed — the fact rescheduling used to destroy, because DUE holds one
// value and writing a new one leaves nothing anywhere saying the old one was
// ever missed. The server records it once, from something that actually
// happened (`service.py::_deadline_being_missed`), and never overwrites it.
//
// This exists as a component rather than as markup because the fact now has to
// travel. It used to be inlined on the Today tab's SUGGESTION rows and nowhere
// else, which meant the record vanished at the exact instant the owner acted on
// it: pressing `+` moved the task onto the day, and the day's own rows carried
// no such chip. The other three surfaces that render a task's deadline — the
// Tasks pane, the two dashboard rows, the day plan — showed a rescheduled task
// as an ordinary one, so "when is this due" had a different answer depending on
// which tab you asked it from. One component, one reading, every surface.
//
// THE COUNT IS THE POINT, not decoration. A bare "was due Mar 11" is a date
// without a scale, and `fmtDue` prints no year — so a deadline missed last
// March reads as this March, and eleven days late reads exactly like eleven
// months. The age says which it is. It is omitted, rather than printed as `0d`,
// when the remembered deadline falls on the day being measured against: a 09:00
// deadline moved at 10:00 has genuinely slipped, and "0d" would be a claim that
// it had not. `daysSlipped` answers null for that case and this renders the
// date alone.
//
// It is also the one WARN-coloured thing on its row, and the surfaces that
// render it give their own due cell's warn up when it is present (see
// `.was-due` in app.css). Two orange dates on one row read as two alarms; the
// interesting one is not the date the reschedule chose.
import { useI18n } from '../i18n'
import { fmtDue } from '../time'
import { useTimeFormat } from '../timeformat'
import { daysSlipped, slippedFrom, ymd, type Slippable } from '../util'

/**
 * The chip, or nothing at all.
 *
 * `task` is nullable because half the callers render rows that may name no task
 * — a note and a habit occurrence on the day plan resolve to none — and a
 * caller having to write the null check itself is a caller that can forget to.
 *
 * `day` is the day being measured against, and it is a parameter for the reason
 * every other date function here takes one: the Today tab steps its own day
 * back and forth, and a look-back has to read as the day it is reviewing. It
 * DEFAULTS to the wall clock because every other surface that renders a
 * deadline — the Tasks pane, the dashboard — is only ever about now, and making
 * each of them spell that out is four chances to spell it differently. The
 * default is read at render and so does not survive a rollover on its own;
 * nothing here needs it to, since the count is in days and the surfaces that
 * care about the changeover (the Today tab) pass their own day anyway.
 *
 * `done` KEEPS THE FACT AND DROPS THE ALARM. A task finished three weeks after
 * it was promised slipped, and the completed pane, the look-back and the
 * dashboard's finished rows are all fair places to say so — how late something
 * ran is part of how the work went. But warn is a call to act, and there is
 * nothing left to act on: an orange chip on a ticked row is the screen shouting
 * about a question it has already answered. So the chip goes quiet and goes on
 * saying the same words. It is a prop rather than a fifth field on `Slippable`
 * because completion decides nothing about whether a deadline was missed —
 * `daysLate` and the triage group it feeds must not start caring — and every
 * caller that renders a finished row already knows it is one.
 */
export function WasDue({ task, day = ymd(new Date()), done = false }: {
  task: Slippable | null | undefined
  day?: string
  done?: boolean
}) {
  const { locale, t: tr } = useI18n()
  const tf = useTimeFormat()
  const from = task ? slippedFrom(task) : null
  if (!from || !task) return null
  const days = daysSlipped(task, day)
  const date = fmtDue(from[0], from[1], tf, locale)
  return (
    <span className={`was-due mono ${done ? 'done' : ''}`}>
      {days == null
        ? tr('today.wasDue', { date })
        : tr('today.wasDueDays', { date, days })}
    </span>
  )
}
