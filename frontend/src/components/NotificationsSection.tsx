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
import { api, AuthError } from '../api'
import { useT } from '../i18n'
import {
  DEFAULT_OFF, DEFAULT_ON, MAX_EVENT_LEAD_MINUTES, MIN_EVENT_LEAD_MINUTES,
  TRIGGER_HINTS, TRIGGER_IS_EVENING, TRIGGER_IS_LOUD, TRIGGER_LABELS,
  isDigestTime, triggerEnabled, type Trigger,
} from '../notifications'
import { DateTimeInput } from './DateTimeInput'

export function NotificationsSection({
  enabled, onEnabledChange,
  chatId, onChatIdChange,
  tokenSet, botId, onTokenChange,
  triggers, onTriggersChange,
  digestTime, onDigestTimeChange,
  eveningTime, onEveningTimeChange,
  eventLead, onEventLeadChange,
  taskLead, onTaskLeadChange,
  homeTz, onExpire,
}: {
  enabled: boolean
  onEnabledChange: (next: boolean) => void
  chatId: string
  onChatIdChange: (next: string) => void
  /** Whether a bot token is stored. The token itself is never sent back — see
   *  `_public_settings` server-side — so this and `botId` are all the UI has,
   *  and all it needs: enough to say which bot is configured without being able
   *  to speak as it. */
  tokenSet: boolean
  botId: string
  onTokenChange: (next: string) => void
  triggers: Partial<Record<Trigger, boolean>>
  onTriggersChange: (next: Partial<Record<Trigger, boolean>>) => void
  digestTime: string
  onDigestTimeChange: (next: string) => void
  /** The hour the evening rules fire at. A second wall clock rather than one
   *  per rule — every rule that samples a standing condition uses this or the
   *  digest hour, so the whole opt-in tier costs two settings. */
  eveningTime: string
  onEveningTimeChange: (next: string) => void
  eventLead: number
  onEventLeadChange: (next: number) => void
  /** The blanket lead for a task deadline, used only by `task_due_soon`. */
  taskLead: number
  onTaskLeadChange: (next: number) => void
  /** The account's home timezone, or '' — the digest refuses to fire without one. */
  homeTz: string
  onExpire: () => void
}) {
  const tr = useT()
  // A write-only field: it starts empty even when a token IS stored, because
  // there is nothing to prefill it with. Emptying it is therefore not "clear
  // the token" — the row has its own Remove for that, so a stray click in a
  // field the owner never meant to touch cannot silently disconnect the bot.
  const [token, setToken] = useState('')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null)

  const runTest = async () => {
    setTesting(true)
    setResult(null)
    try {
      const r = await api.testNotification()
      setResult({ ok: true, detail: r.detail })
    } catch (err) {
      if (err instanceof AuthError) { onExpire(); return }
      setResult({ ok: false, detail: err instanceof Error ? err.message : String(err) })
    } finally {
      setTesting(false)
    }
  }

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

  const [eveningDraft, setEveningDraft] = useState(eveningTime)
  useEffect(() => { setEveningDraft(eveningTime) }, [eveningTime])
  const commitEvening = () => {
    if (isDigestTime(eveningDraft)) onEveningTimeChange(eveningDraft)
    else setEveningDraft(eveningTime)
  }

  const toggle = (t: Trigger) => {
    onTriggersChange({ ...triggers, [t]: !triggerEnabled(triggers, t) })
  }

  const rule = (t: Trigger) => {
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
        <div className="hintline">
          {tr(TRIGGER_HINTS[t])}
          {/* Where its timing comes from, said once per rule rather than left
              to be inferred: a wall-clock rule is governed by a field further
              down this page, and knowing which one is the difference between
              "why did this arrive at 9pm" and knowing where to change it. */}
          {on && TRIGGER_IS_EVENING[t] && ` ${tr('notif.firesEvening')}`}
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="menu-row">
        <label htmlFor="notif-enabled">{tr('notif.enabled')}</label>
        <button className="menu-toggle" id="notif-enabled" aria-pressed={enabled}
          onClick={() => onEnabledChange(!enabled)}>
          {tr(enabled ? 'notif.on' : 'notif.off')}
        </button>
      </div>
      <div className="hintline">{tr('notif.enabled.hint')}</div>

      <div className="menu-head">{tr('notif.telegram')}</div>

      <div className="menu-row">
        <label htmlFor="notif-token">{tr('notif.token')}</label>
        <input className="input notif-token" id="notif-token" type="password"
          autoComplete="off" spellCheck={false}
          placeholder={tokenSet ? tr('notif.token.stored', { bot: botId || '?' })
            : tr('notif.token.placeholder')}
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onBlur={() => {
            // Only a non-empty value is a write. An emptied field is not a
            // request to disconnect the bot — Remove is.
            if (!token.trim()) return
            onTokenChange(token.trim())
            setToken('')
          }} />
      </div>
      <div className="hintline">
        {tr('notif.token.hint')}
        {tokenSet && (
          <>
            {' '}
            <button className="linklike" onClick={() => onTokenChange('')}>
              {tr('notif.token.remove')}
            </button>
          </>
        )}
      </div>

      <div className="menu-row">
        <label htmlFor="notif-chat">{tr('notif.chatId')}</label>
        <input className="input notif-chat" id="notif-chat" inputMode="numeric"
          autoComplete="off" spellCheck={false} value={chatId}
          onChange={(e) => onChatIdChange(e.target.value.trim())} />
      </div>
      <div className="hintline">{tr('notif.chatId.hint')}</div>

      <div className="menu-actions">
        <button className="btn ghost" onClick={() => { void runTest() }} disabled={testing}>
          {tr(testing ? 'notif.test.sending' : 'notif.test')}
        </button>
      </div>
      {result && (
        <div className={`hintline${result.ok ? '' : ' warn'}`} role="status">
          {result.detail}
        </div>
      )}

      <div className="menu-head">{tr('notif.rules')}</div>

      <div className="notif-rules">{DEFAULT_ON.map(rule)}</div>

      <div className="menu-head">{tr('notif.more')}</div>
      {/* The honest framing, and the reason this tier is a separate block
          rather than eight more rows: the app has a position on these, the
          position is "probably not", and saying so is more useful than a flat
          list that implies it has no view at all. */}
      <div className="hintline">{tr('notif.more.hint')}</div>
      <div className="notif-rules">{DEFAULT_OFF.map(rule)}</div>

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
        <label htmlFor="notif-evening">{tr('notif.eveningTime')}</label>
        <DateTimeInput type="time" className="input notif-time" id="notif-evening"
          value={eveningDraft}
          onChange={(e) => setEveningDraft(e.target.value)}
          onBlur={commitEvening}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { commitEvening(); (e.target as HTMLInputElement).blur() }
            if (e.key === 'Escape') { setEveningDraft(eveningTime); e.stopPropagation() }
          }} />
      </div>
      <div className="hintline">{tr('notif.eveningTime.hint')}</div>

      <div className="menu-row">
        <label htmlFor="notif-task-lead">{tr('notif.taskLead')}</label>
        <input className="input notif-lead" id="notif-task-lead" type="number"
          min={MIN_EVENT_LEAD_MINUTES} max={1440} step={1}
          value={taskLead}
          onChange={(e) => {
            const n = Number(e.target.value)
            if (Number.isFinite(n)) onTaskLeadChange(n)
          }} />
      </div>
      <div className="hintline">{tr('notif.taskLead.hint')}</div>

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
