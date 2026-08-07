import { useState, type FormEvent } from 'react'
import { api, AuthError } from '../api'

export function Login({ onLogin }: { onLogin: (user: string) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      const r = await api.login(username, password)
      onLogin(r.user)
    } catch (ex) {
      // A 401 is the wrong-password case and the only one worth rewording. It
      // used to arrive as a fixed AuthError('unauthenticated') — the client
      // threw before reading the body — so the login card rendered that
      // internal token at the user, matching neither string this checked for.
      // Everything else (a 429 lockout, a 5xx) is shown as the server put it.
      setErr(ex instanceof AuthError ? 'Invalid credentials' : (ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">Smylte<span className="dot">.</span></div>
        <div className="field">
          <label className="label">Username</label>
          <input className="input" value={username} autoFocus autoComplete="username"
            onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="field">
          <label className="label">Password</label>
          <input className="input" type="password" value={password} autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} />
        </div>
        {err && <div className="login-err">{err}</div>}
        <button className="btn" type="submit" disabled={busy}>{busy ? '…' : 'Sign in'}</button>
      </form>
    </div>
  )
}
