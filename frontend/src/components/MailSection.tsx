// Email ingestion: where the mail is read from, which model reads it, what it
// is allowed to look at, and where the approved results go.
//
// A section body inside the settings panel, and SELF-FETCHING like
// ConnectionsSection rather than driven from App: nothing else in the app
// needs these values, they are not part of the account's synced preferences
// blob, and two copies of a credential's status in two places is how one of
// them goes stale. Every write answers with the whole payload and this
// replaces its copy with it, so what is on screen is always what the server
// last said and never this component's guess at it.
//
// THE CREDENTIALS ARE WRITE-ONLY, and the screen is built around that. The
// server never sends one back — only whether it is set and the last four
// characters — so a stored key shows as a disabled field with a placeholder
// and an empty value, and the only way to change it is to type a new one. A
// secret never enters this component's state except in the one box it is being
// typed into, and leaves it the moment it is saved.

import { useEffect, useState } from 'react'
import {
  api, AuthError, type List, type MailFolder, type MailImapTest,
  type MailModel, type MailSecretStatus, type MailSettingsPatch,
  type MailSettingsPayload, type MailStatus,
} from '../api'
import { useI18n } from '../i18n'
import { fmtWhen } from '../time'
import { useTimeFormat } from '../timeformat'
import { makeGuard } from '../util'

type Check = { ok: boolean; detail: string }
type ImapCheck = Check & { data: MailImapTest | null }

const OTHER = '__other__'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** One entry per line, and per comma where the entries cannot themselves hold
 *  one. An address, a domain and a pattern never contain a comma; a folder
 *  name or a rule (whose quoted text may) can, so those split on lines only. */
const splitList = (raw: string, commas: boolean) =>
  raw.split(commas ? /[\n,]+/ : /\n+/).map((x) => x.trim()).filter(Boolean)

const sameList = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((x, i) => x === b[i])

// INBOX is the one folder name IMAP compares case-insensitively (RFC 3501).
const isInbox = (name: string) => name.toUpperCase() === 'INBOX'
const sameFolder = (a: string, b: string) => (isInbox(a) && isInbox(b)) || a === b

export function MailSection({ onExpire, mailRev }: {
  onExpire: () => void
  /** Bumped by App on every `mail_updated` event. Only the status panel reads
   *  it: the settings are this section's own and only change when it writes. */
  mailRev?: number
}) {
  const { locale, t: tr } = useI18n()
  const tf = useTimeFormat()
  const guard = makeGuard(onExpire)
  const [payload, setPayload] = useState<MailSettingsPayload | null>(null)
  const [failed, setFailed] = useState(false)
  const [status, setStatus] = useState<MailStatus | null>(null)
  const [lists, setLists] = useState<List[]>([])
  const [calendars, setCalendars] = useState<List[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)

  const [models, setModels] = useState<MailModel[] | null>(null)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [modelsTick, setModelsTick] = useState(0)
  const [otherModel, setOtherModel] = useState(false)

  const [keyCheck, setKeyCheck] = useState<Check | null>(null)
  const [jevCheck, setJevCheck] = useState<Check | null>(null)
  const [imapCheck, setImapCheck] = useState<ImapCheck | null>(null)
  const [testing, setTesting] = useState<'key' | 'jev' | 'imap' | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanNote, setScanNote] = useState<Check | null>(null)

  useEffect(() => {
    let alive = true
    guard(() => api.mailSettings()).then((r) => {
      if (!alive) return
      if (r && typeof r === 'object' && r.settings) setPayload(r)
      else setFailed(true)
    })
    guard(() => api.lists()).then((r) => { if (alive && Array.isArray(r)) setLists(r) })
    guard(() => api.calendars()).then((r) => { if (alive && Array.isArray(r)) setCalendars(r) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The status is the one thing that changes without this section doing
  // anything, so it is re-read on every `mail_updated` and nothing else is.
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const r = await api.mailStatus()
        if (alive && r && typeof r === 'object') setStatus(r)
      } catch (e) {
        if (e instanceof AuthError) onExpire()
        // Any other failure leaves the last status standing: this panel is
        // informational, and a toast for it would cry wolf.
      }
    })()
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mailRev])

  const keySet = payload?.secrets.anthropic_api_key.set ?? false
  // The model list needs a key to ask with, and is asked again after one is
  // saved (`modelsTick`) because replacing a key leaves `set` true throughout
  // and the new key may be the one that can see a different list.
  useEffect(() => {
    if (!keySet) { setModels(null); setModelsError(null); return }
    let alive = true
    ;(async () => {
      try {
        const r = await api.mailModels()
        if (!alive) return
        if (r && Array.isArray(r.models)) { setModels(r.models); setModelsError(null) }
        else setModels(null)
      } catch (e) {
        if (!alive) return
        if (e instanceof AuthError) { onExpire(); return }
        setModels(null)
        setModelsError(message(e))
      }
    })()
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keySet, modelsTick])

  /** Write some settings and take the answer as the new truth. Resolves false
   *  when the server refused, so a field can put its draft back. */
  const save = async (patch: MailSettingsPatch): Promise<boolean> => {
    setSaveError(null)
    try {
      setPayload(await api.putMailSettings(patch))
      return true
    } catch (e) {
      if (e instanceof AuthError) { onExpire(); return false }
      setSaveError(message(e))
      return false
    }
  }

  if (!payload) {
    return failed
      ? <div className="empty" role="alert">{tr('mail.loadFailed')}</div>
      : <div className="empty">{tr('common.loading')}</div>
  }
  const s = payload.settings

  const saveSecret = async (name: 'anthropic_api_key' | 'imap_password' | 'typesafe_api_key',
    value: string) => {
    const ok = await save({ [name]: value })
    if (ok && name === 'anthropic_api_key') setModelsTick((n) => n + 1)
  }

  /** The three "press, wait, read the line under it" buttons. A failure is the
   *  server's own sentence in the warning colour — the 409s carry the reason
   *  (a bad key, a refused login) and that reason is the whole point. */
  const runCheck = async (which: 'key' | 'jev' | 'imap') => {
    setTesting(which)
    if (which === 'key') setKeyCheck(null)
    else if (which === 'jev') setJevCheck(null)
    else setImapCheck(null)
    try {
      if (which === 'imap') {
        const r = await api.testMailImap()
        setImapCheck({ ok: true, detail: r.detail, data: r })
      } else {
        const r = await (which === 'key' ? api.testMailAnthropic() : api.testMailTypesafe())
        ;(which === 'key' ? setKeyCheck : setJevCheck)({ ok: r.ok, detail: r.detail })
      }
    } catch (e) {
      if (e instanceof AuthError) { onExpire(); return }
      const failure = { ok: false, detail: message(e) }
      if (which === 'key') setKeyCheck(failure)
      else if (which === 'jev') setJevCheck(failure)
      else setImapCheck({ ...failure, data: null })
    } finally {
      setTesting(null)
    }
  }

  const scan = async () => {
    setScanning(true)
    setScanNote(null)
    try {
      await api.mailScan()
      setScanNote({ ok: true, detail: tr('mail.scan.queued') })
    } catch (e) {
      if (e instanceof AuthError) { onExpire(); return }
      // The 409 says why (switched off here, or for the whole deployment).
      setScanNote({ ok: false, detail: message(e) })
    } finally {
      setScanning(false)
    }
  }

  const toggle = (id: string, on: boolean, patch: (next: boolean) => MailSettingsPatch,
    labelKey: string) => (
    <div className="menu-row">
      <label htmlFor={id}>{tr(labelKey)}</label>
      <button className="menu-toggle" id={id} aria-pressed={on}
        onClick={() => { void save(patch(!on)) }}>
        {tr(on ? 'mail.on' : 'mail.off')}
      </button>
    </div>
  )

  const numberField = (id: string, labelKey: string, key: 'poll_minutes' | 'body_max_chars' | 'backfill_days',
    min: number, max: number) => (
    <div className="menu-row">
      <label htmlFor={id}>{tr(labelKey)}</label>
      <Draft id={id} type="number" className="input menu-num mail-num" min={min} max={max}
        value={String(s[key])}
        onCommit={async (raw) => {
          const n = Math.round(Number(raw))
          // An emptied or unreadable box snaps back rather than committing 0,
          // which the bounds would turn into a value nobody asked for.
          if (raw.trim() === '' || !Number.isFinite(n)) return false
          const clamped = Math.min(max, Math.max(min, n))
          if (clamped === s[key]) return false
          return save({ [key]: clamped })
        }} />
    </div>
  )

  const listField = (id: string, labelKey: string, key: 'self_addresses' | 'always_parse'
    | 'never_parse' | 'trusted_authserv_ids' | 'kind_rules' | 'folders', hintKey: string,
  commas = true) => (
    <>
      <div className="menu-row">
        <label htmlFor={id}>{tr(labelKey)}</label>
      </div>
      <Draft id={id} multiline rows={3} className="input mail-area"
        value={s[key].join('\n')}
        onCommit={async (raw) => {
          const next = splitList(raw, commas)
          if (sameList(next, s[key])) return false
          return save({ [key]: next })
        }} />
      <div className="hintline">{tr(hintKey)}</div>
    </>
  )

  const picker = (id: string, labelKey: string, value: string, firstKey: string, items: List[],
    key: 'task_list' | 'event_calendar') => (
    <div className="menu-row">
      <label htmlFor={id}>{tr(labelKey)}</label>
      <select className="menu-toggle mail-select" id={id} value={value}
        onChange={(e) => { void save({ [key]: e.target.value || null }) }}>
        <option value="">{tr(firstKey)}</option>
        {/* A saved choice that no longer exists stays visible as what it is,
            rather than the select quietly reading "First list" over a setting
            that still says otherwise. */}
        {value && !items.some((l) => l.id === value) && <option value={value}>{value}</option>}
        {items.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </div>
  )

  const checkLine = (c: Check | null) => c && (
    <div className={`hintline${c.ok ? '' : ' warn'}`} role="status">{c.detail}</div>
  )

  const imap = imapCheck?.data ?? null
  const authres = imap?.auth_results
  const ids = authres?.authserv_ids.join(', ') ?? ''
  const chosen = (f: MailFolder) => s.folders.some((x) => sameFolder(x, f.name))

  const toggleFolder = (f: MailFolder) => {
    const next = chosen(f)
      ? s.folders.filter((x) => !sameFolder(x, f.name))
      : [...s.folders, f.name]
    void save({ folders: next })
  }

  const inList = !!models && models.some((m) => m.id === s.model)
  const modelSelect = models && (otherModel || !inList ? OTHER : s.model)
  const when = (iso: string | null | undefined) =>
    iso ? fmtWhen(iso, tf, locale) : tr('mail.status.never')

  return (
    <>
      {saveError && (
        <div className="hintline warn" role="status">
          {tr('mail.saveFailed', { error: saveError })}
        </div>
      )}
      {!payload.deployment_enabled && (
        <div className="hintline warn">{tr('mail.deploymentOff')}</div>
      )}
      {!payload.secrets_backend.available && (
        <div className="hintline warn">
          {tr('mail.secretsUnavailable', { error: payload.secrets_backend.error ?? '' })}
        </div>
      )}

      {toggle('mail-enabled', s.enabled, (enabled) => ({ enabled }), 'mail.enabled')}

      <div className="menu-head">{tr('mail.head.anthropic')}</div>
      <SecretField id="mail-api-key" label={tr('mail.apiKey')}
        status={payload.secrets.anthropic_api_key} envVar="SMYLTE_ANTHROPIC_API_KEY"
        onSave={(v) => saveSecret('anthropic_api_key', v)}
        onClear={() => saveSecret('anthropic_api_key', '')} />

      <div className="menu-row">
        <label htmlFor="mail-model">{tr('mail.model')}</label>
        {models ? (
          <select className="menu-toggle mail-select" id="mail-model" value={modelSelect ?? ''}
            onChange={(e) => {
              if (e.target.value === OTHER) { setOtherModel(true); return }
              setOtherModel(false)
              void save({ model: e.target.value })
            }}>
            {models.map((m) => (
              <option key={m.id} value={m.id}>{`${m.display_name} — ${m.id}`}</option>
            ))}
            <option value={OTHER}>{tr('mail.model.other')}</option>
          </select>
        ) : (
          <Draft id="mail-model" className="input" value={s.model}
            onCommit={(raw) => commitText(raw, s.model, (model) => save({ model }))} />
        )}
      </div>
      {models && modelSelect === OTHER && (
        <div className="menu-row">
          <span />
          <Draft id="mail-model-other" className="input" value={inList ? '' : s.model}
            onCommit={(raw) => commitText(raw, s.model, (model) => save({ model }))} />
        </div>
      )}
      <div className="hintline">
        {keySet
          ? (modelsError ?? tr('mail.model.hint'))
          : tr('mail.model.needKey')}
      </div>

      <div className="menu-actions">
        <button className="btn ghost" disabled={testing === 'key' || !keySet}
          onClick={() => { void runCheck('key') }}>
          {tr(testing === 'key' ? 'mail.test.running' : 'mail.test.key')}
        </button>
      </div>
      {checkLine(keyCheck)}

      <div className="menu-head">{tr('mail.head.imap')}</div>
      <div className="menu-row">
        <label htmlFor="mail-imap-host">{tr('mail.imap.host')}</label>
        <Draft id="mail-imap-host" className="input" value={s.imap_host}
          onCommit={(raw) => commitText(raw, s.imap_host, (imap_host) => save({ imap_host }))} />
      </div>
      <div className="menu-row">
        <label htmlFor="mail-imap-port">{tr('mail.imap.port')}</label>
        <Draft id="mail-imap-port" type="number" className="input menu-num mail-num"
          min={1} max={65535} value={String(s.imap_port)}
          onCommit={async (raw) => {
            const n = Math.round(Number(raw))
            if (raw.trim() === '' || !Number.isFinite(n)) return false
            const imap_port = Math.min(65535, Math.max(1, n))
            return imap_port === s.imap_port ? false : save({ imap_port })
          }} />
      </div>
      <div className="menu-row">
        <label htmlFor="mail-imap-user">{tr('mail.imap.user')}</label>
        {/* Not trimmed to non-empty: an empty username is a legitimate thing to
            save, and the connection test is what says it is not enough. */}
        <Draft id="mail-imap-user" className="input" value={s.imap_username}
          onCommit={async (raw) => raw.trim() === s.imap_username ? false
            : save({ imap_username: raw.trim() })} />
      </div>
      <SecretField id="mail-imap-password" label={tr('mail.imap.password')}
        status={payload.secrets.imap_password} envVar="SMYLTE_MAIL_IMAP_PASSWORD"
        onSave={(v) => saveSecret('imap_password', v)}
        onClear={() => saveSecret('imap_password', '')} />
      <div className="hintline">{tr('mail.imap.hint')}</div>

      <div className="menu-row">
        <label htmlFor="mail-imap-tls">{tr('mail.imap.tls')}</label>
        <select className="menu-toggle mail-select" id="mail-imap-tls" value={s.imap_tls}
          onChange={(e) => { void save({ imap_tls: e.target.value as 'starttls' | 'ssl' }) }}>
          <option value="starttls">{tr('mail.imap.tls.starttls')}</option>
          <option value="ssl">{tr('mail.imap.tls.ssl')}</option>
        </select>
      </div>
      <div className="menu-row">
        <label htmlFor="mail-imap-cert">{tr('mail.imap.cert')}</label>
        <select className="menu-toggle mail-select" id="mail-imap-cert" value={s.imap_cert_mode}
          onChange={(e) => {
            void save({ imap_cert_mode: e.target.value as typeof s.imap_cert_mode })
          }}>
          <option value="system">{tr('mail.cert.system')}</option>
          <option value="pinned">{tr('mail.cert.pinned')}</option>
          <option value="insecure_localhost">{tr('mail.cert.insecure')}</option>
        </select>
      </div>
      {s.imap_cert_mode === 'pinned' && (
        <>
          <div className="menu-row">
            <label htmlFor="mail-imap-pem">{tr('mail.cert.pem')}</label>
          </div>
          <Draft id="mail-imap-pem" multiline rows={6} className="input mail-pem"
            value={s.imap_pinned_cert}
            onCommit={async (raw) => raw.trim() === s.imap_pinned_cert.trim() ? false
              : save({ imap_pinned_cert: raw.trim() })} />
          <div className="hintline">
            {payload.pinned_cert_fingerprint
              ? tr('mail.cert.fingerprint', { fp: payload.pinned_cert_fingerprint })
              : tr('mail.cert.pemHint')}
          </div>
        </>
      )}
      {s.imap_cert_mode === 'insecure_localhost' && (
        <div className="hintline warn" role="alert">{tr('mail.cert.insecureWarning')}</div>
      )}

      <div className="menu-actions">
        <button className="btn ghost" disabled={testing === 'imap'}
          onClick={() => { void runCheck('imap') }}>
          {tr(testing === 'imap' ? 'mail.test.running' : 'mail.test.imap')}
        </button>
      </div>
      {checkLine(imapCheck)}
      {authres?.checked && (
        <div className={`hintline${authres.present && authres.trusted ? '' : ' warn'}`} role="status">
          {authres.present
            ? tr(authres.trusted ? 'mail.imap.authres.ok' : 'mail.imap.authres.untrusted', { ids })
            : tr('mail.imap.authres.missing')}
        </div>
      )}

      <div className="menu-head">{tr('mail.head.read')}</div>
      {listField('mail-folders', 'mail.folders', 'folders', 'mail.folders.hint', false)}
      {imap && imap.folders.length > 0 && (
        <div className="mail-folders">
          {imap.folders.map((f) => (
            <button key={f.name} type="button" className="chip"
              aria-pressed={!f.excluded && chosen(f)} disabled={f.excluded}
              onClick={() => toggleFolder(f)}>
              {f.name}
              {f.excluded && <span className="mail-never">{tr('mail.folders.never')}</span>}
            </button>
          ))}
        </div>
      )}
      {listField('mail-self', 'mail.self', 'self_addresses', 'mail.self.hint')}
      {listField('mail-always', 'mail.always', 'always_parse', 'mail.always.hint')}
      <div className="hintline">{tr('mail.patterns.hint')}</div>
      {listField('mail-never', 'mail.never', 'never_parse', 'mail.patterns.hint')}
      {toggle('mail-notes-self', s.capture_notes_to_self,
        (capture_notes_to_self) => ({ capture_notes_to_self }), 'mail.notesSelf')}

      <div className="menu-row">
        <label htmlFor="mail-kind-decider">{tr('mail.kindDecider')}</label>
        <select className="menu-toggle mail-select" id="mail-kind-decider" value={s.kind_decider}
          onChange={(e) => {
            void save({ kind_decider: e.target.value as typeof s.kind_decider })
          }}>
          <option value="model">{tr('mail.kindDecider.model')}</option>
          <option value="jev">{tr('mail.kindDecider.jev')}</option>
          <option value="rules">{tr('mail.kindDecider.rules')}</option>
        </select>
      </div>
      {s.kind_decider === 'rules' && listField('mail-kind-rules', 'mail.kindRules', 'kind_rules',
        'mail.kindRules.hint', false)}
      {s.kind_decider === 'jev' && (
        <>
          <SecretField id="mail-typesafe-key" label={tr('mail.typesafeKey')}
            status={payload.secrets.typesafe_api_key} envVar="SMYLTE_TYPESAFE_API_KEY"
            onSave={(v) => saveSecret('typesafe_api_key', v)}
            onClear={() => saveSecret('typesafe_api_key', '')} />
          <div className="menu-row">
            <label htmlFor="mail-jev-model">{tr('mail.jevModel')}</label>
            <Draft id="mail-jev-model" className="input" value={s.jev_model}
              onCommit={(raw) => commitText(raw, s.jev_model, (jev_model) => save({ jev_model }))} />
          </div>
          <div className="hintline">{tr('mail.jev.hint')}</div>
          <div className="menu-actions">
            <button className="btn ghost"
              disabled={testing === 'jev' || !payload.secrets.typesafe_api_key.set}
              onClick={() => { void runCheck('jev') }}>
              {tr(testing === 'jev' ? 'mail.test.running' : 'mail.test.typesafe')}
            </button>
          </div>
          {checkLine(jevCheck)}
        </>
      )}

      <div className="menu-head">{tr('mail.head.where')}</div>
      {picker('mail-task-list', 'mail.taskList', s.task_list ?? '', 'mail.taskList.first',
        lists, 'task_list')}
      {picker('mail-event-cal', 'mail.eventCal', s.event_calendar ?? '', 'mail.eventCal.first',
        calendars, 'event_calendar')}

      <div className="menu-head">{tr('mail.head.schedule')}</div>
      {numberField('mail-poll', 'mail.poll', 'poll_minutes', 1, 1440)}
      {numberField('mail-body', 'mail.body', 'body_max_chars', 500, 100000)}
      {numberField('mail-backfill', 'mail.backfill', 'backfill_days', 0, 90)}

      <div className="menu-head">{tr('mail.head.advanced')}</div>
      {listField('mail-trusted', 'mail.trusted', 'trusted_authserv_ids', 'mail.trusted.hint')}

      <div className="menu-head">{tr('mail.head.status')}</div>
      <div className="menu-row">
        <label>{tr('mail.status.lastRun')}</label>
        <span className="menu-value">
          {when(status?.last_run_finished ?? status?.last_run_started)}
        </span>
      </div>
      <div className="menu-row">
        <label>{tr('mail.status.lastOk')}</label>
        <span className="menu-value">{when(status?.last_ok_at)}</span>
      </div>
      {status?.last_error && (
        <div className="hintline warn">{tr('mail.status.error', { error: status.last_error })}</div>
      )}
      {status && (
        <div className="hintline">
          {tr('mail.status.pending', { count: status.pending_count })}
        </div>
      )}
      <div className="menu-actions">
        <button className="btn ghost" disabled={scanning} onClick={() => { void scan() }}>
          {tr('mail.scan')}
        </button>
      </div>
      {checkLine(scanNote)}
    </>
  )
}

/** Trim, refuse empty, skip an unchanged value: the shape every single-value
 *  text field here commits in. False puts the draft back. */
async function commitText(raw: string, current: string, write: (v: string) => Promise<boolean>) {
  const v = raw.trim()
  if (!v || v === current) return false
  return write(v)
}

/** A text box that holds a DRAFT and commits on blur, and on Enter for a
 *  one-line box. Not on every keystroke: each commit is a PUT, and a half-typed
 *  host or port would be stored on the way to the real one — or, since the
 *  server REFUSES what it cannot read rather than filtering it, be a 422 that
 *  takes the rest of the patch with it. Escape puts the stored value back and
 *  stops there, so the key that abandons a field does not also close the sheet.
 *
 *  `onCommit` resolves false for "nothing to write, or the server said no":
 *  either way the box shows what is stored. */
function Draft({ id, value, onCommit, multiline, rows, type, className, min, max }: {
  id: string
  value: string
  onCommit: (next: string) => Promise<boolean>
  multiline?: boolean
  rows?: number
  type?: string
  className?: string
  min?: number
  max?: number
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => { setDraft(value) }, [value])
  const commit = async () => {
    if (draft === value) return
    if (!(await onCommit(draft))) setDraft(value)
  }
  const common = {
    id, className, value: draft, spellCheck: false, autoComplete: 'off',
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onBlur: () => { void commit() },
  }
  const escape = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setDraft(value) }
  }
  return multiline ? (
    <textarea {...common} rows={rows} onKeyDown={escape} />
  ) : (
    <input {...common} type={type ?? 'text'} min={min} max={max}
      onKeyDown={(e) => {
        // Enter ends the edit and the blur it causes does the commit, so the
        // two paths cannot both fire.
        if (e.key === 'Enter') { e.preventDefault(); (e.target as HTMLInputElement).blur() }
        escape(e)
      }} />
  )
}

/** One credential: stored, set by the environment, or waiting to be typed.
 *
 *  The input is never given a value to show. A stored credential reads as a
 *  disabled, empty box whose PLACEHOLDER says which one it is (the last four
 *  characters); typing a replacement is an explicit step; and the typed text is
 *  dropped from state the moment it is saved. Emptying the box is not a way to
 *  clear it — Clear is, and only Clear — so a stray click into a field the owner
 *  never meant to touch cannot disconnect anything. */
function SecretField({ id, label, status, envVar, onSave, onClear }: {
  id: string
  label: string
  status: MailSecretStatus
  envVar: string
  onSave: (value: string) => Promise<void>
  onClear: () => Promise<void>
}) {
  const { t: tr } = useI18n()
  const [replacing, setReplacing] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  // The environment wins over the store on the server, so there is nothing
  // here that could change the value: say who holds it and stop.
  if (status.source === 'env') {
    return (
      <div className="menu-row">
        <label htmlFor={id}>{label}</label>
        <span className="menu-value" id={id}>{tr('mail.secret.env', { name: envVar })}</span>
      </div>
    )
  }

  const locked = status.set && !replacing
  const save = async () => {
    const v = draft.trim()
    if (!v) return
    setBusy(true)
    try { await onSave(v) } finally {
      // Gone whether or not it was accepted: a refused credential is typed
      // again, not kept in a React state hook for the next attempt.
      setDraft('')
      setReplacing(false)
      setBusy(false)
    }
  }
  const clear = async () => {
    setBusy(true)
    try { await onClear() } finally { setBusy(false) }
  }

  return (
    <>
      <div className="menu-row">
        <label htmlFor={id}>{label}</label>
        {locked ? (
          <input className="input mail-secret" id={id} type="password" disabled value=""
            placeholder={tr('mail.secret.stored', { hint: status.hint ?? '…' })} readOnly />
        ) : (
          <input className="input mail-secret" id={id} type="password"
            autoComplete="new-password" spellCheck={false}
            placeholder={tr('mail.secret.placeholder')}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); void save() }
              if (e.key === 'Escape') {
                e.preventDefault(); e.stopPropagation()
                setDraft('')
                if (status.set) setReplacing(false)
              }
            }} />
        )}
      </div>
      <div className="menu-actions mail-secret-actions">
        {locked ? (
          <>
            <button className="btn ghost" disabled={busy} onClick={() => setReplacing(true)}>
              {tr('mail.secret.replace')}
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => { void clear() }}>
              {tr('mail.secret.clear')}
            </button>
          </>
        ) : (
          <>
            {replacing && (
              <button className="btn ghost" disabled={busy}
                onClick={() => { setDraft(''); setReplacing(false) }}>
                {tr('mail.secret.cancel')}
              </button>
            )}
            <button className="btn ghost" disabled={busy || !draft.trim()}
              onClick={() => { void save() }}>
              {tr('mail.secret.save')}
            </button>
          </>
        )}
      </div>
      {!locked && <div className="hintline">{tr('mail.secret.hint')}</div>}
    </>
  )
}
