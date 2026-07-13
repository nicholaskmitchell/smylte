import { useCallback, useEffect, useRef, useState } from 'react'
import { api, subscribe, type TasksViewMode } from './api'
import { setErrorNotifier } from './util'
import { Login } from './components/Login'
import { TasksView } from './components/TasksView'
import { CalendarView } from './components/CalendarView'
import { SchedulingView } from './components/SchedulingView'

type Auth = 'loading' | 'in' | 'out'
type Tab = 'tasks' | 'calendar' | 'scheduling'

export function App() {
  const [auth, setAuth] = useState<Auth>('loading')
  const [user, setUser] = useState('')
  const [tab, setTab] = useState<Tab>('tasks')
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light')
  const [tasksView, setTasksView] = useState<TasksViewMode>('list')
  const [sideCollapsed, setSideCollapsed] = useState(false)
  const [rev, setRev] = useState(0)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()
  const settingsRef = useRef<HTMLDivElement>(null)
  const gearRef = useRef<HTMLButtonElement>(null)

  // Failed saves/deletes anywhere in the app surface here (see makeGuard).
  useEffect(() => {
    setErrorNotifier((msg) => {
      setToast(msg)
      clearTimeout(toastTimer.current)
      toastTimer.current = setTimeout(() => setToast(null), 6000)
    })
    return () => { setErrorNotifier(null); clearTimeout(toastTimer.current) }
  }, [])

  useEffect(() => {
    api.me().then((m) => { setUser(m.user); setAuth('in') }).catch(() => setAuth('out'))
  }, [])

  const applyTheme = useCallback((next: string) => {
    document.documentElement.dataset.theme = next
    // Keep mobile browser chrome (status bar / URL bar) matching the theme.
    document.querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', next === 'dark' ? '#0C0C10' : '#FBFAF7')
    try { localStorage.setItem('tasks-theme', next) } catch { /* ignore */ }
    setTheme(next)
  }, [])

  // Settings are account-synced: once authenticated, the server is the source of
  // truth (localStorage is only the pre-paint cache to avoid a flash).
  useEffect(() => {
    if (auth !== 'in') return
    api.getSettings()
      .then((s) => {
        if (s.theme === 'dark' || s.theme === 'light') applyTheme(s.theme)
        if (s.tasks_view === 'list' || s.tasks_view === 'day3' || s.tasks_view === 'week') {
          setTasksView(s.tasks_view)
        }
        if (typeof s.sidebar_collapsed === 'boolean') setSideCollapsed(s.sidebar_collapsed)
      })
      .catch(() => { /* keep the locally-cached theme */ })
  }, [auth, applyTheme])

  const changeTasksView = useCallback((v: TasksViewMode) => {
    setTasksView(v)
    api.putSettings({ tasks_view: v }).catch(() => { /* stays local if offline */ })
  }, [])

  const toggleSide = useCallback(() => {
    const next = !sideCollapsed
    setSideCollapsed(next)
    api.putSettings({ sidebar_collapsed: next }).catch(() => { /* stays local if offline */ })
  }, [sideCollapsed])

  // Live updates: any server-side change bumps `rev`, which the views watch.
  // One user action can publish several events in a burst (e.g. a move is a
  // delete + create) — debounce so they coalesce into a single refetch pass.
  useEffect(() => {
    if (auth !== 'in') return
    let timer: ReturnType<typeof setTimeout> | undefined
    const unsubscribe = subscribe(() => {
      clearTimeout(timer)
      timer = setTimeout(() => setRev((r) => r + 1), 250)
    })
    return () => { clearTimeout(timer); unsubscribe() }
  }, [auth])

  // Dismiss the settings menu on an outside click or Escape (like Søren's).
  useEffect(() => {
    if (!settingsOpen) return
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node
      if (settingsRef.current?.contains(t) || gearRef.current?.contains(t)) return
      setSettingsOpen(false)
    }
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setSettingsOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [settingsOpen])

  const toggleTheme = useCallback(() => {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    // Persist to the account so the choice follows the user to other browsers.
    api.putSettings({ theme: next }).catch(() => { /* stays local if offline */ })
  }, [theme, applyTheme])

  const onExpire = useCallback(() => setAuth('out'), [])
  const onLogout = async () => { try { await api.logout() } finally { setAuth('out') } }

  if (auth === 'loading') return null
  if (auth === 'out') return <Login onLogin={(u) => { setUser(u); setAuth('in') }} />

  return (
    <div className="shell">
      <div className="topbar">
        <span className="brand">Smylte<span className="dot">.</span></span>
        <div className="tabs">
          <button className={`tab ${tab === 'tasks' ? 'active' : ''}`} onClick={() => setTab('tasks')}>
            Tasks
          </button>
          <button className={`tab ${tab === 'calendar' ? 'active' : ''}`} onClick={() => setTab('calendar')}>
            Calendar
          </button>
          <button className={`tab ${tab === 'scheduling' ? 'active' : ''}`} onClick={() => setTab('scheduling')}>
            Scheduling
          </button>
        </div>
        <span className="spacer" />
        <button ref={gearRef} className={`icon-btn ${settingsOpen ? 'active' : ''}`}
          title="Settings" aria-label="Settings" onClick={() => setSettingsOpen((o) => !o)}>
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
            strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>

        {settingsOpen && (
          <div ref={settingsRef} className="menu settings-menu" role="dialog" aria-label="Settings">
            <div className="menu-head">Settings</div>
            <div className="menu-row">
              <label>Theme</label>
              <button className="menu-toggle" onClick={toggleTheme}>
                {theme === 'dark' ? 'Dark' : 'Light'}
              </button>
            </div>
            <div className="menu-row">
              <label>Signed in as</label>
              <span className="menu-value">{user}</span>
            </div>
            <div className="hintline">
              Lists and calendars live on the Radicale CalDAV server — changes here
              show up in every connected client.
            </div>
            <div className="menu-actions">
              <button className="btn ghost" onClick={onLogout}>Log out</button>
            </div>
          </div>
        )}
      </div>
      {tab === 'tasks' && (
        <TasksView rev={rev} onExpire={onExpire} view={tasksView} onView={changeTasksView}
          sideCollapsed={sideCollapsed} onToggleSide={toggleSide} />
      )}
      {tab === 'calendar' && (
        <CalendarView rev={rev} onExpire={onExpire}
          sideCollapsed={sideCollapsed} onToggleSide={toggleSide} />
      )}
      {tab === 'scheduling' && <SchedulingView rev={rev} onExpire={onExpire} />}
      {toast && (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setToast(null)}>✕</button>
        </div>
      )}
    </div>
  )
}
