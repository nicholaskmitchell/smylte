import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Login } from './Login'
import { api } from '../api'

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
  const [username] = screen.getAllByRole('textbox')
  const password = document.querySelector('input[type="password"]') as HTMLInputElement
  return { username, password, button: screen.getByRole('button', { name: /sign in/i }) }
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
    loginMock.mockRejectedValue(new Error('invalid credentials'))
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
