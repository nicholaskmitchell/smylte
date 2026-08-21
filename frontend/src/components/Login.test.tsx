import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Login } from './Login'
import { api, AuthError, HttpError } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return { ...mod, api: { ...mod.api, login: vi.fn() } }
})

const loginMock = vi.mocked(api.login)

// Block body: a hook must not return the mock (vitest would call a returned
// function as a teardown callback — invoking the mock and failing the test on
// its rejected promise).
beforeEach(() => { loginMock.mockReset() })

function fields() {
  // By LABEL, which is the point: both inputs were unlabelled, and this helper
  // routed around that — the username by position among the textboxes, the
  // password by a raw type selector (a password input has no `textbox` role at
  // all, so `getByRole` could not reach it). Reaching them by their accessible
  // name is what a screen reader does, so the workaround staying here beside
  // the fix would have gone on passing if the labels were ever unwired again.
  return {
    username: screen.getByLabelText('Username'),
    password: screen.getByLabelText('Password'),
    button: screen.getByRole('button', { name: /sign in/i }),
  }
}

describe('<Login>', () => {
  it('renders the brand and an empty form', () => {
    render(<Login onLogin={() => {}} />)
    expect(screen.getByText('Smylte')).toBeInTheDocument()
    const { username, password } = fields()
    expect(username).toHaveValue('')
    expect(password).toHaveValue('')
  })

  it('submits credentials and reports the user up', async () => {
    loginMock.mockResolvedValue({ authenticated: true, user: 'admin' })
    const onLogin = vi.fn()
    render(<Login onLogin={onLogin} />)
    const { username, password, button } = fields()
    await userEvent.type(username, 'admin')
    await userEvent.type(password, 'hunter2')
    await userEvent.click(button)
    expect(loginMock).toHaveBeenCalledWith('admin', 'hunter2')
    expect(onLogin).toHaveBeenCalledWith('admin')
  })

  it('shows a friendly message on bad credentials and stays on the form', async () => {
    // The shape the api client actually throws for a 401. This used to reject
    // with a plain Error('invalid credentials'), which `j()` can never produce —
    // so the test passed while the real form rendered the word 'unauthenticated'.
    loginMock.mockRejectedValue(new AuthError('invalid credentials'))
    const onLogin = vi.fn()
    render(<Login onLogin={onLogin} />)
    const { username, password, button } = fields()
    await userEvent.type(username, 'admin')
    await userEvent.type(password, 'wrong')
    await userEvent.click(button)
    expect(await screen.findByText('Invalid credentials')).toBeInTheDocument()
    expect(onLogin).not.toHaveBeenCalled()
    expect(button).toBeEnabled()          // busy state cleared for a retry
  })

  it('surfaces unexpected errors verbatim (e.g. rate limiting)', async () => {
    loginMock.mockRejectedValue(new Error('too many attempts, try later'))
    render(<Login onLogin={() => {}} />)
    await userEvent.click(fields().button)
    expect(await screen.findByText('too many attempts, try later')).toBeInTheDocument()
  })
})

it('never shows the api client’s internal token to the user', async () => {
  // `j()` throws AuthError for every 401. It used to carry a fixed
  // 'unauthenticated' regardless of what the endpoint said, so the login card
  // rendered that word at whoever mistyped their password.
  loginMock.mockRejectedValue(new AuthError('unauthenticated'))
  render(<Login onLogin={vi.fn()} />)
  const { username, password, button } = fields()
  await userEvent.type(username, 'admin')
  await userEvent.type(password, 'wrong')
  await userEvent.click(button)
  expect(await screen.findByText('Invalid credentials')).toBeInTheDocument()
  expect(screen.queryByText('unauthenticated')).not.toBeInTheDocument()
})

it('shows a lockout message from the server verbatim', async () => {
  // 429 is not intercepted, so the server's own wording reaches the user.
  loginMock.mockRejectedValue(new HttpError(429, 'too many attempts, try later'))
  render(<Login onLogin={vi.fn()} />)
  const { username, password, button } = fields()
  await userEvent.type(username, 'admin')
  await userEvent.type(password, 'wrong')
  await userEvent.click(button)
  expect(await screen.findByText('too many attempts, try later')).toBeInTheDocument()
})
