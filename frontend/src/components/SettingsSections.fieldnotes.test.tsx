import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NotificationsSection } from './NotificationsSection'
import { MailSection } from './MailSection'
import { DisplaysSection } from './DisplaysSection'
import { SharesSection } from './SharesSection'
import { DeveloperSection } from './DeveloperSection'
import { AppearancePanel } from './AppearancePanel'
import {
  api, HttpError, type Display, type MailSecretStatus, type MailSettingsPayload, type Share,
} from '../api'

// The second half of Settings under Field notes, the design that names things
// and does not explain them: Notifications, Mail, Displays, Shares, Developer
// and the Appearance editor. The preset behaviour is each section's own test
// file, and is not repeated here.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})

const m = vi.mocked(api)

beforeEach(() => {
  vi.clearAllMocks()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
})

afterEach(() => {
  cleanup()
  document.documentElement.removeAttribute('data-surface')
})

const noTitles = () => expect(document.querySelectorAll('[title]')).toHaveLength(0)

describe('Notifications under Field notes', () => {
  const show = (over: Partial<Parameters<typeof NotificationsSection>[0]> = {}) => render(
    <NotificationsSection
      enabled onEnabledChange={vi.fn()}
      chatId="8517516151" onChatIdChange={vi.fn()}
      tokenSet={false} botId="" onTokenChange={vi.fn()}
      onExpire={vi.fn()}
      triggers={{}} onTriggersChange={vi.fn()}
      digestTime="07:30" onDigestTimeChange={vi.fn()}
      eventLead={10} onEventLeadChange={vi.fn()}
      eveningTime="21:00" onEveningTimeChange={vi.fn()}
      taskLead={30} onTaskLeadChange={vi.fn()}
      homeTz="America/New_York"
      {...over} />)

  it('drops the explanations, the per-rule lines and the Default tails', () => {
    show({ triggers: { habits_outstanding: true } })
    // The folds stay mounted while closed, so their rows are in the page.
    for (const gone of [
      /Needs a bot token and a chat id/, /Your user id, or a negative number/,
      /Today’s events, what’s due and the overdue count/,
      /In the evening, the habits still open today/, /Sent at the evening time below/,
      /For the two evening rules above/, /For “Before every task is due”/,
      /Minutes before an event starts/, /Skipped if it would arrive more than four hours late/,
      /After eight buzzing messages/, /Default:/,
    ]) expect(screen.queryByText(gone), String(gone)).toBeNull()
    expect(document.querySelectorAll('.notif-rule .hintline')).toHaveLength(0)
    noTitles()
  })

  it('keeps the token note, which says it is not shown again, and the missing-zone warning', () => {
    show({ homeTz: '', tokenSet: true, botId: '123' })
    expect(screen.getByText(/It isn’t shown again after saving/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove it' })).toBeInTheDocument()
    expect(document.querySelector('.hintline.warn')).toHaveTextContent(/Set a home timezone/)
  })
})

describe('Mail under Field notes', () => {
  const unset: MailSecretStatus = { set: false, hint: null, source: null }
  const payload = (
    over: Partial<MailSettingsPayload['settings']> = {},
    secrets: Partial<MailSettingsPayload['secrets']> = {},
    fingerprint: string | null = null,
  ): MailSettingsPayload => ({
    settings: {
      enabled: false, model: 'claude-haiku-4-5', imap_host: '127.0.0.1', imap_port: 1143,
      imap_username: 'me@proton.example', imap_tls: 'starttls', imap_cert_mode: 'system',
      imap_pinned_cert: '', folders: ['INBOX'], self_addresses: [], always_parse: [],
      never_parse: [], capture_notes_to_self: true, poll_minutes: 5, body_max_chars: 8000,
      backfill_days: 7, task_list: null, event_calendar: null,
      trusted_authserv_ids: ['protonmail.ch'], auto_accept_min_confidence: null,
      kind_decider: 'rules', kind_rules: [], jev_model: 'jev-latest', dedup_decider: 'jev',
      anthropic_workspace_id: '', ...over,
    },
    secrets: { anthropic_api_key: unset, imap_password: unset, typesafe_api_key: unset, ...secrets },
    secrets_backend: { name: 'file', choice: 'auto', available: true, error: null },
    pinned_cert_fingerprint: fingerprint,
    deployment_enabled: true,
    defaults: { model: 'claude-haiku-4-5' },
  })

  const show = async (p: MailSettingsPayload) => {
    m.mailSettings.mockResolvedValue(p)
    render(<MailSection onExpire={vi.fn()} />)
    await screen.findByText('Anthropic')
  }

  beforeEach(() => {
    m.lists.mockResolvedValue([])
    m.calendars.mockResolvedValue([])
    m.mailStatus.mockResolvedValue({
      enabled: false, deployment_enabled: true, running: false, pending_count: 0,
      cursors: [], counts: {},
    })
    m.mailModels.mockResolvedValue({ models: [] })
  })

  it('drops the format hints, the workspace, Bridge and Jev notes', async () => {
    await show(payload({ kind_decider: 'rules' }))
    for (const gone of [
      /One per line: an address, a domain/, /Only needed if Anthropic asks/,
      /Save an API key to choose from/, /Use Bridge’s username and password/,
      /Every address and alias you send from/, /Read even if it looks like bulk mail/,
      /Jev decides task or event/,
    ]) expect(screen.queryByText(gone), String(gone)).toBeNull()
    noTitles()
  })

  it('keeps the rebind, the enabled and the secret notes', async () => {
    await show(payload())
    expect(screen.getByText(/clears the saved password/)).toBeInTheDocument()
    expect(screen.getByText(/skipped mail isn’t read again/)).toBeInTheDocument()
    expect(screen.getAllByText('Not shown again after saving.').length).toBeGreaterThan(0)
  })

  it('keeps the insecure-certificate warning', async () => {
    await show(payload({ imap_cert_mode: 'insecure_localhost' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/Certificate checks are off/)
    expect(screen.getByRole('alert')).toHaveClass('hintline', 'warn')
  })

  it('says only the fingerprint beside a pinned certificate, never the export steps', async () => {
    await show(payload({ imap_cert_mode: 'pinned' }))
    expect(screen.queryByText(/Export TLS certificates/)).toBeNull()
    cleanup()
    await show(payload({ imap_cert_mode: 'pinned' }, {}, 'AB:CD'))
    expect(screen.getByText('SHA-256 AB:CD')).toBeInTheDocument()
    expect(screen.queryByText(/Export TLS certificates/)).toBeNull()
  })

  it('says only a failed model list, not that the model applies from the next email', async () => {
    const key: MailSecretStatus = { set: true, hint: '…WXYZ', source: 'store' }
    m.mailModels.mockResolvedValue({ models: [{ id: 'claude-haiku-4-5', display_name: 'Haiku' }] })
    await show(payload({}, { anthropic_api_key: key }))
    await screen.findByRole('combobox', { name: 'Model' })
    expect(screen.queryByText('Applies from the next email.')).toBeNull()
    cleanup()
    m.mailModels.mockRejectedValue(new HttpError(409, 'Anthropic rejected the key'))
    await show(payload({}, { anthropic_api_key: key }))
    expect(await screen.findByText('Anthropic rejected the key')).toBeInTheDocument()
    expect(screen.queryByText('Applies from the next email.')).toBeNull()
  })
})

describe('Displays under Field notes', () => {
  const DISPLAY: Display = {
    token: 'tok-hallway', name: 'Hallway', mode: 'calendar', palette: 'eink',
    calendars: ['work'], lists: [], hide_done_habits: true, hide_done_tasks: true,
    refresh_seconds: 300, panel_width: 100, panel_height: 100, rotation: 0,
    panel_too_small: true, enabled: true, switchable: true, last_seen_at: null,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
  } as Display

  const open = async () => {
    m.calendars.mockResolvedValue([{ id: 'work', name: 'Work' }, { id: 'home', name: 'Home' }] as never)
    m.lists.mockResolvedValue([] as never)
    m.displays.mockResolvedValue([DISPLAY] as never)
    render(<DisplaysSection onExpire={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
  }

  it('drops the explanations and the title on the last chip', async () => {
    await open()
    for (const gone of [
      /The current item from today’s plan/, /Lets the desk unit’s key switch/,
      /Black and white only/, /The count still includes them/, /A microcontroller can fetch/,
      /Use \.bin on a microcontroller/, /While off, the URL stops working/,
      /The name is shown on the screen/,
    ]) expect(screen.queryByText(gone), String(gone)).toBeNull()
    // The chip is still there, and still refuses to be turned off.
    expect(screen.getByRole('button', { name: 'Work' })).toBeDisabled()
    noTitles()
  })

  it('keeps the e-ink damage warning, the URL privacy note, the rotate note and the size alert', async () => {
    await open()
    expect(screen.getByText(/E-ink panels can be damaged/)).toBeInTheDocument()
    expect(screen.getByText(/Anyone with this URL can see/)).toBeInTheDocument()
    expect(screen.getByText(/A new URL keeps this display’s settings/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/Too small for a month/)
  })
})

describe('Shares under Field notes', () => {
  const SHARE: Share = {
    id: 'a'.repeat(32), name: 'Mum', token: 'tok-mum', url: null,
    lists: [], calendars: [], show_focus: false, horizon_days: 7,
    enabled: true, switched_off_by_password: true, last_seen_at: null,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
  }

  const open = async (share: Share = SHARE, archived: string[] = []) => {
    m.calendars.mockResolvedValue([{ id: 'work', name: 'Work' }, { id: 'old', name: 'Old' }] as never)
    m.lists.mockResolvedValue([{ id: 'inbox', name: 'Inbox' }] as never)
    m.shares.mockResolvedValue([share] as never)
    m.sharePreview.mockResolvedValue({
      v: 1, generated_at: '2026-10-26T14:00:00.000Z', poll_seconds: 30, day: '2026-10-26', days: 7,
      focus: null, calendars: [], events: [], events_more: 0, lists: [],
    } as never)
    render(<SharesSection onExpire={vi.fn()} archived={archived} />)
    const row = (await screen.findByText('Mum')).closest('.disp') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
  }

  it('drops the explanations, and the title on an archived calendar', async () => {
    await open({ ...SHARE, calendars: ['old'] }, ['old'])
    for (const gone of [/Only you see this name/, /While off, the link stops working/])
      expect(screen.queryByText(gone), String(gone)).toBeNull()
    // What a share shows other people is a privacy note, so these stay.
    for (const kept of [/Items marked private in other apps show as Busy/, /Whether you’re focusing or on a break/])
      expect(screen.getByText(kept), String(kept)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Old' })).toHaveClass('is-archived')
    noTitles()
  })

  it('drops the preview note but keeps what the preview shows', async () => {
    await open()
    await userEvent.click(screen.getByRole('button', { name: 'See what they see' }))
    await waitFor(() => expect(document.querySelector('.share-preview')).not.toBeNull())
    expect(screen.queryByText(/exactly what they see right now/i)).toBeNull()
  })

  it('keeps the link privacy note, the rotate note and the status warnings', async () => {
    await open()
    expect(screen.getByText(/Anyone with this link sees what you pick here/)).toBeInTheDocument()
    expect(screen.getByText(/The old link stops working at once/)).toBeInTheDocument()
    expect(screen.getByText(/Switched off because your sign-in details changed/))
      .toHaveClass('hintline', 'warn')
    expect(screen.getByText(/Nothing is selected, so this link shows nothing/))
      .toHaveClass('hintline', 'warn')
  })
})

describe('Developer under Field notes', () => {
  it('drops both lines and keeps the panels', () => {
    render(<DeveloperSection />)
    expect(screen.queryByText(/Every display mode at common panel sizes/)).toBeNull()
    expect(screen.queryByText(/Previews use the real renderer/)).toBeNull()
    expect(document.querySelectorAll('.dev-panel__shot').length).toBeGreaterThan(6)
    noTitles()
  })
})

describe('the Appearance editor under Field notes', () => {
  const show = (on = false) => render(
    <AppearancePanel appearance={{}} onChange={vi.fn()} mode="light" onMode={vi.fn()}
      onClose={vi.fn()} wallpaperAccent={{ on, onToggle: vi.fn() }} />)

  it('drops the theme and per-token hints, and the wallpaper note and its description', () => {
    show()
    expect(screen.queryByText(/Editing it creates your own copy/)).toBeNull()
    expect(screen.queryByText(/On this phone only/)).toBeNull()
    expect(document.querySelectorAll('.appear-hint')).toHaveLength(0)
    expect(document.getElementById('appear-wallpaper-accent-hint')).toBeNull()
    const toggle = screen.getByLabelText('Accent from wallpaper')
    expect(toggle).not.toHaveAttribute('aria-describedby')
    expect(toggle).toHaveAccessibleDescription('')
    // The reset buttons keep their name, but no tooltip.
    expect(screen.getAllByRole('button', { name: /^Reset / }).length).toBeGreaterThan(0)
    noTitles()
  })
})
