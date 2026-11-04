// Settings: a left nav beside a panel on a desktop, a drill-down sheet on a
// phone. Ported from Søren, whose settings menu hit this wall first (see its
// `ui(settings): a left nav on a desktop, a drill-down sheet on a phone`).
//
// It replaced one flat list of rows. A list has no room to grow: every new
// setting made the popover taller, the four `.hintline`s explaining controls
// ended up stacked at the bottom far from what they explain, and on a phone the
// popover hung off `.topbar` under an `82vh` cap while `.shell` is
// `overflow: hidden` — so whatever fell past the fold could not be scrolled to.
// A nav column extends downward for free, and section count stops mattering.
//
// Nav and panel share the width on a desktop and TAKE TURNS on a phone: an
// index of sections, then the one you tapped, with a back arrow and the
// section's name in the title bar. `data-view` is what CSS gates that on.

import { useCallback, useEffect, useRef, useState } from 'react'
import { DEFAULT_CALENDAR_FIT, calendarFitKey, type CalendarFit } from '../calendar'
import { useIsMobile, useEscape } from '../hooks'
import { PendingWrite, UnsentInput, useLayer, usePendingCount, useUnsentCount } from '../layers'
import { SESSION_DEFAULT, sessionKey } from '../session'
import { DEFAULT_TIME_FORMAT, timeFormatKey, type TimeFormat } from '../time'
import { DEFAULT_LANGUAGE, LANGUAGES, languageLabel, type Language } from '../lang'
import { useT } from '../i18n'
import type { List } from '../api'
import type { Tab, TabStart } from '../tabs'
import { DEFAULT_LAYOUT, layoutKey, type Layout } from '../layout'
import { ArchivedCalendarsSection } from './ArchivedCalendarsSection'
import { ConnectionsSection } from './ConnectionsSection'
import { DisplaysSection } from './DisplaysSection'
import { SharesSection } from './SharesSection'
import { DeveloperSection } from './DeveloperSection'
import { Fold, HowFold } from './SettingsFold'
import { PLAN_ON_DUE_TODAY, STALE_OVERDUE_DAYS } from './TodayView'
import { DesktopSection } from './DesktopSection'
import { TabsSection } from './TabsSection'
import { CapacitySection } from './CapacitySection'
import { FocusSection } from './FocusSection'
import type { FocusSettings } from '../focus'
import { NotificationsSection } from './NotificationsSection'
import { MailSection } from './MailSection'
import type { Trigger } from '../notifications'

// The nav, in order. `label` is the accessible name of both the nav item and,
// on a phone, the title bar — Søren's test asserts they agree.
// `label` is now a catalogue KEY rather than the text. The comment above still
// holds and is the reason it has to be: the nav item and the phone title bar
// both render it, a test asserts they agree, and two `tr()` calls on one key
// agree by construction where two translations of one English word need not.
//
// In the order someone looks for things (the tidy Søren's Settings had first):
// how the account measures time, how the app looks, then the two kinds of item,
// then what reaches you and what you hand out, and the account last. Each has a
// one-line `blurb`, shown under its name in the phone's index and as the nav
// item's tooltip on a desktop. Developer's display previews moved into
// Displays, which is what they preview.
const SECTIONS = [
  { id: 'general', label: 'settings.section.general', blurb: 'settings.blurb.general' },
  { id: 'appearance', label: 'settings.section.appearance', blurb: 'settings.blurb.appearance' },
  { id: 'tasks', label: 'settings.section.tasks', blurb: 'settings.blurb.tasks' },
  { id: 'calendar', label: 'settings.section.calendar', blurb: 'settings.blurb.calendar' },
  { id: 'focus', label: 'settings.section.focus', blurb: 'settings.blurb.focus' },
  { id: 'notifications', label: 'settings.section.notifications', blurb: 'settings.blurb.notifications' },
  { id: 'mail', label: 'settings.section.mail', blurb: 'settings.blurb.mail' },
  { id: 'shares', label: 'settings.section.shares', blurb: 'settings.blurb.shares' },
  { id: 'displays', label: 'settings.section.displays', blurb: 'settings.blurb.displays' },
  { id: 'account', label: 'settings.section.account', blurb: 'settings.blurb.account' },
  { id: 'about', label: 'settings.section.about', blurb: 'settings.blurb.about' },
] as const

type Section = (typeof SECTIONS)[number]['id']
export type SettingsSection = Section

// AGPL §13 asks that a modified copy reachable over a network PROMINENTLY OFFER
// its source to the people using it, and a link in the running app is the
// customary way to answer. So it lives in the nav rather than in a README:
// a README is not something a person interacting with the server ever sees.
//
// One constant, and the label is derived from it rather than written twice —
// a fork that repoints the href and leaves the visible text naming this
// repository would be worse than no link at all, and two strings are how that
// happens. Change this line and both move.
const SOURCE_URL = 'https://github.com/nicholaskmitchell/smylte'

export function SettingsMenu({
  initialSection,
  layout, onToggleLayout,
  theme, onToggleTheme, onCustomizeAppearance,
  tabOrder, startTab, onTabOrderChange, onStartTabChange,
  timeFormat, onToggleTimeFormat,
  language, onLanguageChange,
  dayCapacity, onDayCapacityChange, dayCapacityByWeekday, onDayCapacityByWeekdayChange,
  homeTz, onToggleHomeTz,
  calFit, onToggleCalFit,
  archivedCals, onArchivedCalsChange,
  showCompleted, onToggleShowCompleted, autoCloseParents, onToggleAutoCloseParents,
  staleOverdue, onStaleOverdueChange,
  planOnDueToday, onTogglePlanOnDueToday,
  focus, onFocusChange,
  notifyEnabled, onNotifyEnabledChange,
  notifyChatId, onNotifyChatIdChange,
  notifyTokenSet, notifyBotId, onNotifyTokenChange,
  notifyTriggers, onNotifyTriggersChange,
  notifyDigestTime, onNotifyDigestTimeChange,
  notifyEveningTime, onNotifyEveningTimeChange,
  notifyEventLead, onNotifyEventLeadChange,
  notifyTaskLead, onNotifyTaskLeadChange,
  mailRev,
  user, sessionTtl, onCycleSessionTtl,
  onLogout, onExpire, onClose, panelRef,
}: {
  /** Where to open, when not at the top. The menu is drawn inside whichever
   *  frame is on screen, so switching the frame remounts it — and the switch
   *  is made from Appearance, which is where it should still be open. */
  initialSection?: Section
  /** The app's frame (see layout.ts). */
  layout: Layout
  onToggleLayout: () => void
  theme: string
  onToggleTheme: () => void
  onCustomizeAppearance: () => void
  tabOrder: Tab[]
  startTab: TabStart
  onTabOrderChange: (next: Tab[]) => void
  onStartTabChange: (next: TabStart) => void
  timeFormat: TimeFormat
  language: Language
  onLanguageChange: (next: Language) => void
  onToggleTimeFormat: () => void
  /** The account-wide working day, or null for "never said". */
  dayCapacity: number | null
  onDayCapacityChange: (next: number | null) => void
  /** Sparse per-weekday exceptions, keyed by the `HABIT_DAYS` names. */
  dayCapacityByWeekday: Record<string, number>
  onDayCapacityByWeekdayChange: (next: Record<string, number>) => void
  homeTz: string
  onToggleHomeTz: () => void
  calFit: CalendarFit
  onToggleCalFit: () => void
  archivedCals: string[]
  onArchivedCalsChange: (next: string[]) => void
  showCompleted: boolean
  onToggleShowCompleted: () => void
  autoCloseParents: boolean
  onToggleAutoCloseParents: () => void
  /** Days past a deadline before the Today strip asks for a decision about a
   *  task rather than offering it. 0 turns that off. */
  staleOverdue: number
  onStaleOverdueChange: (next: number) => void
  /** Whether answering one of those rows with today also puts the task on
   *  today's plan, rather than only moving its deadline there. */
  planOnDueToday: boolean
  onTogglePlanOnDueToday: () => void
  /** The focus clock, every key present (see `sanitizeFocusSettings`). */
  focus: FocusSettings
  onFocusChange: (patch: Partial<FocusSettings>) => void
  notifyEnabled: boolean
  onNotifyEnabledChange: (next: boolean) => void
  notifyChatId: string
  onNotifyChatIdChange: (next: string) => void
  /** Whether a bot token is stored, and which bot. The token itself never comes
   *  back from the server, so this is all the UI has — and all it needs. */
  notifyTokenSet: boolean
  notifyBotId: string
  onNotifyTokenChange: (next: string) => void
  /** Sparse overrides: an absent rule means that rule's own default. */
  notifyTriggers: Partial<Record<Trigger, boolean>>
  onNotifyTriggersChange: (next: Partial<Record<Trigger, boolean>>) => void
  notifyDigestTime: string
  onNotifyDigestTimeChange: (next: string) => void
  notifyEveningTime: string
  onNotifyEveningTimeChange: (next: string) => void
  notifyEventLead: number
  onNotifyEventLeadChange: (next: number) => void
  notifyTaskLead: number
  onNotifyTaskLeadChange: (next: number) => void
  /** Bumped by App on every `mail_updated` event, so the email section can
   *  re-read its status without a poll. */
  mailRev?: number
  user: string
  sessionTtl: number | null
  onCycleSessionTtl: () => void
  onLogout: () => void
  onExpire: () => void
  onClose: () => void
  /** The surface App watches for outside clicks. */
  panelRef: React.RefObject<HTMLDivElement>
}) {
  const isMobile = useIsMobile()
  const [section, setSection] = useState<Section>(initialSection ?? 'general')
  // Only meaningful on a phone. On a desktop the nav is a permanent column, so
  // there is nothing to be "in" and nothing to go back to.
  const [view, setView] = useState<'index' | 'panel'>(initialSection ? 'panel' : 'index')
  // Focus follows the switch. `initialSection` is set by pressing the Layout
  // row, which remounts this menu in the other frame, and by Home's modules,
  // which open it at Email or Shares. Only the first leaves the pressed button
  // gone, which is why focus moves for 'appearance' alone: without it focus
  // falls to <body>, behind the phone's modal sheet or out of the menu
  // altogether.
  const layoutRowRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (initialSection === 'appearance') layoutRowRef.current?.focus()
  // Mount only: this is where the menu opens, not a section it follows.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // The archived-calendar agenda is a step below the Calendar section. It lives
  // here so one back control can unwind the whole stack in order.
  const [viewingCal, setViewingCal] = useState<List | null>(null)
  // The archived-calendar fold, held here because opening an agenda inside it
  // has to keep it open on the way back out.
  const [archivedOpen, setArchivedOpen] = useState(false)
  // The display previews render every mode at once, so only while looked at.
  const [previewsOpen, setPreviewsOpen] = useState(false)

  const panels = useRef<HTMLDivElement>(null)

  const show = useCallback((next: Section) => {
    setSection(next)
    setView('panel')
    setViewingCal(null)
    // A section is a new screenful, so start it at the top.
    if (panels.current) panels.current.scrollTop = 0
  }, [])

  // One step out, wherever we are: out of the agenda, then out of the section,
  // then out of settings. Escape and the back arrow share it so they cannot
  // disagree about the order.
  const back = useCallback(() => {
    if (viewingCal) { setViewingCal(null); return }
    if (isMobile && view === 'panel') { setView('index'); return }
    onClose()
  }, [viewingCal, isMobile, view, onClose])

  // `useEscape(back)`, not `useEscape(onClose)`. The finding said to leave this
  // one hand-rolled because its Escape means "go back one step" rather than
  // "close" — but the hook takes a callback, so the semantics are preserved
  // exactly and this is the last hand-rolled copy. Its own suite covers all
  // three levels (agenda -> section -> closed) and is the control.
  useEscape(back)
  // Back takes the same step. The inline fields in the sections are not layers:
  // they stop Escape at the field and commit on blur, and Back blurs them first
  // (layers.ts), so they commit as a tap on the section's ‹ would.
  //
  // A name typed into an add field, or a password not yet saved, goes only by
  // Enter or its button, and closing Settings throws it away, so Back asks
  // first. While such a name is being added, Back waits, so that a failure
  // still has the section to put it back in. Only on the step that closes:
  // stepping back to the phone's index keeps the section, and its text,
  // mounted underneath.
  const [unsent, reportUnsent] = useUnsentCount()
  const [pending, reportPending] = usePendingCount()
  const closes = !viewingCal && !(isMobile && view === 'panel')
  useLayer(back, {
    dialog: panelRef, unsaved: unsent > 0 && closes, busy: pending > 0 && closes,
  })
  const sheetPress = useRef(false)

  const tr = useT()
  const active = SECTIONS.find((s) => s.id === section)!
  /** A hint, then what it is out of the box: every control says its default. */
  const withDefault = (hint: string, value: string) =>
    `${hint} ${tr('settings.default', { value })}`
  /** Read the stale-overdue field and store it, or put it back.
   *
   *  Clamped rather than refused, unlike the fields whose grammar can fail to
   *  parse: a number input hands back a number or nothing, so "91" is a value
   *  out of range rather than a sentence this cannot read, and the bounds are
   *  the server's own (`SettingsPatch.stale_overdue_days`). An empty or
   *  unreadable field snaps back to what is stored — never to 0, which is the
   *  OFF switch and must only ever be reached deliberately. */
  const commitStale = (el: HTMLInputElement) => {
    const n = Number(el.value)
    if (el.value.trim() === '' || !Number.isFinite(n)) {
      el.value = String(staleOverdue)
      return
    }
    // A NEGATIVE snaps back rather than clamping to 0, because 0 is the OFF
    // switch and `Math.max(0, …)` reached it silently: `<input min={0}>` does
    // not stop -5 being typed, so blurring disabled the triage group without
    // anyone choosing to. Only a value at least 0 is a value; above the ceiling
    // is a number out of range, which the server's own bound clamps.
    if (n < 0) {
      el.value = String(staleOverdue)
      return
    }
    const next = Math.min(90, Math.round(n))
    el.value = String(next)
    if (next !== staleOverdue) onStaleOverdueChange(next)
  }
  // What the title bar says. Beside a visible nav it would only be saying the
  // section's name twice, so on a desktop it stays "Settings".
  const title = viewingCal ? viewingCal.name
    : isMobile && view === 'panel' ? tr(active.label)
    : tr('app.settings')
  // The back arrow appears wherever there is a step to take back.
  const canGoBack = !!viewingCal || (isMobile && view === 'panel')

  const nav = (
    <div className="set-nav" role="tablist" aria-label={tr('settings.sections')}>
      {SECTIONS.map((s) => (
        // `role="tab"`, not a plain button: the topbar already has a *Tasks*
        // tab and so does this nav, and the roles are what keep the two apart.
        <button key={s.id} type="button" role="tab" id={`set-tab-${s.id}`}
          className={`set-nav-item ${section === s.id ? 'active' : ''}`}
          aria-selected={section === s.id} aria-controls={`set-panel-${s.id}`}
          // Named by its label alone, so the blurb reads as a description
          // rather than as part of what the item is called.
          aria-label={tr(s.label)} aria-describedby={`set-blurb-${s.id}`}
          title={tr(s.blurb)}
          onClick={() => show(s.id)}>
          <span className="set-nav-text">
            <span className="set-nav-label">{tr(s.label)}</span>
            <span className="set-nav-blurb" id={`set-blurb-${s.id}`}>{tr(s.blurb)}</span>
          </span>
        </button>
      ))}
    </div>
  )

  const panel = (
    <div className="set-panels" ref={panels}>
      <div className="set-panel" role="tabpanel" id={`set-panel-${section}`}
        aria-labelledby={`set-tab-${section}`}>
        {section === 'general' && (
          <>
            {/* First in the panel, above the clock: it decides what every
                other label on this screen says, so a reader who cannot read
                them should not have to get past them to reach it. */}
            <div className="menu-head">{tr('settings.language')}</div>
            <div className="menu-row">
              <label htmlFor="set-language">{tr('settings.language')}</label>
              {/* A picker, not a cycling toggle like the ones under it. The
                  list will grow past two, and a control you press repeatedly to
                  find the language you read is the wrong shape for the one
                  setting whose labels a reader may not be able to read. */}
              <select className="menu-toggle" id="set-language" value={language}
                aria-label={tr('settings.language.aria')}
                onChange={(e) => onLanguageChange(e.target.value as Language)}>
                {LANGUAGES.map((l) => (
                  // The endonym, so every option is legible to the person who
                  // would choose it — see `LANGUAGE_LABEL`.
                  <option key={l} value={l}>{languageLabel(l)}</option>
                ))}
              </select>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.language.hint'), languageLabel(DEFAULT_LANGUAGE))}
            </div>

            <div className="menu-head">{tr('settings.clock')}</div>
            <div className="menu-row">
              <label>{tr('settings.clock')}</label>
              <button className="menu-toggle" onClick={onToggleTimeFormat}
                aria-label={tr('settings.clock.aria')}>
                {tr(timeFormatKey(timeFormat))}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.clock.short'), tr(timeFormatKey(DEFAULT_TIME_FORMAT)))}
            </div>
            <HowFold title={tr('settings.clock.how')}>{tr('settings.clock.hint')}</HowFold>

            {/* Beside the clock, because both answer "how does this account
                measure time" — and a day's length belongs next to how the day
                is drawn rather than buried under the Tasks panel. */}
            <div className="menu-head">{tr('settings.workingDay')}</div>
            <CapacitySection minutes={dayCapacity} byWeekday={dayCapacityByWeekday}
              onChange={onDayCapacityChange}
              onWeekdayChange={onDayCapacityByWeekdayChange} />

            <div className="menu-head">{tr('settings.timezone')}</div>
            <div className="menu-row">
              <label>{tr('settings.homeTimezone')}</label>
              <button className="menu-toggle" onClick={onToggleHomeTz}
                aria-label={tr('settings.homeTimezone.aria')}
                title={tr('settings.homeTimezone.title')}>
                {/* An IANA zone name is not translated: it is an identifier the
                    server and every other CalDAV client share. */}
                {homeTz || tr('settings.notSet')}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.homeTimezone.hint'), tr('settings.notSet'))}
            </div>
          </>
        )}

        {section === 'appearance' && (
          <>
            {/* First, above the theme: it is the one choice here that moves
                things rather than recolouring them, and the one someone who
                wants the old frame back comes looking for. */}
            <div className="menu-row">
              <label>{tr('settings.layout')}</label>
              <button ref={layoutRowRef} className="menu-toggle" onClick={onToggleLayout}
                aria-label={tr('settings.layout.aria')}>
                {tr(layoutKey(layout))}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.layout.hint'), tr(layoutKey(DEFAULT_LAYOUT)))}
            </div>
            <div className="menu-row">
              <label>{tr('settings.theme')}</label>
              <button className="menu-toggle" onClick={onToggleTheme}>
                {tr(theme === 'dark' ? 'theme.dark' : 'theme.light')}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.theme.hint'), tr('theme.light'))}
            </div>
            <div className="menu-row">
              <label>{tr('settings.appearance')}</label>
              <button className="menu-toggle" aria-label={tr('settings.appearance.aria')}
                onClick={onCustomizeAppearance}>
                {tr('settings.appearance.customize')}
              </button>
            </div>
            <div className="hintline">{tr('settings.appearance.hint')}</div>

            {/* Here rather than under General since the tidy: which views
                the strip or the sidebar shows, and in what order, is how the
                app looks. */}
            <div className="menu-head">{tr('settings.tabs')}</div>
            <TabsSection order={tabOrder} start={startTab} layout={layout}
              onOrderChange={onTabOrderChange} onStartChange={onStartTabChange} />

            <DesktopSection />
          </>
        )}

        {section === 'calendar' && (
          <>
            {/* The agenda is a step below this section, and the title bar already
                names the calendar you are in. Leaving the section's own rows
                above it would put "Calendar window" under a "Retired 2023"
                heading — so the agenda replaces the section rather than
                stacking under it. The list itself stays mounted either way, so
                stepping back does not refetch. */}
            {!viewingCal && (<>
            <div className="menu-row">
              <label>{tr('settings.calendarWindow')}</label>
              <button className="menu-toggle" onClick={onToggleCalFit}
                aria-label={tr('settings.calendarFit.aria')}
                title={tr('settings.calendarFit.title')}>
                {tr(calendarFitKey(calFit))}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.calendarFit.hint'), tr(calendarFitKey(DEFAULT_CALENDAR_FIT)))}
            </div>
            </>)}
            {/* A fold whose summary counts them. Opening an agenda takes the
                panel (`bare` hides the summary under the calendar's own name
                in the title bar) and keeps the fold open for the way back. */}
            <Fold className={viewingCal ? 'bare' : undefined}
              open={archivedOpen || !!viewingCal} onOpenChange={setArchivedOpen}
              summary={archivedCals.length
                ? tr('settings.archived.summary', { n: String(archivedCals.length) })
                : tr('settings.archived.summaryNone')}>
              <ArchivedCalendarsSection archived={archivedCals}
                onChange={onArchivedCalsChange} onExpire={onExpire}
                viewing={viewingCal} onViewing={setViewingCal} />
              {!viewingCal && (
                <div className="hintline">{tr('settings.archived.hint')}</div>
              )}
            </Fold>
          </>
        )}

        {section === 'tasks' && (
          <>
            <div className="menu-row">
              <label>{tr('settings.completedTasks')}</label>
              <button className="menu-toggle" onClick={onToggleShowCompleted}
                aria-pressed={showCompleted}>
                {tr(showCompleted
                  ? 'settings.completedTasks.shown' : 'settings.completedTasks.hidden')}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.completedTasks.hint'), tr('settings.completedTasks.hidden'))}
            </div>
            <div className="menu-row">
              <label htmlFor="set-autoclose">{tr('settings.autoCloseParents')}</label>
              <button className="menu-toggle" id="set-autoclose"
                onClick={onToggleAutoCloseParents} aria-pressed={autoCloseParents}>
                {tr(autoCloseParents
                  ? 'settings.autoCloseParents.on' : 'settings.autoCloseParents.off')}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.autoCloseParents.hint'), tr('settings.autoCloseParents.on'))}
            </div>
            {/* The overdue strip's two levers, set once by most people, so
                folded under a line that says what they are set to. */}
            <Fold summary={tr(staleOverdue > 0 ? 'settings.overdue.summary' : 'settings.overdue.summaryOff', {
              n: String(staleOverdue),
              plan: tr(planOnDueToday ? 'settings.overdue.planned' : 'settings.overdue.notPlanned'),
            })}>
            <div className="menu-row">
              <label htmlFor="set-stale-overdue">{tr('settings.staleOverdue')}</label>
              {/* A number the owner types, committed on blur and on Enter like
                  every other one in this sheet — not on each keystroke, which
                  would PUT a settings blob per digit and briefly store "1" on
                  the way to "14". Escape restores and stops there, so the key
                  that abandons a field does not also close the sheet. */}
              {/* No `key` on the value: remounting on every commit dropped
                  focus out of the field the moment Enter was pressed. The
                  element keeps its own text and `commitStale` writes the
                  accepted value back into it, which is what a controlled-enough
                  field needs without being re-created. */}
              <input id="set-stale-overdue" className="input menu-num" type="number"
                min={0} max={90} defaultValue={staleOverdue}
                onBlur={(e) => commitStale(e.currentTarget)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitStale(e.currentTarget)
                  if (e.key === 'Escape') {
                    e.stopPropagation()
                    e.currentTarget.value = String(staleOverdue)
                  }
                }} />
            </div>
            <div className="hintline">
              {staleOverdue > 0
                ? withDefault(tr('settings.staleOverdue.hint'), String(STALE_OVERDUE_DAYS))
                : tr('settings.staleOverdue.off')}
            </div>
            {/* Directly under the threshold, because the two describe one
                strip: that one says when a task starts being asked about, this
                says what one of the answers does. Left visible when the
                threshold is 0 rather than hidden with the group it governs —
                a control that disappears is a control the owner cannot find
                again to work out why it stopped mattering, and the hint below
                says plainly that the group has to be on for it to do
                anything. */}
            <div className="menu-row">
              <label htmlFor="set-plan-on-due-today">{tr('settings.planOnDueToday')}</label>
              <button className="menu-toggle" id="set-plan-on-due-today"
                onClick={onTogglePlanOnDueToday} aria-pressed={planOnDueToday}>
                {tr(planOnDueToday
                  ? 'settings.planOnDueToday.on' : 'settings.planOnDueToday.off')}
              </button>
            </div>
            <div className="hintline">
              {staleOverdue > 0
                ? withDefault(tr('settings.planOnDueToday.hint'),
                  tr(PLAN_ON_DUE_TODAY ? 'settings.planOnDueToday.on' : 'settings.planOnDueToday.off'))
                : tr('settings.planOnDueToday.moot')}
            </div>
            </Fold>
          </>
        )}

        {section === 'focus' && (
          <>
            <div className="hintline">{tr('settings.focus.intro')}</div>
            <FocusSection value={focus} onChange={onFocusChange} />
          </>
        )}

        {section === 'notifications' && (
          <>
            <NotificationsSection
              enabled={notifyEnabled} onEnabledChange={onNotifyEnabledChange}
              chatId={notifyChatId} onChatIdChange={onNotifyChatIdChange}
              tokenSet={notifyTokenSet} botId={notifyBotId}
              onTokenChange={onNotifyTokenChange}
              onExpire={onExpire}
              triggers={notifyTriggers}
              onTriggersChange={onNotifyTriggersChange}
              digestTime={notifyDigestTime}
              onDigestTimeChange={onNotifyDigestTimeChange}
              eveningTime={notifyEveningTime}
              onEveningTimeChange={onNotifyEveningTimeChange}
              eventLead={notifyEventLead}
              onEventLeadChange={onNotifyEventLeadChange}
              taskLead={notifyTaskLead}
              onTaskLeadChange={onNotifyTaskLeadChange}
              homeTz={homeTz} />
          </>
        )}

        {section === 'mail' && (
          <>
            <div className="hintline">{tr('mail.intro')}</div>
            <MailSection onExpire={onExpire} mailRev={mailRev} />
          </>
        )}

        {section === 'displays' && (
          <>
            <div className="hintline">{tr('disp.intro')}</div>
            <DisplaysSection onExpire={onExpire} archived={archivedCals} />
            {/* What was the Developer section: every mode at common panel
                sizes. Rendering them all is not free, and they are a
                reference, so folded. */}
            <Fold summary={tr('disp.previews.summary')} onOpenChange={setPreviewsOpen}>
              {previewsOpen && <DeveloperSection />}
            </Fold>
          </>
        )}

        {section === 'shares' && (
          <>
            <div className="hintline">{tr('shares.intro')}</div>
            <SharesSection onExpire={onExpire} archived={archivedCals} />
          </>
        )}

        {section === 'account' && (
          <>
            <div className="menu-row">
              <label>{tr('settings.signedInAs')}</label>
              <span className="menu-value">{user}</span>
            </div>
            <div className="menu-row">
              <label>{tr('settings.staySignedIn')}</label>
              <button className="menu-toggle" onClick={onCycleSessionTtl}
                aria-label={tr('settings.staySignedIn.aria')}>
                {tr(sessionKey(sessionTtl))}
              </button>
            </div>
            <div className="hintline">
              {withDefault(tr('settings.session.hint'), tr(sessionKey(SESSION_DEFAULT)))}
            </div>

            <div className="menu-head">{tr('settings.connectedApps')}</div>
            <ConnectionsSection onExpire={onExpire} />

            <div className="menu-actions">
              <button className="btn ghost" onClick={onLogout}>{tr('settings.logout')}</button>
            </div>
          </>
        )}

        {section === 'about' && (
          <>
            <div className="menu-row">
              <label>{tr('about.licence')}</label>
              <span className="menu-value">AGPL-3.0-only</span>
            </div>
            <div className="menu-row">
              <label>{tr('about.source')}</label>
              <a className="linklike" href={SOURCE_URL}
                target="_blank" rel="noreferrer noopener">
                {SOURCE_URL.replace(/^https?:\/\//, '')}
              </a>
            </div>
            <div className="hintline">{tr('about.hint')}</div>
          </>
        )}
      </div>
    </div>
  )

  const body = (
    <>
      <div className="menu-head set-head">
        {canGoBack ? (
          <button className="icon-btn set-back" onClick={back} aria-label={tr('app.back')}>‹</button>
        ) : <span className="set-back-slot" />}
        <span className="set-title">{title}</span>
        <button className="icon-btn set-close" onClick={onClose}
          aria-label={tr('app.closeSettings')}>✕</button>
      </div>
      <div className="set-body">
        {nav}
        <PendingWrite.Provider value={reportPending}>
          <UnsentInput.Provider value={reportUnsent}>{panel}</UnsentInput.Provider>
        </PendingWrite.Provider>
      </div>
    </>
  )

  // On a phone this is a bottom sheet, the idiom every other dialog here
  // already uses (`.overlay` + a sheet, see `.side.drawer`) — not Søren's
  // top-anchored geometry, which exists to clear a masthead Smylte does not
  // have. The scrim is also the only "tap outside" left once the sheet spans
  // the width.
  //
  // One tree at both widths, with only classes and attributes changing, so a
  // rotation across the breakpoint keeps every section mounted with what was
  // typed in it. Two trees remounted them and dropped the text. On a wide
  // screen the outer element is `.set-frame`, which draws no box of its own.
  return (
    <div className={isMobile ? 'overlay set-overlay' : 'set-frame'}
      // The press/release pair every other scrim carries (TaskModal's comment
      // has the mechanism): a drag-select that began in a field and let go on
      // the scrim used to close the sheet over a half-typed token or size.
      onMouseDown={isMobile ? (e) => { sheetPress.current = e.target === e.currentTarget } : undefined}
      onClick={isMobile
        ? (e) => {
          if (e.target === e.currentTarget && sheetPress.current) onClose()
          sheetPress.current = false
        }
        : undefined}>
      <div ref={panelRef} tabIndex={-1}
        className={isMobile ? 'settings-menu set-sheet' : 'menu settings-menu'}
        data-view={isMobile ? view : 'panel'}
        role="dialog" aria-modal={isMobile ? 'true' : undefined} aria-label={tr('app.settings')}
        onClick={isMobile ? (e) => e.stopPropagation() : undefined}>
        {body}
      </div>
    </div>
  )
}
