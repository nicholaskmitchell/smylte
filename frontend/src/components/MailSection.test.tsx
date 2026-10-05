// The email settings section: that a credential is never shown or kept, that
// each control writes what it says, and that the checks report the server's own
// words.
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MailSection } from './MailSection'
import {
  api, HttpError, type MailImapTest, type MailSecretStatus, type MailSettingsPayload,
} from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})

const m = vi.mocked(api)

const unset: MailSecretStatus = { set: false, hint: null, source: null }
const stored = (hint: string): MailSecretStatus => ({ set: true, hint, source: 'store' })

function payload(
  over: { settings?: Partial<MailSettingsPayload['settings']>
    secrets?: Partial<MailSettingsPayload['secrets']> } = {},
): MailSettingsPayload {
  return {
    settings: {
      enabled: false, model: 'claude-haiku-4-5', imap_host: '127.0.0.1', imap_port: 1143,
      imap_username: 'me@proton.example', imap_tls: 'starttls', imap_cert_mode: 'system',
      imap_pinned_cert: '', folders: ['INBOX'], self_addresses: [], always_parse: [],
      never_parse: [], capture_notes_to_self: true, poll_minutes: 5, body_max_chars: 8000,
      backfill_days: 7, task_list: null, event_calendar: null,
      trusted_authserv_ids: ['protonmail.ch', '*.protonmail.ch'],
      auto_accept_min_confidence: null, kind_decider: 'jev', kind_rules: [],
      jev_model: 'jev-latest', dedup_decider: 'jev', anthropic_workspace_id: '', ...over.settings,
    },
    secrets: {
      anthropic_api_key: unset, imap_password: unset, typesafe_api_key: unset, ...over.secrets,
    },
    secrets_backend: { name: 'file', choice: 'auto', available: true, error: null },
    pinned_cert_fingerprint: null,
    deployment_enabled: true,
    defaults: { model: 'claude-haiku-4-5' },
  }
}

const KEY = 'sk-ant-api03-' + 'A'.repeat(40) + 'WXYZ'

async function show(p: MailSettingsPayload = payload()) {
  m.mailSettings.mockResolvedValue(p)
  const onExpire = vi.fn()
  const view = render(<MailSection onExpire={onExpire} />)
  await screen.findByText('Anthropic')
  return { onExpire, ...view }
}

const el = (id: string) => document.getElementById(id)!

beforeEach(() => {
  vi.clearAllMocks()
  m.lists.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.mailStatus.mockResolvedValue({
    enabled: false, deployment_enabled: true, running: false, pending_count: 0,
    cursors: [], counts: {},
  })
  m.mailModels.mockResolvedValue({ models: [] })
  m.putMailSettings.mockResolvedValue(payload())
})
afterEach(cleanup)

describe('a stored credential', () => {
  const stored_ = () => payload({ secrets: { anthropic_api_key: stored('…WXYZ') } })

  it('is a disabled, empty password field that says which one it is', async () => {
    await show(stored_())
    const input = el('mail-api-key') as HTMLInputElement
    expect(input.type).toBe('password')
    expect(input.value).toBe('')
    expect(input).toBeDisabled()
    expect(input.placeholder).toBe('Stored — …WXYZ')
    // Nothing on the page carries more of it than the hint the server sent.
    expect(document.body.textContent).not.toContain('sk-ant')
  })

  it('Replace reveals an empty, enabled field, and Save writes only what was typed', async () => {
    const user = userEvent.setup()
    await show(stored_())
    await user.click(screen.getByRole('button', { name: 'Replace' }))
    const input = el('mail-api-key') as HTMLInputElement
    expect(input).toBeEnabled()
    expect(input.value).toBe('')
    expect(input.autocomplete).toBe('new-password')
    // The Bridge password above it is unset, so it has a Save of its own; the
    // API key's is the first in the page.
    const save = () => screen.getAllByRole('button', { name: 'Save' })[0]
    expect(save()).toBeDisabled()
    await user.type(input, 'new')
    await user.click(save())
    expect(m.putMailSettings).toHaveBeenCalledWith({ anthropic_api_key: 'new' })
    // And it is gone from the box the moment it is saved.
    await waitFor(() => expect((el('mail-api-key') as HTMLInputElement).value).toBe(''))
  })

  it('Clear sends an empty string', async () => {
    const user = userEvent.setup()
    await show(stored_())
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(m.putMailSettings).toHaveBeenCalledWith({ anthropic_api_key: '' })
  })

  it('Cancel puts the stored field back without writing', async () => {
    const user = userEvent.setup()
    await show(stored_())
    await user.click(screen.getByRole('button', { name: 'Replace' }))
    await user.type(el('mail-api-key'), 'half')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(el('mail-api-key')).toBeDisabled()
    expect(m.putMailSettings).not.toHaveBeenCalled()
  })

  it('an unset one is an enabled field with a Save that waits for text', async () => {
    await show()
    expect(el('mail-api-key')).toBeEnabled()
    expect(screen.getAllByRole('button', { name: 'Save' })[0]).toBeDisabled()
  })
})

describe('a credential set by the server environment', () => {
  it('says so, with no field and no buttons to change it', async () => {
    await show(payload({ secrets: {
      anthropic_api_key: { set: true, hint: '…WXYZ', source: 'env' },
    } }))
    expect(screen.getByText('Set by SMYLTE_ANTHROPIC_API_KEY in the server environment'))
      .toBeInTheDocument()
    expect(el('mail-api-key').tagName).not.toBe('INPUT')
    expect(screen.queryByRole('button', { name: 'Replace' })).toBeNull()
  })
})

describe('the certificate setting', () => {
  it('warns, and writes, when checks are switched off', async () => {
    const user = userEvent.setup()
    m.putMailSettings.mockResolvedValue(payload({ settings: { imap_cert_mode: 'insecure_localhost' } }))
    await show()
    expect(screen.queryByRole('alert')).toBeNull()
    await user.selectOptions(el('mail-imap-cert'), 'insecure_localhost')
    expect(m.putMailSettings).toHaveBeenCalledWith({ imap_cert_mode: 'insecure_localhost' })
    expect(await screen.findByRole('alert')).toHaveTextContent('Certificate checks are off')
  })

  it('asks for the certificate when pinning', async () => {
    await show(payload({ settings: { imap_cert_mode: 'pinned' } }))
    expect(el('mail-imap-pem').tagName).toBe('TEXTAREA')
  })
})

describe('saving', () => {
  it('commits a text field on blur, not on every keystroke', async () => {
    const user = userEvent.setup()
    await show()
    const host = el('mail-imap-host') as HTMLInputElement
    await user.clear(host)
    await user.type(host, 'bridge.lan')
    expect(m.putMailSettings).not.toHaveBeenCalled()
    await user.tab()
    expect(m.putMailSettings).toHaveBeenCalledWith({ imap_host: 'bridge.lan' })
  })

  it('writes the optional workspace id on blur, and an emptied box clears it', async () => {
    const user = userEvent.setup()
    await show()
    const ws = el('mail-workspace') as HTMLInputElement
    expect(ws.value).toBe('')
    expect(screen.getByText(/Leave empty unless Anthropic says/)).toBeInTheDocument()
    await user.type(ws, ' wrkspc_01ABC ')
    expect(m.putMailSettings).not.toHaveBeenCalled()
    await user.tab()
    expect(m.putMailSettings).toHaveBeenCalledWith({ anthropic_workspace_id: 'wrkspc_01ABC' })
    cleanup()
    m.putMailSettings.mockClear()
    await show(payload({ settings: { anthropic_workspace_id: 'wrkspc_01ABC' } }))
    const stored = el('mail-workspace') as HTMLInputElement
    expect(stored.value).toBe('wrkspc_01ABC')
    await user.clear(stored)
    await user.tab()
    expect(m.putMailSettings).toHaveBeenCalledWith({ anthropic_workspace_id: '' })
  })

  it('splits a list on lines and commas', async () => {
    const user = userEvent.setup()
    await show()
    await user.type(el('mail-self'), 'me@x.example, alias@x.example\nother@x.example')
    await user.tab()
    expect(m.putMailSettings).toHaveBeenCalledWith(
      { self_addresses: ['me@x.example', 'alias@x.example', 'other@x.example'] })
  })

  it('does not split a rule on its commas', async () => {
    const user = userEvent.setup()
    await show(payload({ settings: { kind_decider: 'rules' } }))
    await user.type(el('mail-kind-rules'), 'subject:"a, b" -> event')
    await user.tab()
    expect(m.putMailSettings).toHaveBeenCalledWith({ kind_rules: ['subject:"a, b" -> event'] })
  })

  it('puts the draft back and says why when the server refuses', async () => {
    const user = userEvent.setup()
    m.putMailSettings.mockRejectedValue(new HttpError(422, 'rule 1: unknown field'))
    await show()
    const host = el('mail-imap-host') as HTMLInputElement
    await user.clear(host)
    await user.type(host, 'nope')
    await user.tab()
    const warn = await screen.findByText(/Couldn’t save: rule 1: unknown field/)
    expect(warn).toHaveClass('warn')
    expect(warn).toHaveAttribute('role', 'status')
    expect(host.value).toBe('127.0.0.1')
  })

  it('Escape reverts the draft and does not leave the section', async () => {
    const user = userEvent.setup()
    await show()
    const host = el('mail-imap-host') as HTMLInputElement
    await user.type(host, 'xyz')
    await user.keyboard('{Escape}')
    expect(host.value).toBe('127.0.0.1')
    expect(m.putMailSettings).not.toHaveBeenCalled()
  })

  it('clamps a number into its range', async () => {
    const user = userEvent.setup()
    await show()
    const poll = el('mail-poll') as HTMLInputElement
    await user.clear(poll)
    await user.type(poll, '99999')
    await user.tab()
    expect(m.putMailSettings).toHaveBeenCalledWith({ poll_minutes: 1440 })
  })

  it('toggles reading on', async () => {
    const user = userEvent.setup()
    await show()
    await user.click(el('mail-enabled'))
    expect(m.putMailSettings).toHaveBeenCalledWith({ enabled: true })
  })

  it('warns when the deployment has it switched off', async () => {
    const p = payload()
    p.deployment_enabled = false
    await show(p)
    expect(screen.getByText(/SMYLTE_MAIL_ENABLED=false/)).toHaveClass('warn')
  })
})

describe('the API key check', () => {
  const withKey = () => payload({ secrets: { anthropic_api_key: stored('…WXYZ') } })

  it('shows what the server said on success', async () => {
    const user = userEvent.setup()
    m.testMailAnthropic.mockResolvedValue({ ok: true, detail: 'The key works.' })
    await show(withKey())
    await user.click(screen.getByRole('button', { name: 'Test API key' }))
    const line = await screen.findByText('The key works.')
    expect(line).not.toHaveClass('warn')
  })

  it('shows the refusal as a warning', async () => {
    const user = userEvent.setup()
    m.testMailAnthropic.mockRejectedValue(new HttpError(409, 'Anthropic rejected the key'))
    await show(withKey())
    await user.click(screen.getByRole('button', { name: 'Test API key' }))
    const line = await screen.findByText('Anthropic rejected the key')
    expect(line).toHaveClass('warn')
    expect(line).toHaveAttribute('role', 'status')
  })
})

describe('the connection check', () => {
  const found: MailImapTest = {
    ok: true, detail: 'Connected to Bridge.',
    folders: [
      { name: 'INBOX', special: [], excluded: false, selected: true },
      { name: 'Sent', special: ['\\Sent'], excluded: true, selected: false },
      { name: 'Labels/School', special: [], excluded: false, selected: false },
    ],
    auth_results: { checked: true, present: true, authserv_ids: ['mailin008.protonmail.ch'], trusted: true },
  }

  it('lists the folders as chips, and refuses the ones that are never read', async () => {
    const user = userEvent.setup()
    m.testMailImap.mockResolvedValue(found)
    await show()
    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText('Connected to Bridge.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^INBOX/ })).toHaveAttribute('aria-pressed', 'true')
    const sent = screen.getByRole('button', { name: /^Sent/ })
    expect(sent).toBeDisabled()
    expect(sent).toHaveTextContent('never read')
    expect(screen.getByRole('button', { name: /^Labels\/School/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('writes the folder list when a chip is pressed', async () => {
    const user = userEvent.setup()
    m.testMailImap.mockResolvedValue(found)
    await show()
    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    await user.click(await screen.findByRole('button', { name: /^Labels\/School/ }))
    expect(m.putMailSettings).toHaveBeenCalledWith({ folders: ['INBOX', 'Labels/School'] })
  })

  it('says whether the sender headers come through and are trusted', async () => {
    const user = userEvent.setup()
    m.testMailImap.mockResolvedValue(found)
    await show()
    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/come through \(mailin008\.protonmail\.ch\)/)).not.toHaveClass('warn')
    cleanup()
    m.testMailImap.mockResolvedValue({
      ...found, auth_results: { ...found.auth_results, trusted: false },
    })
    await show()
    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/which isn’t in the trusted list/)).toHaveClass('warn')
  })

  it('reports a failed login in the warning colour', async () => {
    const user = userEvent.setup()
    m.testMailImap.mockRejectedValue(new HttpError(409, 'the server rejected the login'))
    await show()
    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText('the server rejected the login')).toHaveClass('warn')
  })
})

describe('the model picker', () => {
  const withKey = (model = 'claude-haiku-4-5') =>
    payload({ settings: { model }, secrets: { anthropic_api_key: stored('…WXYZ') } })
  const models = {
    models: [
      { id: 'claude-haiku-4-5', display_name: 'Claude Haiku 4.5' },
      { id: 'claude-sonnet-4-5', display_name: 'Claude Sonnet 4.5' },
    ],
  }

  it('offers the models the key can see, and Other…', async () => {
    m.mailModels.mockResolvedValue(models)
    await show(withKey())
    const select = (await waitFor(() => {
      const s = el('mail-model')
      expect(s.tagName).toBe('SELECT')
      return s
    })) as HTMLSelectElement
    expect([...select.options].map((o) => o.value))
      .toEqual(['claude-haiku-4-5', 'claude-sonnet-4-5', '__other__'])
    expect(select.value).toBe('claude-haiku-4-5')
    expect(screen.getByRole('option', { name: 'Claude Haiku 4.5 — claude-haiku-4-5' })).toBeInTheDocument()
  })

  it('writes the model that was picked', async () => {
    const user = userEvent.setup()
    m.mailModels.mockResolvedValue(models)
    await show(withKey())
    await screen.findByRole('option', { name: /Sonnet/ })
    await user.selectOptions(el('mail-model'), 'claude-sonnet-4-5')
    expect(m.putMailSettings).toHaveBeenCalledWith({ model: 'claude-sonnet-4-5' })
  })

  it('reveals a text box for Other…', async () => {
    const user = userEvent.setup()
    m.mailModels.mockResolvedValue(models)
    await show(withKey())
    await screen.findByRole('option', { name: /Sonnet/ })
    expect(document.getElementById('mail-model-other')).toBeNull()
    await user.selectOptions(el('mail-model'), '__other__')
    expect(el('mail-model-other')).toBeInTheDocument()
  })

  it('shows a model that is not in the list as Other…, holding it', async () => {
    m.mailModels.mockResolvedValue(models)
    await show(withKey('claude-future-9'))
    await screen.findByRole('option', { name: /Sonnet/ })
    expect((el('mail-model') as HTMLSelectElement).value).toBe('__other__')
    expect((el('mail-model-other') as HTMLInputElement).value).toBe('claude-future-9')
  })

  it('is a plain text box, with the reason, when there is no key', async () => {
    await show()
    expect(el('mail-model').tagName).toBe('INPUT')
    expect(m.mailModels).not.toHaveBeenCalled()
    expect(screen.getByText(/Save an API key to choose/)).toBeInTheDocument()
  })

  it('falls back to the text box when the list cannot be fetched', async () => {
    m.mailModels.mockRejectedValue(new HttpError(409, 'Anthropic rejected the key'))
    await show(withKey())
    expect(await screen.findByText('Anthropic rejected the key')).toBeInTheDocument()
    expect(el('mail-model').tagName).toBe('INPUT')
  })
})

describe('task or event', () => {
  it('shows the rules box only when rules decide', async () => {
    const user = userEvent.setup()
    m.putMailSettings.mockResolvedValue(payload({ settings: { kind_decider: 'rules' } }))
    await show(payload({ settings: { kind_decider: 'model' } }))
    expect(document.getElementById('mail-kind-rules')).toBeNull()
    await user.selectOptions(el('mail-kind-decider'), 'rules')
    expect(m.putMailSettings).toHaveBeenCalledWith({ kind_decider: 'rules' })
    expect(await screen.findByLabelText('Rules')).toBe(el('mail-kind-rules'))
  })

  it('shows the TypeSafe fields whichever decider is chosen', async () => {
    await show(payload({ settings: { kind_decider: 'model', dedup_decider: 'model' } }))
    expect(await screen.findByLabelText('TypeSafe API key')).toBe(el('mail-typesafe-key'))
    expect(el('mail-jev-model')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Test TypeSafe key' })).toBeInTheDocument()
  })

  it('choosing TypeSafe Jev writes it', async () => {
    const user = userEvent.setup()
    m.putMailSettings.mockResolvedValue(payload({ settings: { kind_decider: 'jev' } }))
    await show(payload({ settings: { kind_decider: 'model' } }))
    expect((el('mail-kind-decider') as HTMLSelectElement).value).toBe('model')
    await user.selectOptions(el('mail-kind-decider'), 'jev')
    expect(m.putMailSettings).toHaveBeenCalledWith({ kind_decider: 'jev' })
  })

  it('writes the duplicate-check decider', async () => {
    const user = userEvent.setup()
    m.putMailSettings.mockResolvedValue(payload({ settings: { dedup_decider: 'model' } }))
    await show()
    expect((el('mail-dedup-decider') as HTMLSelectElement).value).toBe('jev')
    expect(screen.getByRole('option', { name: 'TypeSafe Jev, Claude when unsure' })).toBeInTheDocument()
    await user.selectOptions(el('mail-dedup-decider'), 'model')
    expect(m.putMailSettings).toHaveBeenCalledWith({ dedup_decider: 'model' })
  })

  it('stores the TypeSafe key write-only', async () => {
    const user = userEvent.setup()
    await show(payload({ settings: { kind_decider: 'jev' } }))
    await user.type(el('mail-typesafe-key'), 'ts-secret-key')
    await user.click(screen.getAllByRole('button', { name: 'Save' })
      .find((b) => !(b as HTMLButtonElement).disabled)!)
    expect(m.putMailSettings).toHaveBeenCalledWith({ typesafe_api_key: 'ts-secret-key' })
  })

  it('the TypeSafe check reports a pass and a failure', async () => {
    const user = userEvent.setup()
    const p = payload({ settings: { kind_decider: 'jev' }, secrets: { typesafe_api_key: stored('…1234') } })
    m.testMailTypesafe.mockResolvedValueOnce({ ok: true, detail: 'The TypeSafe key works.' })
    await show(p)
    await user.click(screen.getByRole('button', { name: 'Test TypeSafe key' }))
    expect(await screen.findByText('The TypeSafe key works.')).not.toHaveClass('warn')
    m.testMailTypesafe.mockRejectedValueOnce(new HttpError(409, 'TypeSafe rejected the API key'))
    await user.click(screen.getByRole('button', { name: 'Test TypeSafe key' }))
    expect(await screen.findByText('TypeSafe rejected the API key')).toHaveClass('warn')
  })

  it('writes the Jev model on blur', async () => {
    const user = userEvent.setup()
    await show(payload({ settings: { kind_decider: 'jev' } }))
    const model = el('mail-jev-model') as HTMLInputElement
    await user.clear(model)
    await user.type(model, 'jev-preview')
    await user.tab()
    expect(m.putMailSettings).toHaveBeenCalledWith({ jev_model: 'jev-preview' })
  })
})

describe('where it goes, and status', () => {
  it('offers the owner\'s lists and writes null for the default', async () => {
    const user = userEvent.setup()
    m.lists.mockResolvedValue([{
      id: 'home', href: '/home/', name: 'Home', is_task_list: true, is_calendar: false,
      open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
    }])
    await show(payload({ settings: { task_list: 'home' } }))
    const select = el('mail-task-list') as HTMLSelectElement
    await waitFor(() => expect(select.value).toBe('home'))
    await user.selectOptions(select, '')
    expect(m.putMailSettings).toHaveBeenCalledWith({ task_list: null })
  })

  it('queues a scan, and shows the reason when it is refused', async () => {
    const user = userEvent.setup()
    m.mailScan.mockResolvedValueOnce({ queued: true })
    await show()
    await user.click(screen.getByRole('button', { name: 'Check now' }))
    expect(await screen.findByText('Checking…')).not.toHaveClass('warn')
    m.mailScan.mockRejectedValueOnce(new HttpError(409, 'email ingestion is switched off in Settings'))
    await user.click(screen.getByRole('button', { name: 'Check now' }))
    expect(await screen.findByText('email ingestion is switched off in Settings')).toHaveClass('warn')
  })

  it('shows the last error and how many suggestions are waiting', async () => {
    m.mailStatus.mockResolvedValue({
      enabled: true, deployment_enabled: true, running: false, pending_count: 2,
      last_error: 'could not log in', cursors: [], counts: {},
    })
    await show()
    expect(await screen.findByText('Last error: could not log in')).toHaveClass('warn')
    expect(screen.getByText('2 suggestions waiting')).toBeInTheDocument()
  })

  it('re-reads the status when told the mail changed', async () => {
    m.mailSettings.mockResolvedValue(payload())
    const { rerender } = render(<MailSection onExpire={vi.fn()} mailRev={0} />)
    await screen.findByText('Anthropic')
    const before = m.mailStatus.mock.calls.length
    rerender(<MailSection onExpire={vi.fn()} mailRev={1} />)
    await waitFor(() => expect(m.mailStatus.mock.calls.length).toBe(before + 1))
  })
})

it('hands an expired session to onExpire', async () => {
  const { AuthError } = await import('../api')
  m.mailSettings.mockRejectedValue(new AuthError('expired'))
  const onExpire = vi.fn()
  render(<MailSection onExpire={onExpire} />)
  await waitFor(() => expect(onExpire).toHaveBeenCalled())
})

// Kept so a stray literal key in a fixture above is caught if it ever leaks
// into a rendered page.
it('never renders a key it was not given', async () => {
  await show()
  expect(document.body.textContent).not.toContain(KEY)
})
