// "Notify me N minutes before." One control, used by the task editor and the
// event editor, because it is one feature: the value lands in the same sidecar
// column and is read by the same notification rule whichever editor set it.
//
// A picker rather than a free number field. The useful leads are a short list
// (you want five minutes, or a day, not 37 minutes), a select states the whole
// range without the user having to discover it, and "Don't notify" is then a
// real option in the same control rather than a cleared field — which matters,
// because 0 is a real answer here ("tell me at the moment itself") and cannot
// double as "off".

import { useT } from '../i18n'
import type { Vars } from '../i18n/index'

/** The value meaning "no reminder". Sent to the server as -1, which is the
 *  clear sentinel every duration in this app uses — 0 is a real lead, so the
 *  clear cannot borrow falsiness. */
export const NO_REMINDER = -1

// Minutes. Kept short deliberately: a longer list is not more useful, it is
// just more to read past on the way to the two everybody picks.
export const REMINDER_CHOICES = [0, 5, 10, 15, 30, 60, 120, 1440] as const

export function ReminderField({ value, onChange, id = 'reminder', disabled = false }: {
  /** Minutes before, or null for "no reminder". */
  value: number | null
  onChange: (next: number | null) => void
  id?: string
  disabled?: boolean
}) {
  const tr = useT()
  // A stored value the list does not offer — set through the API, the MCP
  // connector, or a build with a different list — is kept as its own option
  // rather than silently snapped to the nearest choice. Rewriting someone's 45
  // minutes to 30 because this control has no row for it would be the picker
  // editing data it was only asked to display.
  const choices: number[] = value !== null && !REMINDER_CHOICES.includes(value as never)
    ? [...REMINDER_CHOICES, value].sort((a, b) => a - b)
    : [...REMINDER_CHOICES]

  return (
    <select className="menu-toggle reminder-field" id={id} disabled={disabled}
      value={value === null ? '' : String(value)}
      aria-label={tr('reminder.aria')}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}>
      <option value="">{tr('reminder.none')}</option>
      {choices.map((m) => (
        <option key={m} value={String(m)}>{reminderLabel(m, tr)}</option>
      ))}
    </select>
  )
}

/** How a lead reads in a row or a picker. Exported for the callers that show
 *  the current value without opening the control. */
export function reminderLabel(minutes: number, tr: (k: string, v?: Vars) => string): string {
  if (minutes === 0) return tr('reminder.atTime')
  if (minutes % 1440 === 0) return tr('reminder.days', { n: minutes / 1440 })
  if (minutes % 60 === 0) return tr('reminder.hours', { n: minutes / 60 })
  return tr('reminder.minutes', { n: minutes })
}
