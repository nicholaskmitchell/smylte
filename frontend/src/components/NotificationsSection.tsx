// Notification rules: which ones are on, when the digest arrives, and how much
// warning a meeting gets.
//
// A section body inside the settings panel, not a dialog of its own: the panel
// column owns the scrolling, the heading and the way out, so this renders only
// its own rows.
//
// Every row says whether the rule BUZZES or arrives silently, and that is the
// point of the section rather than decoration. Loud and quiet are fixed in the
// backend — a booking or a sync failure can never wake anyone — so the question
// this screen has to answer is not "when may it interrupt me" (there is nothing
// to set) but "what am I agreeing to by leaving this on".

import { useEffect, useState } from 'react'
import { useT } from '../i18n'
import {
  MAX_EVENT_LEAD_MINUTES, MIN_EVENT_LEAD_MINUTES, TRIGGERS, TRIGGER_HINTS,
  TRIGGER_IS_LOUD, TRIGGER_LABELS, isDigestTime, triggerEnabled, type Trigger,
} from '../notifications'
import { DateTimeInput } from './DateTimeInput'

export function NotificationsSection({
  triggers, onTriggersChange,
  digestTime, onDigestTimeChange,
  eventLead, onEventLeadChange,
  homeTz,
}: {
  triggers: Partial<Record<Trigger, boolean>>
  onTriggersChange: (next: Partial<Record<Trigger, boolean>>) => void
  digestTime: string
  onDigestTimeChange: (next: string) => void
  eventLead: number
  onEventLeadChange: (next: number) => void
  /** The account's home timezone, or '' — the digest refuses to fire without one. */
  homeTz: string
}) {
  const tr = useT()

  // The time field holds a local draft and commits on blur/Enter, like
  // CapacityField: an <input type="time"> reports every intermediate value as
  // the user types, and a half-typed one is both a wrong hour and — since the
  // server REJECTS a malformed `notify_digest_time` rather than filtering it —
  // a 422 that would take the whole settings PUT with it.
  const [draft, setDraft] = useState(digestTime)
  useEffect(() => { setDraft(digestTime) }, [digestTime])

  const commit = () => {
    if (isDigestTime(draft)) onDigestTimeChange(draft)
    else setDraft(digestTime)
  }

  const toggle = (t: Trigger) => {
    onTriggersChange({ ...triggers, [t]: !triggerEnabled(triggers, t) })
  }

  return (
    <>
      <div className="notif-rules">
        {TRIGGERS.map((t) => {
          const on = triggerEnabled(triggers, t)
          return (
            <div className="notif-rule" key={t}>
              <div className="menu-row">
                <label htmlFor={`notif-${t}`}>{tr(TRIGGER_LABELS[t])}</label>
                <span className={`chip notif-volume${TRIGGER_IS_LOUD[t] ? ' loud' : ''}`}>
                  {tr(TRIGGER_IS_LOUD[t] ? 'notif.volume.buzzes' : 'notif.volume.silent')}
                </span>
                <button className="menu-toggle" id={`notif-${t}`}
                  aria-pressed={on}
                  aria-label={tr('notif.trigger.aria', { rule: tr(TRIGGER_LABELS[t]) })}
                  onClick={() => toggle(t)}>
                  {tr(on ? 'notif.on' : 'notif.off')}
                </button>
              </div>
              <div className="hintline">{tr(TRIGGER_HINTS[t])}</div>
            </div>
          )
        })}
      </div>

      <div className="menu-head">{tr('notif.timing')}</div>

      <div className="menu-row">
        <label htmlFor="notif-digest-time">{tr('notif.digestTime')}</label>
        <DateTimeInput type="time" className="input notif-time" id="notif-digest-time"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { commit(); (e.target as HTMLInputElement).blur() }
            if (e.key === 'Escape') { setDraft(digestTime); e.stopPropagation() }
          }} />
      </div>
      {/* The one misconfiguration that silently disables a rule. The digest
          refuses to fire at all without a home timezone rather than resolving
          the hour against the server clock — which is UTC in the ordinary
          deploy, so "07:30" would land in the middle of the night — and a rule
          that is on but never fires is worse than one that is off. */}
      <div className={`hintline${homeTz ? '' : ' warn'}`}>
        {homeTz ? tr('notif.digestTime.hint', { tz: homeTz })
          : tr('notif.digestTime.noTz')}
      </div>

      <div className="menu-row">
        <label htmlFor="notif-lead">{tr('notif.eventLead')}</label>
        <input className="input notif-lead" id="notif-lead" type="number"
          min={MIN_EVENT_LEAD_MINUTES} max={MAX_EVENT_LEAD_MINUTES} step={1}
          value={eventLead}
          onChange={(e) => {
            const n = Number(e.target.value)
            if (Number.isFinite(n)) onEventLeadChange(n)
          }} />
      </div>
      <div className="hintline">{tr('notif.eventLead.hint')}</div>

      <div className="hintline">{tr('notif.ceiling.hint')}</div>
    </>
  )
}
