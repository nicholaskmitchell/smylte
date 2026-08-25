import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api, AuthError, HttpError, subscribe,
  type DashboardModule, type Settings, type TaskGroup, type TasksViewMode,
} from './api'
import { setErrorNotifier } from './util'
import { DataProvider } from './data'
import { clearCache, setCacheUser, sweepOldVersions } from './cache'
import {
  applyTokens, cacheAppearance, ensureFonts, presetSlug, readCachedAppearance,
  resolve, sanitizeAppearance, syncThemeColor, type Appearance, type Mode,
} from './appearance'
import {
  DEFAULT_CALENDAR_FIT, calendarFitLabel, isCalendarFit, nextCalendarFit, type CalendarFit,
} from './calendar'
import { sanitizeLayout } from './dashboard'
import { isSessionTtl, nextSessionTtl, sessionLabel } from './session'
import {
  DEFAULT_TIME_FORMAT, isTimeFormat, nextTimeFormat, timeFormatLabel, type TimeFormat,
} from './time'
import { sanitizeCapacityByWeekday } from './capacity'
import { TimeFormatProvider } from './timeformat'
import {
  DEFAULT_TAB_ORDER, DEFAULT_TAB_START, TAB_LABELS, cacheTab, isTab, readCachedTab,
  resolveStartTab, sanitizeTabOrder, sanitizeTabStart, type Tab, type TabStart,
} from './tabs'
import { Login } from './components/Login'
import { TasksView } from './components/TasksView'
import { CalendarView } from './components/CalendarView'
import { SchedulingView } from './components/SchedulingView'
import { HomeView } from './components/HomeView'
import { TodayView } from './components/TodayView'
import { AppearancePanel } from './components/AppearancePanel'
import { SettingsMenu } from './components/SettingsMenu'

type Auth = 'loading' | 'in' | 'out'

export function App() {
  const [auth, setAuth] = useState<Auth>('loading')
  const [user, setUser] = useState('')
  // Seeded from the boot cache so the app paints the tab it will settle on,
  // rather than flashing the default while the settings fetch is in flight.
  //
  // The fallback is DEFAULT_TAB_START, not the strip's first tab. Those were the
  // same value until Today took the head of the strip while Home stayed the tab
  // a fresh account opens on (see tabs.ts) — and seeding from the strip would
  // have painted Today for the length of the /api/settings round trip and then
  // yanked the view to Home, which is precisely the flash this seed exists to
  // remove. `isTab` narrows away the 'last' case, which names no tab to paint;
  // with nothing remembered "last" resolves to the strip's head anyway.
  const [tab, setTab] = useState<Tab>(
    () => readCachedTab() ?? (isTab(DEFAULT_TAB_START) ? DEFAULT_TAB_START : DEFAULT_TAB_ORDER[0]))
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
  const [collapsedTasks, setCollapsedTasks] = useState<string[]>([])
  const [showCompleted, setShowCompleted] = useState(false)
  const [timeFormat, setTimeFormat] = useState<TimeFormat>(DEFAULT_TIME_FORMAT)
  // How long a day is expected to hold. Null is "never said", and it stays null
  // rather than defaulting to an assumed working day — see
  // `service._effective_capacity`, which every reader of this agrees with.
  const [dayCapacity, setDayCapacity] = useState<number | null>(null)
  const [dayCapacityByWeekday, setDayCapacityByWeekday] =
    useState<Record<string, number>>({})
  const [homeTz, setHomeTz] = useState('')     // '' = fall back to each link's zone
  // An allowlist, not a hidden-set: no task list is drawn on the calendar until
  // it is opted in (see the SettingsPatch comment for why this one is inverted).
  const [calTaskLists, setCalTaskLists] = useState<string[]>([])
  const [calShowDone, setCalShowDone] = useState(false)
  // Whether the month grid fits the pane or grows to its busiest day. Dynamic is
  // what the grid has always done, so an account that never chose keeps it.
  const [calFit, setCalFit] = useState<CalendarFit>(DEFAULT_CALENDAR_FIT)
  // How long a login lasts. Null means the deployment's own TASKS_SESSION_TTL,
  // which is what this used to be the only way to set.
  const [sessionTtl, setSessionTtl] = useState<number | null>(null)
  const [rev, setRev] = useState(0)
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Appearance is the one editor still opened over the app: it is a full token
  // workbench, not a row of settings. Tabs, connected apps and archived
  // calendars are sections inside the settings panel now.
  const [appearanceOpen, setAppearanceOpen] = useState(false)
  // Did the settings read FAIL? Not "has it succeeded" — the difference matters.
  // Gating on success also blocks a gesture racing the initial load, which turns
  // a millisecond window into a silently dropped preference and a confusing
  // toast: a new failure mode in place of the one being fixed. This is the
  // read-side twin of data.tsx's `listsOk`, narrowed to the case that actually
  // loses data. See `MERGED_SETTINGS` and `saveSettings` below.
  //
  // A ref, not state, because nothing renders from it and because half the
  // `change*` callbacks below are `useCallback(..., [])` — they capture the
  // FIRST `saveSettings` and hold it for the life of the app, so a value read
  // out of a closure would be the one from before the read ever finished. A ref
  // is read at call time and cannot go stale.
  const settingsFailed = useRef(false)
  // Seeded from the pre-paint cache so the editor opens showing what is already
  // on screen; the server overwrites it a moment later like every other setting.
  const [appearance, setAppearance] = useState<Appearance>(() => readCachedAppearance() ?? {})
  const [dashboard, setDashboard] = useState<DashboardModule[]>([])
  // The calendar month, held here so returning to the Calendar tab lands where
  // you left it rather than snapping back to today.
  const [cursor, setCursor] = useState(() => {
    const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1)
  })
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()
  const settingsRef = useRef<HTMLDivElement>(null)
  const gearRef = useRef<HTMLButtonElement>(null)
  /** The tab strip and whichever tab is current. Only the second is read; the
   *  strip's ref is what makes the guard below cheap — no scrolling is attempted
   *  before the bar exists. */
  const tabsRef = useRef<HTMLDivElement>(null)
  const activeTabRef = useRef<HTMLButtonElement>(null)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 6000)
  }, [])

  // Keep the current tab visible in a strip that scrolls (phones — see the
  // markup below). Runs on every tab change AND on first paint, which is the
  // one that matters: a reload lands on the remembered tab, and if that tab
  // sits past the right edge the bar opens looking like Today is selected.
  //
  // Guarded on the strip actually overflowing, so this is inert on a desktop
  // where nothing scrolls — `scrollIntoView` on a non-scrolling parent can
  // still nudge an ancestor, and the bar has no business moving anything there.
  useEffect(() => {
    const strip = tabsRef.current
    const active = activeTabRef.current
    if (!strip || !active) return
    if (strip.scrollWidth <= strip.clientWidth) return
    active.scrollIntoView({ inline: 'nearest', block: 'nearest' })
  }, [tab, tabOrder])

  // Failed saves/deletes anywhere in the app surface here (see makeGuard).
  useEffect(() => {
    setErrorNotifier(showToast)
    return () => { setErrorNotifier(null); clearTimeout(toastTimer.current) }
  }, [showToast])

  useEffect(() => {
    // The cache is per-account and keyed by name, so a different user simply
    // misses rather than reading someone else's rows; clearing on a change is
    // quota hygiene. `setCacheUser` runs before `setAuth('in')` so the views —
    // which seed from the cache as they mount — never race it.
    sweepOldVersions()
    api.me()
      .then((m) => { setCacheUser(m.user); setUser(m.user); setAuth('in') })
      .catch(() => setAuth('out'))
  }, [])

  const applyTheme = useCallback((next: string) => {
    document.documentElement.dataset.theme = next
    try { localStorage.setItem('tasks-theme', next) } catch { /* ignore */ }
    setTheme(next)
  }, [])

  // The one place appearance reaches the DOM, by both of its routes. A shipped
  // preset is an attribute, because it is a whole alternative design and lives
  // in tokens.css; a saved theme is a sparse map of inline properties on <html>,
  // which wins over :root without replacing it. The two are mutually exclusive,
  // and clearing both restores the shipped design exactly. Re-runs on a
  // light/dark flip too, since either route carries a separate map per mode.
  useEffect(() => {
    const mode: Mode = theme === 'dark' ? 'dark' : 'light'
    const slug = presetSlug(appearance?.active)
    if (slug) document.documentElement.dataset.preset = slug
    else delete document.documentElement.dataset.preset
    const tokens = resolve(appearance, mode)
    applyTokens(document.documentElement, tokens)
    ensureFonts(tokens)
    // Reads the resolved --bg back off the element, so it is correct whichever
    // route set it — hence last.
    syncThemeColor()
  }, [appearance, theme])

  // Settings are account-synced: once authenticated, the server is the source of
  // truth (localStorage is only the pre-paint cache to avoid a flash).
  useEffect(() => {
    if (auth !== 'in') return
    settingsFailed.current = false
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
        if (Array.isArray(s.collapsed_tasks)) {
          setCollapsedTasks(s.collapsed_tasks.filter((x) => typeof x === 'string'))
        }
        if (typeof s.show_completed_tasks === 'boolean') setShowCompleted(s.show_completed_tasks)
        if (isTimeFormat(s.time_format)) setTimeFormat(s.time_format)
        // Treated as hand-edited, like every other settings value here. A
        // non-number default is dropped to null rather than coerced: a capacity
        // read out of junk would be a number nobody gave, which is the one
        // thing this feature must not produce.
        // A negative stored value is the CLEAR sentinel at rest, and reads back
        // as "never said" — the same answer the server's resolution gives it.
        setDayCapacity(
          typeof s.day_capacity_minutes === 'number'
            && Number.isFinite(s.day_capacity_minutes)
            && s.day_capacity_minutes >= 0
            ? s.day_capacity_minutes
            : null)
        setDayCapacityByWeekday(sanitizeCapacityByWeekday(s.day_capacity_by_weekday))
        if (typeof s.home_timezone === 'string') setHomeTz(s.home_timezone)
        if (Array.isArray(s.calendar_task_lists)) {
          setCalTaskLists(s.calendar_task_lists.filter((x) => typeof x === 'string'))
        }
        if (typeof s.calendar_show_done_tasks === 'boolean') {
          setCalShowDone(s.calendar_show_done_tasks)
        }
        if (isCalendarFit(s.calendar_fit)) setCalFit(s.calendar_fit)
        if (isSessionTtl(s.session_ttl_s)) setSessionTtl(s.session_ttl_s)
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
      .catch((e) => {
        // The old handler was a bare `.catch(() => {})` with a comment saying it
        // keeps the locally-cached theme and appearance. True of those two — they
        // have a localStorage mirror — and of nothing else. The other eleven
        // preferences sat at their shipped defaults with no toast, no error
        // state and no retry (this effect re-runs on an `auth` transition only;
        // a `rev` bump does not re-run it), and the user had no way to tell.
        //
        // `settingsOk` stays false, which is what actually stops the loss; the
        // toast is so the user knows why a preference will not stick, and the
        // AuthError branch matches what the WRITE path already does — a tab open
        // past its session TTL used to keep accepting preference changes.
        if (e instanceof AuthError) { setAuth('out'); return }
        settingsFailed.current = true
        showToast("Couldn't load your preferences — changes won't be saved until this reloads")
      })
  }, [auth, applyTheme, showToast])

  // Every UI preference is written the same way, so the failure handling lives
  // in one place. These used to be `.catch(() => {})` — which swallowed an
  // AuthError just as happily as a dropped connection, so a tab open past the
  // session TTL kept accepting preference changes, never fell back to the login
  // form, and lost every one of them on the next reload with no explanation.
  // A 422 (a layout the server's bounds reject) vanished the same way.
  // The preferences whose value is COMPUTED FROM STATE THE READ WAS SUPPOSED TO
  // POPULATE. Those are the ones a failed read turns into a delete: the local
  // state is the shipped default, so the first gesture PUTs it over whatever the
  // account had.
  //
  // The predicate used to be "is it a merge with an array we hold", which let
  // three through that belong here:
  //
  //  * `session_ttl_s` CYCLES. `nextSessionTtl` is read-modify-write over
  //    exactly the state that failed to load: with the read broken the panel
  //    reads "7 days" whatever the account holds, and one click PUTs 30 — a 30x
  //    lengthening of the field app.py calls out as security-relevant, from a
  //    label that was already lying.
  //  * `home_timezone` toggles the same way, and it decides where floating
  //    events land in the public booking page's busy set.
  //  * `appearance` was excused as having a localStorage mirror — but
  //    `cacheAppearance` REMOVES that mirror whenever no theme is active. An
  //    account with saved themes and none active therefore starts from `{}`, and
  //    picking a theme emits `{active: id}` with no `themes` key.
  //    `update_settings` does a shallow `current.update(patch)`, so that one PUT
  //    destroys the whole theme collection.
  //
  // "Scalar" was never the question. Read-modify-write is — and the rule is
  // applied to the CLASS, not to the three the review happened to name. Every
  // remaining toggle here is `next = !current` or `nextX(current)` over state
  // this same read populates, so each one turns a failed read into a silent
  // flip to the opposite of what the account holds: the row shows the shipped
  // default, the user presses it once expecting to change what they see, and
  // the account's real value is overwritten by the negation of a lie.
  //
  // `start_tab` and `tasks_view` are NOT here on purpose: both carry the value
  // just chosen from a picker, so what is written is what the user asked for
  // whether or not the read landed.
  const MERGED_SETTINGS = [
    'hidden_calendars', 'archived_calendars', 'hidden_lists', 'task_groups',
    'collapsed_groups', 'collapsed_tasks', 'dashboard', 'calendar_task_lists',
    'tab_order', 'session_ttl_s', 'home_timezone', 'appearance',
    'sidebar_collapsed', 'show_completed_tasks', 'calendar_show_done_tasks',
    'calendar_fit', 'time_format',
    // The per-weekday map is READ-MODIFY-WRITE: the section rebuilds the whole
    // object to change one weekday, and `store.update_settings` merges
    // shallowly — so writing it after a failed read would replace the account's
    // real map with one built from the empty default. `day_capacity_minutes` is
    // deliberately NOT here, for the same reason `start_tab` is not: it carries
    // the value just typed into a field, so what is written is what was asked
    // for whether or not the read landed.
    'day_capacity_by_weekday',
  ] as const

  const saveSettings = useCallback((patch: Settings) => {
    if (settingsFailed.current) {
      const held = MERGED_SETTINGS.filter((k) => k in patch)
      if (held.length) {
        patch = Object.fromEntries(
          Object.entries(patch).filter(([k]) => !held.includes(k as never))) as Settings
        showToast("Your preferences didn't load, so this change wasn't saved — reload to try again")
      }
      if (!Object.keys(patch).length) return
    }
    api.putSettings(patch).catch((e) => {
      if (e instanceof AuthError) { setAuth('out'); return }
      // Offline is the ordinary case and the local state stands in fine; a
      // rejection from a server we *did* reach is what the user needs to know.
      if (e instanceof HttpError) showToast(`Couldn't save your preferences: ${e.message}`)
    })
  }, [showToast])

  // The settings a repeated gesture writes: an appearance slider fires onChange
  // on every step (a drag across one range is up to 56 of them), a dashboard
  // drag on every grid cell crossed, and folding a run of subtask trees is one
  // gesture as far as the user is concerned. Paint locally at once, but let the
  // write settle on the trailing edge, so one gesture is one PUT.
  //
  // Patches accumulate rather than replace one another. They used to replace,
  // which was harmless while only two continuous gestures existed (you cannot
  // drag an appearance slider and the dashboard at once) but silently dropped
  // the earlier of any two *different* preferences written inside the window.
  const saveTimer = useRef<ReturnType<typeof setTimeout>>()
  const pendingPatch = useRef<Settings>({})
  const saveSettingsSoon = useCallback((patch: Settings) => {
    pendingPatch.current = { ...pendingPatch.current, ...patch }
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      const next = pendingPatch.current
      pendingPatch.current = {}
      saveSettings(next)
    }, 400)
  }, [saveSettings])
  useEffect(() => () => clearTimeout(saveTimer.current), [])

  // Appearance is account-synced like the rest, plus mirrored to localStorage
  // for the pre-paint script in index.html (which runs before this bundle).
  const changeAppearance = useCallback((next: Appearance) => {
    setAppearance(next)
    cacheAppearance(next)
    saveSettingsSoon({ appearance: next })
  }, [saveSettingsSoon])

  const changeDashboard = useCallback((next: DashboardModule[]) => {
    setDashboard(next)
    saveSettingsSoon({ dashboard: next })
  }, [saveSettingsSoon])

  // Switching tabs only touches the server while the app is set to reopen where
  // the user left off — a fixed start tab has nothing to remember.
  const changeTab = useCallback((next: Tab) => {
    tabTouched.current = true
    setTab(next)
    if (startTab !== 'last') return
    cacheTab(next)
    saveSettings({ last_tab: next })
  }, [startTab])

  const changeTabOrder = useCallback((next: Tab[]) => {
    setTabOrder(next)
    saveSettings({ tab_order: next })
  }, [])

  const changeStartTab = useCallback((next: TabStart) => {
    setStartTab(next)
    // Keep the boot cache honest straight away: "last" means the current tab,
    // anything else means itself.
    cacheTab(next === 'last' ? tab : next)
    saveSettings({ start_tab: next, ...(next === 'last' ? { last_tab: tab } : {}) })
  }, [tab])

  const changeTasksView = useCallback((v: TasksViewMode) => {
    setTasksView(v)
    saveSettings({ tasks_view: v })
  }, [])

  const toggleSide = useCallback(() => {
    const next = !sideCollapsed
    setSideCollapsed(next)
    saveSettings({ sidebar_collapsed: next })
  }, [sideCollapsed])

  // Per-calendar visibility follows the account like the other prefs above.
  const changeHiddenCals = useCallback((next: string[]) => {
    setHiddenCals(next)
    saveSettings({ hidden_calendars: next })
  }, [])

  // Archived calendars follow the account too. Archive/restore is just a write
  // to this list — the CalDAV collection is never touched.
  const changeArchivedCals = useCallback((next: string[]) => {
    setArchivedCals(next)
    saveSettings({ archived_calendars: next })
  }, [])

  // Tasks-side sidebar prefs — hidden lists (combined-view visibility), the
  // group definitions, and which groups are collapsed. All account-synced like
  // the calendar prefs above; none of them touch the CalDAV collections.
  const changeHiddenLists = useCallback((next: string[]) => {
    setHiddenLists(next)
    saveSettings({ hidden_lists: next })
  }, [])
  const changeTaskGroups = useCallback((next: TaskGroup[]) => {
    setTaskGroups(next)
    saveSettings({ task_groups: next })
  }, [])
  const changeCollapsedGroups = useCallback((next: string[]) => {
    setCollapsedGroups(next)
    saveSettings({ collapsed_groups: next })
  }, [])
  // Which subtask trees are folded away. Follows the account like the rest, and
  // is written on the trailing edge because collapsing several in a row is one
  // gesture as far as the user is concerned.
  const changeCollapsedTasks = useCallback((next: string[]) => {
    setCollapsedTasks(next)
    saveSettingsSoon({ collapsed_tasks: next })
  }, [saveSettingsSoon])

  // Session length. The server keeps the same allowlist and refuses anything
  // else, so this cycles rather than offering a free field. Written straight
  // through, not debounced — one click is one decision.
  const cycleSessionTtl = useCallback(() => {
    const next = nextSessionTtl(sessionTtl)
    setSessionTtl(next)
    saveSettings({ session_ttl_s: next })
  }, [sessionTtl])

  // Whether completed tasks show inline in the main view. Hidden by default; the
  // sidebar's "View completed" button always works regardless of this choice.
  const toggleShowCompleted = useCallback(() => {
    const next = !showCompleted
    setShowCompleted(next)
    saveSettings({ show_completed_tasks: next })
  }, [showCompleted])

  const changeCalTaskLists = useCallback((next: string[]) => {
    setCalTaskLists(next)
    saveSettings({ calendar_task_lists: next })
  }, [])

  const toggleCalShowDone = useCallback(() => {
    const next = !calShowDone
    setCalShowDone(next)
    saveSettings({ calendar_show_done_tasks: next })
  }, [calShowDone])

  // Fixed or dynamic month grid. Two values, so the row cycles like the clock.
  const toggleCalFit = useCallback(() => {
    const next = nextCalendarFit(calFit)
    setCalFit(next)
    saveSettings({ calendar_fit: next })
  }, [calFit])

  // The zone this account authors times in. It exists for the scheduling links:
  // the app writes non-all-day events as floating local wall time, which names
  // no instant on its own, so the busy-set behind a public booking page has to
  // be told which clock they were written on. Unset, it falls back to the
  // link's own zone — which is a per-link field that may be anywhere, and when
  // the two differed the owner's real appointments were offered as free time.
  //
  // A cycle rather than a picker: the answer is almost always "wherever I am",
  // and a 400-entry zone list for a setting most accounts never need is a worse
  // trade than one button that adopts this device's zone.
  const toggleHomeTz = useCallback(() => {
    const next = homeTz ? '' : Intl.DateTimeFormat().resolvedOptions().timeZone
    setHomeTz(next)
    saveSettings({ home_timezone: next })
  }, [homeTz])

  // 12- or 24-hour clock. Two values, so the row cycles like the theme rather
  // than offering a picker.
  const changeDayCapacity = useCallback((next: number | null) => {
    setDayCapacity(next)
    // -1 CLEARS, the same sentinel this feature uses on every other surface.
    // It is needed here specifically because `store.update_settings` merges
    // shallowly and SKIPS None — so sending null would leave the old value in
    // place and the owner could never get back to "never said" once they had
    // said something. 0 cannot be the clear: "I do not work today" is a real
    // capacity, and the whole point of the null case is that it is different
    // from a zero-length day.
    saveSettings({ day_capacity_minutes: next ?? -1 })
  }, [])

  const changeDayCapacityByWeekday = useCallback((next: Record<string, number>) => {
    setDayCapacityByWeekday(next)
    saveSettings({ day_capacity_by_weekday: next })
  }, [])

  const toggleTimeFormat = useCallback(() => {
    const next = nextTimeFormat(timeFormat)
    setTimeFormat(next)
    saveSettings({ time_format: next })
  }, [timeFormat])

  // Live updates: a server-side *data* change bumps `rev`, which the views
  // watch. One user action can publish several events in a burst (e.g. a move
  // is a delete + create) — debounce so they coalesce into a single refetch pass.
  //
  // A settings write is not a data change. It is published to every subscriber
  // including the tab that made it, and bumping `rev` for it cost 1 + N requests
  // per event in TasksView (and 1 + N more in HomeView) — so one drag of an
  // appearance slider, which writes on every step, became a request storm that
  // also replaced the tasks array under any optimistic paint in flight. UI
  // preferences have nothing to say about task data, so they are not a reason
  // to refetch it.
  // Declared here rather than beside the other callbacks below because the SSE
  // effect needs it: an expired session is invisible to EventSource, so the
  // reconnect loop probes over HTTP and reports back through this.
  const onExpire = useCallback(() => setAuth('out'), [])

  useEffect(() => {
    if (auth !== 'in') return
    let timer: ReturnType<typeof setTimeout> | undefined
    const unsubscribe = subscribe((type) => {
      if (type === 'settings_updated') return
      clearTimeout(timer)
      timer = setTimeout(() => setRev((r) => r + 1), 250)
    }, onExpire)
    return () => { clearTimeout(timer); unsubscribe() }
  }, [auth, onExpire])

  // Dismiss the settings menu on an outside click (like Søren's). Escape is
  // SettingsMenu's own: it has a drill-down to unwind — the archived-calendar
  // agenda, then the section, then the menu — and closing outright from here
  // would skip those steps.
  useEffect(() => {
    if (!settingsOpen) return
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node
      if (settingsRef.current?.contains(t) || gearRef.current?.contains(t)) return
      setSettingsOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [settingsOpen])

  const changeTheme = useCallback((next: 'light' | 'dark') => {
    applyTheme(next)
    // Persist to the account so the choice follows the user to other browsers.
    saveSettings({ theme: next })
  }, [applyTheme])

  const toggleTheme = useCallback(() => {
    changeTheme(theme === 'dark' ? 'light' : 'dark')
  }, [theme, changeTheme])

  // Logging out clears the mirror; an expired session deliberately does not,
  // since it is usually the same person about to sign back in and keeping it
  // makes that instant.
  // Tear the UI down only if the sign-out actually landed. POST /api/logout is
  // the only thing that revokes the session token and the only thing that can
  // clear the HttpOnly cookie — JS cannot. Putting setAuth('out') in a `finally`
  // showed the login card either way, so a failed request left a live session
  // and a valid cookie behind while the user believed they were signed out, and
  // the rejection escaped an async onClick as an unhandled promise rejection.
  // A 401 is the one failure that means it worked: the session is already gone.
  const onLogout = async () => {
    try {
      await api.logout()
    } catch (e) {
      if (!(e instanceof AuthError)) {
        showToast("Couldn't sign out — you are still signed in on this device.")
        return
      }
    }
    clearCache()
    setCacheUser('')
    setAuth('out')
  }

  // While /api/me is in flight the shell paints anyway — the tab strip is real
  // (seeded from the boot cache) and a click on it sticks, on the app's own
  // rule that a deliberate choice beats a stored one. This used to be
  // `return null`: a blank page for the first of four sequential round trips.
  const booting = auth === 'loading'

  // The provider sits above the auth branch, not inside the signed-in one:
  // inside, resolving the session would swap the root element type and remount
  // everything under it. `enabled` is what keeps it from talking to a server
  // that has not yet said who we are.
  return (
    <DataProvider rev={rev} onExpire={onExpire} taskGroups={taskGroups} enabled={auth === 'in'}>
      <TimeFormatProvider value={timeFormat}>
      {auth === 'out'
        ? <Login onLogin={(u) => { setCacheUser(u); setUser(u); setAuth('in') }} />
        : (
    // One shell for both booting and signed in, rather than two trees swapped
    // over: React reconciles by element type, so a different root would throw
    // the boot markup away and mount a fresh tree — losing the very frame this
    // exists to paint (and any click already in flight against it).
    <div className="shell">
      <div className="topbar">
        <span className="brand">Smylte<span className="dot">.</span></span>
        {/* The strip SCROLLS on a phone (see app.css), which means the tab you
            are actually on can start out beyond the right edge — five tabs come
            to more than a 390px bar holds. Nothing else brings it back, so the
            active one is scrolled into view whenever it changes and on the
            first paint, which is the reload case: land on Scheduling, reload,
            and without this the bar opens showing Today with no indication of
            where you are.

            `inline: 'nearest'` so a tab already visible does not jog the strip,
            and `block: 'nearest'` so this never scrolls the PAGE vertically —
            the default is 'start', which would drag the whole view. */}
        <div className="tabs" ref={tabsRef}>
          {tabOrder.map((t) => (
            <button key={t} className={`tab ${tab === t ? 'active' : ''}`}
              ref={t === tab ? activeTabRef : undefined}
              onClick={() => changeTab(t)}>
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>
        <span className="spacer" />
        {booting ? null : (
        <button ref={gearRef} className={`icon-btn ${settingsOpen ? 'active' : ''}`}
          title="Settings" aria-label="Settings" onClick={() => setSettingsOpen((o) => !o)}>
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
            strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        )}

        {settingsOpen && (
          <SettingsMenu panelRef={settingsRef}
            theme={theme} onToggleTheme={toggleTheme}
            onCustomizeAppearance={() => { setSettingsOpen(false); setAppearanceOpen(true) }}
            tabOrder={tabOrder} startTab={startTab}
            onTabOrderChange={changeTabOrder} onStartTabChange={changeStartTab}
            timeFormat={timeFormat} onToggleTimeFormat={toggleTimeFormat}
            dayCapacity={dayCapacity} onDayCapacityChange={changeDayCapacity}
            dayCapacityByWeekday={dayCapacityByWeekday}
            onDayCapacityByWeekdayChange={changeDayCapacityByWeekday}
            homeTz={homeTz} onToggleHomeTz={toggleHomeTz}
            calFit={calFit} onToggleCalFit={toggleCalFit}
            archivedCals={archivedCals} onArchivedCalsChange={changeArchivedCals}
            showCompleted={showCompleted} onToggleShowCompleted={toggleShowCompleted}
            user={user} sessionTtl={sessionTtl} onCycleSessionTtl={cycleSessionTtl}
            onLogout={onLogout} onExpire={onExpire}
            onClose={() => setSettingsOpen(false)} />
        )}
      </div>
      {booting && <div className="work"><div className="content" aria-busy="true" /></div>}
      {!booting && tab === 'tasks' && (
        <TasksView onExpire={onExpire} view={tasksView} onView={changeTasksView}
          sideCollapsed={sideCollapsed} onToggleSide={toggleSide}
          hiddenLists={hiddenLists} onHiddenListsChange={changeHiddenLists}
          groups={taskGroups} onGroupsChange={changeTaskGroups}
          collapsedGroups={collapsedGroups} onCollapsedGroupsChange={changeCollapsedGroups}
          collapsedTasks={collapsedTasks} onCollapsedTasksChange={changeCollapsedTasks}
          showCompleted={showCompleted} />
      )}
      {!booting && tab === 'calendar' && (
        <CalendarView onExpire={onExpire} cursor={cursor} onCursorChange={setCursor}
          sideCollapsed={sideCollapsed} onToggleSide={toggleSide}
          hiddenCalendars={hiddenCals} onHiddenCalendarsChange={changeHiddenCals}
          archivedCalendars={archivedCals} onArchivedCalendarsChange={changeArchivedCals}
          calTaskLists={calTaskLists} onCalTaskListsChange={changeCalTaskLists}
          calShowDone={calShowDone} onCalShowDoneChange={toggleCalShowDone}
          fit={calFit} />
      )}
      {!booting && tab === 'scheduling' && <SchedulingView rev={rev} onExpire={onExpire} />}
      {!booting && tab === 'today' && (
        // The same two calendar-visibility sets the Home dashboard is handed,
        // and read-only here for the same reason: the Calendar tab owns editing
        // (and pruning) them. Passing them is not cosmetic — TodayView asks the
        // data layer for the same window over the same calendar SET, and
        // `requestWindow` keys its dedupe on that set, so a Today tab that
        // asked over the archived calendars too would re-fan-out over every
        // calendar on each switch between the two tabs.
        <TodayView rev={rev} onExpire={onExpire}
          hiddenCalendars={hiddenCals} archivedCalendars={archivedCals} />
      )}
      {!booting && tab === 'home' && (
        <HomeView rev={rev} onExpire={onExpire}
          layout={dashboard} onLayoutChange={changeDashboard}
          hiddenCalendars={hiddenCals} archivedCalendars={archivedCals} />
      )}
      {appearanceOpen && (
        <AppearancePanel appearance={appearance} onChange={changeAppearance}
          mode={theme === 'dark' ? 'dark' : 'light'} onMode={changeTheme}
          onClose={() => setAppearanceOpen(false)} />
      )}
      {toast && (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setToast(null)}>✕</button>
        </div>
      )}
    </div>
        )}
      </TimeFormatProvider>
    </DataProvider>
  )
}


