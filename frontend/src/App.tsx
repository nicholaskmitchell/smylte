import { useCallback, useEffect, useRef, useState } from 'react'
import { api, subscribe, type DashboardModule, type TaskGroup, type TasksViewMode } from './api'
import { setErrorNotifier } from './util'
import {
  applyTokens, cacheAppearance, ensureFonts, readCachedAppearance, resolve,
  sanitizeAppearance, syncThemeColor, type Appearance, type Mode,
} from './appearance'
import { sanitizeLayout } from './dashboard'
import {
  DEFAULT_TAB_ORDER, DEFAULT_TAB_START, TAB_LABELS, cacheTab, isTab, readCachedTab,
  resolveStartTab, sanitizeTabOrder, sanitizeTabStart, type Tab, type TabStart,
} from './tabs'
import { Login } from './components/Login'
import { TasksView } from './components/TasksView'
import { CalendarView } from './components/CalendarView'
import { SchedulingView } from './components/SchedulingView'
import { HomeView } from './components/HomeView'
import { AppearancePanel } from './components/AppearancePanel'
import { ArchivedCalendarsModal } from './components/ArchivedCalendarsModal'
import { TabsModal } from './components/TabsModal'

type Auth = 'loading' | 'in' | 'out'

export function App() {
  const [auth, setAuth] = useState<Auth>('loading')
  const [user, setUser] = useState('')
  // Seeded from the boot cache so the app paints the tab it will settle on,
  // rather than flashing the default while the settings fetch is in flight.
  const [tab, setTab] = useState<Tab>(() => readCachedTab() ?? DEFAULT_TAB_ORDER[0])
  const [tabOrder, setTabOrder] = useState<Tab[]>(DEFAULT_TAB_ORDER)
  const [startTab, setStartTab] = useState<TabStart>(DEFAULT_TAB_START)
  // A tab picked while settings were still loading wins over the stored choice —
  // nothing is more jarring than the view changing under a deliberate click.
  const tabTouched = useRef(false)
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light')
  const [tasksView, setTasksView] = useState<TasksViewMode>('list')
  const [sideCollapsed, setSideCollapsed] = useState(false)
  const [hiddenCals, setHiddenCals] = useState<string[]>([])
  const [archivedCals, setArchivedCals] = useState<string[]>([])
  const [hiddenLists, setHiddenLists] = useState<string[]>([])
  const [taskGroups, setTaskGroups] = useState<TaskGroup[]>([])
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>([])
  const [showCompleted, setShowCompleted] = useState(false)
  const [rev, setRev] = useState(0)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [archivedOpen, setArchivedOpen] = useState(false)
  const [tabsOpen, setTabsOpen] = useState(false)
  const [appearanceOpen, setAppearanceOpen] = useState(false)
  // Seeded from the pre-paint cache so the editor opens showing what is already
  // on screen; the server overwrites it a moment later like every other setting.
  const [appearance, setAppearance] = useState<Appearance>(() => readCachedAppearance() ?? {})
  const [dashboard, setDashboard] = useState<DashboardModule[]>([])
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
    try { localStorage.setItem('tasks-theme', next) } catch { /* ignore */ }
    setTheme(next)
  }, [])

  // The one place custom appearance reaches the DOM. Overrides are inline
  // properties on <html>, so they win over :root in tokens.css without
  // replacing it — an empty map (no active theme) restores the shipped design
  // exactly. Re-runs on a light/dark flip too, since a theme carries a separate
  // map per mode.
  useEffect(() => {
    const mode: Mode = theme === 'dark' ? 'dark' : 'light'
    const tokens = resolve(appearance, mode)
    applyTokens(document.documentElement, tokens)
    ensureFonts(tokens)
    syncThemeColor()
  }, [appearance, theme])

  // Settings are account-synced: once authenticated, the server is the source of
  // truth (localStorage is only the pre-paint cache to avoid a flash).
  useEffect(() => {
    if (auth !== 'in') return
    api.getSettings()
      .then((s) => {
        if (s.theme === 'dark' || s.theme === 'light') applyTheme(s.theme)
        const order = sanitizeTabOrder(s.tab_order)
        const start = sanitizeTabStart(s.start_tab)
        setTabOrder(order)
        setStartTab(start)
        if (!tabTouched.current) {
          const opening = resolveStartTab(start, isTab(s.last_tab) ? s.last_tab : undefined, order)
          setTab(opening)
          cacheTab(opening)
        }
        if (s.tasks_view === 'list' || s.tasks_view === 'day3' || s.tasks_view === 'week') {
          setTasksView(s.tasks_view)
        }
        if (typeof s.sidebar_collapsed === 'boolean') setSideCollapsed(s.sidebar_collapsed)
        if (Array.isArray(s.hidden_calendars)) {
          setHiddenCals(s.hidden_calendars.filter((x) => typeof x === 'string'))
        }
        if (Array.isArray(s.archived_calendars)) {
          setArchivedCals(s.archived_calendars.filter((x) => typeof x === 'string'))
        }
        if (Array.isArray(s.hidden_lists)) {
          setHiddenLists(s.hidden_lists.filter((x) => typeof x === 'string'))
        }
        if (Array.isArray(s.task_groups)) {
          // Defend against a malformed blob (hand-edited settings, an old
          // schema): keep only well-formed groups with a real id and name.
          setTaskGroups(s.task_groups.filter((g): g is TaskGroup =>
            !!g && typeof g.id === 'string' && typeof g.name === 'string' &&
            Array.isArray(g.lists)).map((g) => ({
              id: g.id, name: g.name, lists: g.lists.filter((x) => typeof x === 'string'),
            })))
        }
        if (Array.isArray(s.collapsed_groups)) {
          setCollapsedGroups(s.collapsed_groups.filter((x) => typeof x === 'string'))
        }
        if (typeof s.show_completed_tasks === 'boolean') setShowCompleted(s.show_completed_tasks)
        // Both blobs are re-validated here rather than trusted: they are the
        // two settings a user can hand-edit or import a file into, and an
        // unknown token or a garbage grid cell should degrade to the default
        // instead of reaching the CSSOM or the layout engine.
        if (s.appearance) {
          const clean = sanitizeAppearance(s.appearance)
          setAppearance(clean)
          cacheAppearance(clean)
        }
        if (Array.isArray(s.dashboard)) setDashboard(sanitizeLayout(s.dashboard))
      })
      .catch(() => { /* keep the locally-cached theme + appearance */ })
  }, [auth, applyTheme])

  // Appearance is account-synced like the rest, plus mirrored to localStorage
  // for the pre-paint script in index.html (which runs before this bundle).
  const changeAppearance = useCallback((next: Appearance) => {
    setAppearance(next)
    cacheAppearance(next)
    api.putSettings({ appearance: next }).catch(() => { /* stays local if offline */ })
  }, [])

  const changeDashboard = useCallback((next: DashboardModule[]) => {
    setDashboard(next)
    api.putSettings({ dashboard: next }).catch(() => { /* stays local if offline */ })
  }, [])

  // Switching tabs only touches the server while the app is set to reopen where
  // the user left off — a fixed start tab has nothing to remember.
  const changeTab = useCallback((next: Tab) => {
    tabTouched.current = true
    setTab(next)
    if (startTab !== 'last') return
    cacheTab(next)
    api.putSettings({ last_tab: next }).catch(() => { /* stays local if offline */ })
  }, [startTab])

  const changeTabOrder = useCallback((next: Tab[]) => {
    setTabOrder(next)
    api.putSettings({ tab_order: next }).catch(() => { /* stays local if offline */ })
  }, [])

  const changeStartTab = useCallback((next: TabStart) => {
    setStartTab(next)
    // Keep the boot cache honest straight away: "last" means the current tab,
    // anything else means itself.
    cacheTab(next === 'last' ? tab : next)
    api.putSettings({ start_tab: next, ...(next === 'last' ? { last_tab: tab } : {}) })
      .catch(() => { /* stays local if offline */ })
  }, [tab])

  const changeTasksView = useCallback((v: TasksViewMode) => {
    setTasksView(v)
    api.putSettings({ tasks_view: v }).catch(() => { /* stays local if offline */ })
  }, [])

  const toggleSide = useCallback(() => {
    const next = !sideCollapsed
    setSideCollapsed(next)
    api.putSettings({ sidebar_collapsed: next }).catch(() => { /* stays local if offline */ })
  }, [sideCollapsed])

  // Per-calendar visibility follows the account like the other prefs above.
  const changeHiddenCals = useCallback((next: string[]) => {
    setHiddenCals(next)
    api.putSettings({ hidden_calendars: next }).catch(() => { /* stays local if offline */ })
  }, [])

  // Archived calendars follow the account too. Archive/restore is just a write
  // to this list — the CalDAV collection is never touched.
  const changeArchivedCals = useCallback((next: string[]) => {
    setArchivedCals(next)
    api.putSettings({ archived_calendars: next }).catch(() => { /* stays local if offline */ })
  }, [])

  // Tasks-side sidebar prefs — hidden lists (combined-view visibility), the
  // group definitions, and which groups are collapsed. All account-synced like
  // the calendar prefs above; none of them touch the CalDAV collections.
  const changeHiddenLists = useCallback((next: string[]) => {
    setHiddenLists(next)
    api.putSettings({ hidden_lists: next }).catch(() => { /* stays local if offline */ })
  }, [])
  const changeTaskGroups = useCallback((next: TaskGroup[]) => {
    setTaskGroups(next)
    api.putSettings({ task_groups: next }).catch(() => { /* stays local if offline */ })
  }, [])
  const changeCollapsedGroups = useCallback((next: string[]) => {
    setCollapsedGroups(next)
    api.putSettings({ collapsed_groups: next }).catch(() => { /* stays local if offline */ })
  }, [])

  // Whether completed tasks show inline in the main view. Hidden by default; the
  // sidebar's "View completed" button always works regardless of this choice.
  const toggleShowCompleted = useCallback(() => {
    const next = !showCompleted
    setShowCompleted(next)
    api.putSettings({ show_completed_tasks: next }).catch(() => { /* stays local if offline */ })
  }, [showCompleted])

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

  const changeTheme = useCallback((next: 'light' | 'dark') => {
    applyTheme(next)
    // Persist to the account so the choice follows the user to other browsers.
    api.putSettings({ theme: next }).catch(() => { /* stays local if offline */ })
  }, [applyTheme])

  const toggleTheme = useCallback(() => {
    changeTheme(theme === 'dark' ? 'light' : 'dark')
  }, [theme, changeTheme])

  const onExpire = useCallback(() => setAuth('out'), [])
  const onLogout = async () => { try { await api.logout() } finally { setAuth('out') } }

  if (auth === 'loading') return null
  if (auth === 'out') return <Login onLogin={(u) => { setUser(u); setAuth('in') }} />

  return (
    <div className="shell">
      <div className="topbar">
        <span className="brand">Smylte<span className="dot">.</span></span>
        <div className="tabs">
          {tabOrder.map((t) => (
            <button key={t} className={`tab ${tab === t ? 'active' : ''}`}
              onClick={() => changeTab(t)}>
              {TAB_LABELS[t]}
            </button>
          ))}
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
              <label>Appearance</label>
              <button className="menu-toggle" aria-label="Customize appearance"
                onClick={() => { setSettingsOpen(false); setAppearanceOpen(true) }}>
                Customize…
              </button>
            </div>
            <div className="menu-row">
              <label>Tabs</label>
              <button className="menu-toggle" aria-label="Customize tabs"
                onClick={() => { setSettingsOpen(false); setTabsOpen(true) }}>
                Customize…
              </button>
            </div>
            <div className="menu-row">
              <label>Completed tasks</label>
              <button className="menu-toggle" onClick={toggleShowCompleted}
                aria-pressed={showCompleted}>
                {showCompleted ? 'Shown' : 'Hidden'}
              </button>
            </div>
            <div className="menu-row">
              <label>Signed in as</label>
              <span className="menu-value">{user}</span>
            </div>
            <div className="menu-row">
              <label>Archived calendars</label>
              <button className="menu-toggle"
                onClick={() => { setSettingsOpen(false); setArchivedOpen(true) }}>
                {archivedCals.length > 0 ? `View (${archivedCals.length})` : 'View'}
              </button>
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
          sideCollapsed={sideCollapsed} onToggleSide={toggleSide}
          hiddenLists={hiddenLists} onHiddenListsChange={changeHiddenLists}
          groups={taskGroups} onGroupsChange={changeTaskGroups}
          collapsedGroups={collapsedGroups} onCollapsedGroupsChange={changeCollapsedGroups}
          showCompleted={showCompleted} />
      )}
      {tab === 'calendar' && (
        <CalendarView rev={rev} onExpire={onExpire}
          sideCollapsed={sideCollapsed} onToggleSide={toggleSide}
          hiddenCalendars={hiddenCals} onHiddenCalendarsChange={changeHiddenCals}
          archivedCalendars={archivedCals} onArchivedCalendarsChange={changeArchivedCals} />
      )}
      {tab === 'scheduling' && <SchedulingView rev={rev} onExpire={onExpire} />}
      {tab === 'home' && (
        <HomeView rev={rev} onExpire={onExpire}
          layout={dashboard} onLayoutChange={changeDashboard}
          hiddenCalendars={hiddenCals} archivedCalendars={archivedCals} />
      )}
      {appearanceOpen && (
        <AppearancePanel appearance={appearance} onChange={changeAppearance}
          mode={theme === 'dark' ? 'dark' : 'light'} onMode={changeTheme}
          onClose={() => setAppearanceOpen(false)} />
      )}
      {archivedOpen && (
        <ArchivedCalendarsModal archived={archivedCals} onChange={changeArchivedCals}
          onExpire={onExpire} onClose={() => setArchivedOpen(false)} />
      )}
      {tabsOpen && (
        <TabsModal order={tabOrder} start={startTab} onOrderChange={changeTabOrder}
          onStartChange={changeStartTab} onClose={() => setTabsOpen(false)} />
      )}
      {toast && (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setToast(null)}>✕</button>
        </div>
      )}
    </div>
  )
}
