import { useCallback, useEffect, useState } from 'react'
import { api, subscribe } from './api'
import { Login } from './components/Login'
import { TasksView } from './components/TasksView'
import { CalendarView } from './components/CalendarView'

type Auth = 'loading' | 'in' | 'out'
type Tab = 'tasks' | 'calendar'

export function App() {
  const [auth, setAuth] = useState<Auth>('loading')
  const [user, setUser] = useState('')
  const [tab, setTab] = useState<Tab>('tasks')
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light')
  const [rev, setRev] = useState(0)

  useEffect(() => {
    api.me().then((m) => { setUser(m.user); setAuth('in') }).catch(() => setAuth('out'))
  }, [])

  // Live updates: any server-side change bumps `rev`, which the views watch.
  useEffect(() => {
    if (auth !== 'in') return
    return subscribe(() => setRev((r) => r + 1))
  }, [auth])

  const toggleTheme = useCallback(() => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark'
      document.documentElement.dataset.theme = next
      try { localStorage.setItem('tasks-theme', next) } catch { /* ignore */ }
      return next
    })
  }, [])

  const onExpire = useCallback(() => setAuth('out'), [])
  const onLogout = async () => { try { await api.logout() } finally { setAuth('out') } }

  if (auth === 'loading') return null
  if (auth === 'out') return <Login onLogin={(u) => { setUser(u); setAuth('in') }} />

  return (
    <div className="shell">
      <div className="topbar">
        <span className="brand">Radicale<span className="dot">.</span></span>
        <div className="tabs">
          <button className={`tab ${tab === 'tasks' ? 'active' : ''}`} onClick={() => setTab('tasks')}>
            Tasks
          </button>
          <button className={`tab ${tab === 'calendar' ? 'active' : ''}`} onClick={() => setTab('calendar')}>
            Calendar
          </button>
        </div>
        <span className="spacer" />
        <span className="topbar-meta">{user}</span>
        <button className="icon-btn" title="Toggle theme" onClick={toggleTheme}>
          {theme === 'dark' ? '☾' : '☀'}
        </button>
        <button className="btn ghost" onClick={onLogout}>Log out</button>
      </div>
      {tab === 'tasks'
        ? <TasksView rev={rev} onExpire={onExpire} />
        : <CalendarView rev={rev} onExpire={onExpire} />}
    </div>
  )
}
