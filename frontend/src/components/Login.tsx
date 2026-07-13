import { useState, type FormEvent } from 'react'
import { api } from '../api'

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
      const msg = (ex as Error).message
      setErr(msg === 'Unauthorized' || msg === 'invalid credentials' ? 'Invalid credentials' : msg)
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
