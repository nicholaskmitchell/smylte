import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  DEFAULT_CALENDAR_FIT, isCalendarFit, nextCalendarFit, type CalendarFit,
} from './calendar'
import { sanitizeLayout } from './dashboard'
import { isSessionTtl, nextSessionTtl } from './session'
import {
  DEFAULT_TIME_FORMAT, isTimeFormat, nextTimeFormat, type TimeFormat,
} from './time'
import { sanitizeCapacityByWeekday } from './capacity'
import {
  DEFAULT_DIGEST_TIME, DEFAULT_EVENT_LEAD_MINUTES, isDigestTime,
  sanitizeEventLead, sanitizeTriggers, type Trigger,
} from './notifications'
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
import { DEFAULT_LANGUAGE, deviceLanguage, isLanguage, type Language } from './lang'
import { I18nProvider } from './i18n'
import { translate } from './i18n/index'
import { AppearancePanel } from './components/AppearancePanel'
import { SettingsMenu } from './components/SettingsMenu'

// 'offline' is NOT 'out'. A server that cannot be reached is not a session that
// has gone away — the rule `api.ts`'s SSE loop already states and enforces ("a
// server that is down is not a session that is gone, and signing a live session
// out on one 502 from the tunnel would be a worse bug than the one this fixes").
// Boot used to collapse the two, so any transport failure rendered the sign-in
// card over a perfectly valid cookie AND flipped `enabled` false, which put the
// disk mirror's last-known-good data out of reach from the very screen that had
// nothing else to show.
type Auth = 'loading' | 'in' | 'out' | 'offline'

// How long boot waits for `/api/me` before calling it unreachable. A half-open
// socket neither resolves nor rejects, and this one call decides whether the app
// renders at all.
const BOOT_TIMEOUT_MS = 15_000

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
  // Whether the opening tab has been restored for this signed-in session. The
  // settings read re-runs on every `settings_updated`; the tab restore inside
  // it must not.
  const tabRestored = useRef(false)
  // PUTs issued and not yet settled. `pendingPatch` empties when the request is
  // ISSUED, so it alone cannot tell whether our own write has landed.
  const writesInFlight = useRef(0)
  // Every settings key this tab has written, in order, appended at the GESTURE.
  // The settings read snapshots its length before issuing and reads the tail
  // when it answers, so it knows which of the values it is holding the user has
  // since changed. An append-only list rather than a set because the question is
  // "since when", not "ever".
  const writeLog = useRef<string[]>([])
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
  const [language, setLanguage] = useState<Language>(DEFAULT_LANGUAGE)
  // App's own translator rather than `useT()`, because App is what RENDERS the
  // provider: a hook read here would see the default context, not the value one
  // line of JSX below it, and the top bar would stay English on a German
  // account. It owns `language` outright, so it needs no context to ask.
  const tr = useMemo(
    () => (key: string, vars?: Parameters<typeof translate>[2]) =>
      translate(language, key, vars),
    [language])
  // How long a day is expected to hold. Null is "never said", and it stays null
  // rather than defaulting to an assumed working day — see
  // `service._effective_capacity`, which every reader of this agrees with.
  const [dayCapacity, setDayCapacity] = useState<number | null>(null)
  const [dayCapacityByWeekday, setDayCapacityByWeekday] =
    useState<Record<string, number>>({})
  const [homeTz, setHomeTz] = useState('')     // '' = fall back to each link's zone
  // Notification rules. The override map is SPARSE — {} means every rule is at
  // its own default — so an untouched account and one that toggled a rule back
  // to its default are the same state, which is what makes adding a rule later
  // safe. See notifications.ts.
  const [notifyTriggers, setNotifyTriggers] =
    useState<Partial<Record<Trigger, boolean>>>({})
  const [notifyEnabled, setNotifyEnabled] = useState(false)
  const [notifyChatId, setNotifyChatId] = useState('')
  // The token itself never comes back from the server (it is write-only over
  // HTTP), so what the UI holds is whether one is stored and which bot it is.
  const [notifyTokenSet, setNotifyTokenSet] = useState(false)
  const [notifyBotId, setNotifyBotId] = useState('')
  const [notifyDigestTime, setNotifyDigestTime] = useState(DEFAULT_DIGEST_TIME)
  const [notifyEventLead, setNotifyEventLead] = useState(DEFAULT_EVENT_LEAD_MINUTES)
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
  // A SECOND revision counter, for settings alone. `rev` drives the task and
  // event refetch, and bumping it on a preference change is the request storm
  // the SSE handler's early return was added to stop — but dropping the event
  // outright left this tab holding whatever the settings blob said when it
  // loaded. See the SSE effect and `store.update_settings`' shallow merge.
  const [settingsRev, setSettingsRev] = useState(0)
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
  // NULL means "never arranged", `[]` means "deliberately empty", and they used
  // to be the same value. `HomeView` reads an empty array as "show the stock
  // five", which is right for a new account and wrong the moment the owner
  // removes their last module — Remove put five modules back on the board. One
  // value cannot answer both questions, so there are two.
  const [dashboard, setDashboard] = useState<DashboardModule[] | null>(null)
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

  // Bumped by the Retry button and by a recovery signal, to re-run boot.
  const [bootTry, setBootTry] = useState(0)
  const retryBoot = useCallback(() => setBootTry((n) => n + 1), [])

  useEffect(() => {
    // The cache is per-account and keyed by name, so a different user simply
    // misses rather than reading someone else's rows; clearing on a change is
    // quota hygiene. `setCacheUser` runs before `setAuth('in')` so the views —
    // which seed from the cache as they mount — never race it.
    sweepOldVersions()
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), BOOT_TIMEOUT_MS)
    let alive = true
    api.me(ctl.signal)
      .then((m) => {
        if (!alive) return
        setCacheUser(m.user); setUser(m.user); setAuth('in')
      })
      // BRANCHED on the error. `j()` produces `AuthError` only for a 401 — a
      // dropped connection rejects with a TypeError, a 5xx with HttpError, an
      // abort with AbortError — and all of them used to land in one
      // `catch(() => setAuth('out'))`.
      .catch((e) => {
        if (!alive) return
        setAuth(e instanceof AuthError ? 'out' : 'offline')
      })
      .finally(() => clearTimeout(timer))
    return () => { alive = false; ctl.abort(); clearTimeout(timer) }
  }, [bootTry])

  // Re-probe when the machine says it might work now, so a laptop that was shut
  // while offline is signed in by the time its owner looks at it rather than
  // waiting on a tap. Only while offline: `visibilitychange` fires constantly in
  // ordinary use and there is nothing to re-probe in any other state.
  useEffect(() => {
    if (auth !== 'offline') return
    const wake = () => {
      if (document.visibilityState === 'visible') retryBoot()
    }
    window.addEventListener('online', retryBoot)
    document.addEventListener('visibilitychange', wake)
    return () => {
      window.removeEventListener('online', retryBoot)
      document.removeEventListener('visibilitychange', wake)
    }
  }, [auth, retryBoot])

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
    // A sign-out clears the restore latch, so signing back in (which never
    // remounts this component) opens where the account says again.
    if (auth !== 'in') { tabRestored.current = false; return }
    settingsFailed.current = false
    // Where the write log stands as this read is ISSUED. Anything appended
    // after this point is a preference the user changed while the read was in
    // flight, and applying the payload's value for it would revert their
    // gesture. See `keep` below.
    const writesBefore = writeLog.current.length
    api.getSettings()
      .then((s) => {
        // The generalisation of `tabTouched`. The read applied its whole
        // payload unconditionally, and the gear is clickable the instant
        // `/api/me` returns — the same commit that ISSUES this request — so the
        // entire read RTT was a window in which a gesture could be silently
        // undone. `get_settings` takes the backend's single global service lock,
        // which is also held across CalDAV round trips during a sync sweep, so
        // that window is seconds, not milliseconds.
        //
        // The author guarded exactly one field, `tabTouched` for the tab, and
        // left every other setter to clobber whatever the user had just chosen:
        // the row showed the account's old value, the account held the new one,
        // and nothing said so — after which the next gesture cycled from the
        // wrong value and, for an array preference, wrote the merged-wrong array
        // back.
        //
        // Keyed on WHEN, not on whether: only keys written between this
        // request being issued and its answer arriving are held back. A read
        // issued afterwards — every `settings_updated` refetch, which already
        // waits for our own PUT to land — carries the newer truth and is applied
        // in full, so another device's change still reaches a tab that has
        // touched the same preference.
        const touched = new Set(writeLog.current.slice(writesBefore))
        const keep = (k: keyof Settings) => !touched.has(k as string)

        if (keep('theme') && (s.theme === 'dark' || s.theme === 'light')) applyTheme(s.theme)
        const order = sanitizeTabOrder(s.tab_order)
        const start = sanitizeTabStart(s.start_tab)
        if (keep('tab_order')) setTabOrder(order)
        if (keep('start_tab')) setStartTab(start)
        // Restoring the opening tab is a FIRST-LOAD action, not something to
        // redo on every read. This effect now re-runs on `settingsRev` too —
        // any settings write on any device — and `tabTouched` is false for a
        // tab the user simply has not switched, so without this latch a theme
        // change on the phone yanked the open desktop view to whatever tab the
        // account last recorded and `cacheTab` persisted the yank.
        if (!tabTouched.current && !tabRestored.current && keep('last_tab')) {
          tabRestored.current = true
          const opening = resolveStartTab(start, isTab(s.last_tab) ? s.last_tab : undefined, order)
          setTab(opening)
          cacheTab(opening)
        }
        if (keep('tasks_view')
          && (s.tasks_view === 'list' || s.tasks_view === 'day3' || s.tasks_view === 'week')) {
          setTasksView(s.tasks_view)
        }
        if (keep('sidebar_collapsed') && typeof s.sidebar_collapsed === 'boolean') {
          setSideCollapsed(s.sidebar_collapsed)
        }
        if (keep('hidden_calendars') && Array.isArray(s.hidden_calendars)) {
          setHiddenCals(s.hidden_calendars.filter((x) => typeof x === 'string'))
        }
        if (keep('archived_calendars') && Array.isArray(s.archived_calendars)) {
          setArchivedCals(s.archived_calendars.filter((x) => typeof x === 'string'))
        }
        if (keep('hidden_lists') && Array.isArray(s.hidden_lists)) {
          setHiddenLists(s.hidden_lists.filter((x) => typeof x === 'string'))
        }
        if (keep('task_groups') && Array.isArray(s.task_groups)) {
          // Defend against a malformed blob (hand-edited settings, an old
          // schema): keep only well-formed groups with a real id and name.
          setTaskGroups(s.task_groups.filter((g): g is TaskGroup =>
            !!g && typeof g.id === 'string' && typeof g.name === 'string' &&
            Array.isArray(g.lists)).map((g) => ({
              id: g.id, name: g.name, lists: g.lists.filter((x) => typeof x === 'string'),
            })))
        }
        if (keep('collapsed_groups') && Array.isArray(s.collapsed_groups)) {
          setCollapsedGroups(s.collapsed_groups.filter((x) => typeof x === 'string'))
        }
        if (keep('collapsed_tasks') && Array.isArray(s.collapsed_tasks)) {
          setCollapsedTasks(s.collapsed_tasks.filter((x) => typeof x === 'string'))
        }
        if (keep('show_completed_tasks') && typeof s.show_completed_tasks === 'boolean') {
          setShowCompleted(s.show_completed_tasks)
        }
        if (keep('time_format') && isTimeFormat(s.time_format)) setTimeFormat(s.time_format)
        if (keep('language') && isLanguage(s.language)) setLanguage(s.language)
        // Treated as hand-edited, like every other settings value here. A
        // non-number default is dropped to null rather than coerced: a capacity
        // read out of junk would be a number nobody gave, which is the one
        // thing this feature must not produce.
        // A negative stored value is the CLEAR sentinel at rest, and reads back
        // as "never said" — the same answer the server's resolution gives it.
        // These two are the reason `keep` is a predicate rather than a filter
        // over the payload: they are the only setters here that run
        // UNCONDITIONALLY, so a stripped key would not be skipped — it would be
        // applied as `undefined` and read back as "never said".
        if (keep('day_capacity_minutes')) {
          setDayCapacity(
            typeof s.day_capacity_minutes === 'number'
              && Number.isFinite(s.day_capacity_minutes)
              && s.day_capacity_minutes >= 0
              ? s.day_capacity_minutes
              : null)
        }
        if (keep('day_capacity_by_weekday')) {
          setDayCapacityByWeekday(sanitizeCapacityByWeekday(s.day_capacity_by_weekday))
        }
        if (keep('home_timezone') && typeof s.home_timezone === 'string') setHomeTz(s.home_timezone)
        // Re-validated on the way in, like every other value off the wire: the
        // settings blob is one hand-editable JSON document, and an unknown rule
        // name in it must be dropped rather than rendered as a row nothing can
        // turn off.
        if (keep('notifications_enabled') && typeof s.notifications_enabled === 'boolean') {
          setNotifyEnabled(s.notifications_enabled)
        }
        if (keep('notify_telegram_chat_id') && typeof s.notify_telegram_chat_id === 'string') {
          setNotifyChatId(s.notify_telegram_chat_id)
        }
        // Guarded like everything else. These two are DERIVED by the server
        // rather than typed here, which is why they looked exempt — but pasting
        // a token sets them optimistically, so a read already in flight would
        // land afterwards and put the row back to "no token" a moment after one
        // was pasted. `changeNotifyToken` logs them for exactly this.
        if (keep('notify_telegram_bot_token_set')) {
          setNotifyTokenSet(s.notify_telegram_bot_token_set === true)
        }
        if (keep('notify_telegram_bot_id')) {
          setNotifyBotId(typeof s.notify_telegram_bot_id === 'string' ? s.notify_telegram_bot_id : '')
        }
        if (keep('notify_triggers')) setNotifyTriggers(sanitizeTriggers(s.notify_triggers))
        if (keep('notify_digest_time') && isDigestTime(s.notify_digest_time)) {
          setNotifyDigestTime(s.notify_digest_time)
        }
        if (keep('notify_event_lead_minutes')
            && typeof s.notify_event_lead_minutes === 'number') {
          setNotifyEventLead(sanitizeEventLead(s.notify_event_lead_minutes))
        }
        if (keep('calendar_task_lists') && Array.isArray(s.calendar_task_lists)) {
          setCalTaskLists(s.calendar_task_lists.filter((x) => typeof x === 'string'))
        }
        if (keep('calendar_show_done_tasks') && typeof s.calendar_show_done_tasks === 'boolean') {
          setCalShowDone(s.calendar_show_done_tasks)
        }
        if (keep('calendar_fit') && isCalendarFit(s.calendar_fit)) setCalFit(s.calendar_fit)
        if (keep('session_ttl_s') && isSessionTtl(s.session_ttl_s)) setSessionTtl(s.session_ttl_s)
        // Both blobs are re-validated here rather than trusted: they are the
        // two settings a user can hand-edit or import a file into, and an
        // unknown token or a garbage grid cell should degrade to the default
        // instead of reaching the CSSOM or the layout engine.
        if (keep('appearance') && s.appearance) {
          const clean = sanitizeAppearance(s.appearance)
          setAppearance(clean)
          cacheAppearance(clean)
        }
        // Only when the KEY is present. An account that has never arranged
        // anything has no `dashboard` in its settings at all, and that absence
        // is what `null` records — so a settings read must not turn it into an
        // empty array on its way past.
        if (keep('dashboard') && Array.isArray(s.dashboard)) setDashboard(sanitizeLayout(s.dashboard))
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
        showToast(tr('app.settingsLoadFailed'))
      })
  }, [auth, settingsRev, applyTheme, showToast, tr])

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
    'calendar_fit', 'time_format', 'language',
    // The trigger map is READ-MODIFY-WRITE — one toggle rebuilds the whole
    // object — so writing it after a failed read would replace the account's
    // real overrides with one built from `{}`, silently re-enabling every rule
    // they had turned off. The digest time and the lead are NOT here: each
    // carries the value just entered in a field, so what is written is what was
    // asked for whether or not the read landed.
    'notify_triggers',
    // A toggle and a text field the user types into. Both are single-value
    // writes, so they are NOT read-modify-write — but a late read landing
    // after either was changed would still revert the gesture, which is what
    // `keep` guards on the read side; they stay out of this list for the same
    // reason `day_capacity_minutes` does.

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
    writeLog.current.push(...Object.keys(patch))
    if (settingsFailed.current) {
      const held = MERGED_SETTINGS.filter((k) => k in patch)
      if (held.length) {
        patch = Object.fromEntries(
          Object.entries(patch).filter(([k]) => !held.includes(k as never))) as Settings
        showToast(tr('app.settingsNotLoaded'))
      }
      if (!Object.keys(patch).length) return
    }
    // Counted, not flagged: two gestures can be in flight at once (an
    // immediate `saveSettings` alongside a debounced one), and the refetch
    // guard below must wait for the LAST of them.
    writesInFlight.current += 1
    api.putSettings(patch).catch((e) => {
      if (e instanceof AuthError) { setAuth('out'); return }
      // Offline is the ordinary case and the local state stands in fine; a
      // rejection from a server we *did* reach is what the user needs to know.
      // The server's own words ride along untranslated — see i18n/index.ts on
      // why server text is out of scope — inside a sentence that is not.
      if (e instanceof HttpError) showToast(tr('app.settingsSaveFailed', { error: e.message }))
    }).finally(() => { writesInFlight.current -= 1 })
  }, [showToast, tr])

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
    // Noted HERE, at the gesture, not 400ms later when the PUT goes out: a
    // slider drag that starts inside a slow read's flight has already changed
    // what the user is looking at. (The eventual `saveSettings` notes the same
    // keys again; by then any refetch is already held off by `writesInFlight`,
    // so the repeat cannot suppress another device's value.)
    writeLog.current.push(...Object.keys(patch))
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

  const changeNotifyEnabled = useCallback((next: boolean) => {
    setNotifyEnabled(next)
    saveSettings({ notifications_enabled: next })
  }, [])

  const changeNotifyChatId = useCallback((next: string) => {
    setNotifyChatId(next)
    saveSettingsSoon({ notify_telegram_chat_id: next })
  }, [])

  const changeNotifyToken = useCallback((next: string) => {
    // Optimistic, like every other write here — but on the DERIVED flags, since
    // the token itself is never held locally. An empty string is the explicit
    // Remove, not an accidentally cleared field: the section only calls this
    // with '' from its own Remove control.
    setNotifyTokenSet(!!next)
    setNotifyBotId(next.includes(':') ? next.split(':', 1)[0] : '')
    // The write log is keyed on what the PATCH carries, and the patch carries
    // the token — but what this gesture changed on screen is the two derived
    // flags, and they are what a read in flight would revert. Logged by hand
    // because they are the one pair whose local value has no key of its own on
    // the wire.
    writeLog.current.push('notify_telegram_bot_token_set', 'notify_telegram_bot_id')
    saveSettings({ notify_telegram_bot_token: next })
  }, [])

  const changeNotifyTriggers = useCallback((next: Partial<Record<Trigger, boolean>>) => {
    setNotifyTriggers(next)
    saveSettings({ notify_triggers: next })
  }, [])

  const changeNotifyDigestTime = useCallback((next: string) => {
    // The section only commits a well-formed HH:MM, and the guard is repeated
    // here because the server REJECTS a malformed one rather than filtering it:
    // a bad value would 422 the PUT and take the theme with it.
    if (!isDigestTime(next)) return
    setNotifyDigestTime(next)
    saveSettings({ notify_digest_time: next })
  }, [])

  const changeNotifyEventLead = useCallback((next: number) => {
    const clean = sanitizeEventLead(next)
    setNotifyEventLead(clean)
    saveSettingsSoon({ notify_event_lead_minutes: clean })
  }, [])

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

  /** Chosen from a picker rather than cycled, unlike the toggles around it: the
   *  list will grow past two, and a control you press repeatedly to find the
   *  language you read is the wrong shape for the one setting a reader may not
   *  be able to read the labels of. */
  const changeLanguage = useCallback((next: Language) => {
    setLanguage(next)
    saveSettings({ language: next })
  }, [])

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
    let settingsTimer: ReturnType<typeof setTimeout> | undefined
    let settingsWaits = 0
    const unsubscribe = subscribe((type) => {
      if (type === 'settings_updated') {
        // Re-read the SETTINGS — but never bump `rev`, which is what the bare
        // early return here was protecting: one appearance-slider drag would
        // otherwise fire a full lists+tasks refetch per step.
        //
        // Dropping the event entirely was the other half of the problem. This is
        // the only place `api.getSettings` is reached from, and its effect keys
        // on an auth transition, so a tab open since this morning held this
        // morning's blob for the rest of the day. `store.update_settings` merges
        // SHALLOWLY, and every list-shaped preference — task_groups,
        // hidden_lists, archived_calendars, dashboard, tab_order, appearance —
        // is written back WHOLE from local state. So creating a group on the
        // phone and then renaming a different one in the stale desktop tab sent
        // `{task_groups: [<this morning's array>]}` and the new group was gone
        // from the account, silently, on both devices. Same shape wipes a theme
        // saved on another device.
        //
        // Held off while this tab has a write of its own outstanding: re-reading
        // now would paint the value the write is about to replace.
        //
        // Two things that check gets wrong if it is a bare `pendingPatch` test
        // at the moment the event ARRIVES. `pendingPatch` is emptied when the
        // debounced PUT is ISSUED, not when it lands, so the whole flight of the
        // request looked idle — and the server publishes `settings_updated` to
        // every subscriber INCLUDING the tab that wrote it, so the event racing
        // that window is exactly the common case. And a gesture that starts
        // inside the 250ms debounce was never seen at all.
        //
        // So: check on the trailing edge, count in-flight requests too, and WAIT
        // rather than drop. Dropping is not safe here — the event may be another
        // device's, and this is the only path that re-reads settings, so a
        // dropped one leaves the tab holding a stale blob that the next
        // list-shaped write sends back whole. Capped at ~5s so a hung request
        // cannot silence the refetch for good; a refetch that does race a write
        // is a flicker, and the trailing write still wins.
        clearTimeout(settingsTimer)
        const armSettingsRefetch = () => {
          settingsTimer = setTimeout(() => {
            const busy = Object.keys(pendingPatch.current).length > 0
              || writesInFlight.current > 0
            if (busy && settingsWaits < 20) { settingsWaits += 1; armSettingsRefetch(); return }
            settingsWaits = 0
            setSettingsRev((r) => r + 1)
          }, 250)
        }
        armSettingsRefetch()
        return
      }
      clearTimeout(timer)
      timer = setTimeout(() => setRev((r) => r + 1), 250)
    }, onExpire)
    return () => {
      clearTimeout(timer)
      clearTimeout(settingsTimer)
      unsubscribe()
    }
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
        showToast(tr('app.logoutFailed'))
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
      {/* Signed out there is no account to ask, so the browser's preference is
          the best answer available — see `deviceLanguage`. It is used ONLY in
          that state: once a session resolves the account's setting wins, back to
          English included. */}
      <I18nProvider value={auth === 'out' ? deviceLanguage() : language}>
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
              {tr(TAB_LABELS[t])}
            </button>
          ))}
        </div>
        <span className="spacer" />
        {booting ? null : (
        <button ref={gearRef} className={`icon-btn ${settingsOpen ? 'active' : ''}`}
          title={tr('app.settings')} aria-label={tr('app.settings')}
          onClick={() => setSettingsOpen((o) => !o)}>
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
            language={language} onLanguageChange={changeLanguage}
            dayCapacity={dayCapacity} onDayCapacityChange={changeDayCapacity}
            dayCapacityByWeekday={dayCapacityByWeekday}
            onDayCapacityByWeekdayChange={changeDayCapacityByWeekday}
            homeTz={homeTz} onToggleHomeTz={toggleHomeTz}
            calFit={calFit} onToggleCalFit={toggleCalFit}
            archivedCals={archivedCals} onArchivedCalsChange={changeArchivedCals}
            showCompleted={showCompleted} onToggleShowCompleted={toggleShowCompleted}
            notifyEnabled={notifyEnabled} onNotifyEnabledChange={changeNotifyEnabled}
            notifyChatId={notifyChatId} onNotifyChatIdChange={changeNotifyChatId}
            notifyTokenSet={notifyTokenSet} notifyBotId={notifyBotId}
            onNotifyTokenChange={changeNotifyToken}
            notifyTriggers={notifyTriggers} onNotifyTriggersChange={changeNotifyTriggers}
            notifyDigestTime={notifyDigestTime}
            onNotifyDigestTimeChange={changeNotifyDigestTime}
            notifyEventLead={notifyEventLead}
            onNotifyEventLeadChange={changeNotifyEventLead}
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
      {/* The shell stays, and says why it is short. `auth === 'offline'` means
          `/api/me` could not be reached, NOT that the session ended — so the
          cached rows the views seed from are still on screen underneath this,
          which is the whole point of the disk mirror. Retry re-runs boot; so
          does coming back online or returning to the tab. */}
      {auth === 'offline' && (
        <div className="offline-bar" role="status">
          <span>{tr('app.offline')}</span>
          <button className="btn ghost" onClick={retryBoot}>{tr('app.retry')}</button>
        </div>
      )}
      {toast && (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button className="icon-btn" aria-label={tr('app.dismiss')}
            onClick={() => setToast(null)}>✕</button>
        </div>
      )}
    </div>
        )}
      </TimeFormatProvider>
      </I18nProvider>
    </DataProvider>
  )
}


