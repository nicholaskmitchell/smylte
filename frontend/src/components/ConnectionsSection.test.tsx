// The only screen that shows which applications hold a live MCP OAuth grant
// over the whole account, and the only place one can be revoked — and it had no
// behavioural test at all. A regression here is silent by construction: the
// component renders confident prose in every state.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectionsSection } from './ConnectionsSection'
import { api, AuthError, HttpError } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})

const m = vi.mocked(api)

const GRANT = {
  family_id: 'fam-1',
  client_name: 'Claude Desktop',
  scope: 'mcp:read mcp:write',
  created_at: '2026-08-01T10:00:00Z',
  last_used_at: '2026-08-20T09:30:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  cleanup()
})

const mount = (onExpire = vi.fn()) =>
  render(<ConnectionsSection onExpire={onExpire} />)

describe('<ConnectionsSection>', () => {
  it('lists a live grant with what it can do', async () => {
    m.mcpConnections.mockResolvedValue([GRANT] as never)
    mount()
    expect(await screen.findByText('Claude Desktop')).toBeInTheDocument()
    expect(screen.getByText(/read and write/i)).toBeInTheDocument()
  })

  it('says the account has nothing connected only when it really has nothing', async () => {
    m.mcpConnections.mockResolvedValue([] as never)
    mount()
    expect(await screen.findByText(/nothing is connected/i)).toBeInTheDocument()
  })

  it('does NOT claim an empty account when the fetch fails', async () => {
    // `makeGuard` swallows a non-401 and resolves undefined, so a 502 used to
    // land in the same render as a genuinely empty account: "Nothing is
    // connected." over an unread list, on the one screen that answers "what has
    // read+write access to everything I own right now".
    m.mcpConnections.mockRejectedValue(new HttpError(502, 'bad gateway'))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t load/i)
    expect(screen.queryByText(/nothing is connected/i)).toBeNull()
  })

  it('does not sit on "Loading…" forever when the fetch fails', async () => {
    m.mcpConnections.mockRejectedValue(new HttpError(500, 'boom'))
    mount()
    await waitFor(() => expect(screen.queryByText('Loading…')).toBeNull())
  })

  it('hands a lapsed session back to the shell instead of showing an error', async () => {
    const onExpire = vi.fn()
    m.mcpConnections.mockRejectedValue(new AuthError('unauthenticated'))
    mount(onExpire)
    await waitFor(() => expect(onExpire).toHaveBeenCalled())
  })

  it('revokes a grant, and puts the row back if the revoke fails', async () => {
    const user = userEvent.setup()
    m.mcpConnections.mockResolvedValue([GRANT] as never)
    m.mcpDisconnect.mockRejectedValue(new HttpError(500, 'boom'))
    mount()
    await screen.findByText('Claude Desktop')

    // Two-step, so a stray click cannot revoke access to the whole account.
    await user.click(screen.getByRole('button', { name: /disconnect/i }))
    await user.click(screen.getByRole('button', { name: /disconnect|confirm|yes/i }))

    expect(m.mcpDisconnect).toHaveBeenCalledWith('fam-1')
    // The optimistic removal must not stick when the server refused.
    await waitFor(() => expect(screen.getByText('Claude Desktop')).toBeInTheDocument())
  })
})
