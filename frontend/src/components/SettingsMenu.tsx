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
import { calendarFitKey, type CalendarFit } from '../calendar'
import { useIsMobile, useEscape } from '../hooks'
import { sessionKey } from '../session'
import { timeFormatKey, type TimeFormat } from '../time'
import { LANGUAGES, languageLabel, type Language } from '../lang'
import { useT } from '../i18n'
import type { List } from '../api'
import type { Tab, TabStart } from '../tabs'
import { ArchivedCalendarsSection } from './ArchivedCalendarsSection'
import { ConnectionsSection } from './ConnectionsSection'
import { TabsSection } from './TabsSection'
import { CapacitySection } from './CapacitySection'
import { NotificationsSection } from './NotificationsSection'
import type { Trigger } from '../notifications'

// The nav, in order. `label` is the accessible name of both the nav item and,
// on a phone, the title bar — Søren's test asserts they agree.
// `label` is now a catalogue KEY rather than the text. The comment above still
// holds and is the reason it has to be: the nav item and the phone title bar
// both render it, a test asserts they agree, and two `tr()` calls on one key
// agree by construction where two translations of one English word need not.
const SECTIONS = [
  { id: 'general', label: 'settings.section.general' },
  { id: 'appearance', label: 'settings.section.appearance' },
  { id: 'calendar', label: 'settings.section.calendar' },
  { id: 'tasks', label: 'settings.section.tasks' },
  { id: 'notifications', label: 'settings.section.notifications' },
  { id: 'account', label: 'settings.section.account' },
] as const

type Section = (typeof SECTIONS)[number]['id']

export function SettingsMenu({
  theme, onToggleTheme, onCustomizeAppearance,
  tabOrder, startTab, onTabOrderChange, onStartTabChange,
  timeFormat, onToggleTimeFormat,
  language, onLanguageChange,
  dayCapacity, onDayCapacityChange, dayCapacityByWeekday, onDayCapacityByWeekdayChange,
  homeTz, onToggleHomeTz,
  calFit, onToggleCalFit,
  archivedCals, onArchivedCalsChange,
  showCompleted, onToggleShowCompleted,
  notifyEnabled, onNotifyEnabledChange,
  notifyChatId, onNotifyChatIdChange,
  notifyTokenSet, notifyBotId, onNotifyTokenChange,
  notifyTriggers, onNotifyTriggersChange,
  notifyDigestTime, onNotifyDigestTimeChange,
  notifyEveningTime, onNotifyEveningTimeChange,
  notifyEventLead, onNotifyEventLeadChange,
  notifyTaskLead, onNotifyTaskLeadChange,
  user, sessionTtl, onCycleSessionTtl,
  onLogout, onExpire, onClose, panelRef,
}: {
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
  const [section, setSection] = useState<Section>('general')
  // Only meaningful on a phone. On a desktop the nav is a permanent column, so
  // there is nothing to be "in" and nothing to go back to.
  const [view, setView] = useState<'index' | 'panel'>('index')
  // The archived-calendar agenda is a step below the Calendar section. It lives
  // here so one back control can unwind the whole stack in order.
  const [viewingCal, setViewingCal] = useState<List | null>(null)

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

  const tr = useT()
  const active = SECTIONS.find((s) => s.id === section)!
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
          onClick={() => show(s.id)}>
          {tr(s.label)}
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
            <div className="menu-head">{tr('settings.tabs')}</div>
            <TabsSection order={tabOrder} start={startTab}
              onOrderChange={onTabOrderChange} onStartChange={onStartTabChange} />

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
            <div className="hintline">{tr('settings.language.hint')}</div>

            <div className="menu-head">{tr('settings.clock')}</div>
            <div className="menu-row">
              <label>{tr('settings.clock')}</label>
              <button className="menu-toggle" onClick={onToggleTimeFormat}
                aria-label={tr('settings.clock.aria')}>
                {tr(timeFormatKey(timeFormat))}
              </button>
            </div>
            <div className="hintline">{tr('settings.clock.hint')}</div>

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
          </>
        )}

        {section === 'appearance' && (
          <>
            <div className="menu-row">
              <label>{tr('settings.theme')}</label>
              <button className="menu-toggle" onClick={onToggleTheme}>
                {tr(theme === 'dark' ? 'theme.dark' : 'theme.light')}
              </button>
            </div>
            <div className="menu-row">
              <label>{tr('settings.appearance')}</label>
              <button className="menu-toggle" aria-label={tr('settings.appearance.aria')}
                onClick={onCustomizeAppearance}>
                {tr('settings.appearance.customize')}
              </button>
            </div>
            <div className="hintline">
              Customize opens the full editor over the design system — every
              color token, the corner radius, the text scale and the type
              families — and saves what you make as a named theme.
            </div>
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
              A fixed calendar window fits the whole month in the pane: every week
              is the same height, and a day with more than fits collapses into
              “+N more”. Dynamic lets a busy week grow and the grid scroll.
            </div>

            <div className="menu-head">{tr('settings.archivedCalendars')}</div>
            </>)}
            <ArchivedCalendarsSection archived={archivedCals}
              onChange={onArchivedCalsChange} onExpire={onExpire}
              viewing={viewingCal} onViewing={setViewingCal} />
            {!viewingCal && (
              <div className="hintline">
                Archiving hides a calendar without deleting it. Lists and
                calendars live on the Radicale CalDAV server — changes there show
                up in every connected client, but an archive is Smylte's own and
                the collection stays on the wire.
              </div>
            )}
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
              Whether completed tasks stay in the main view. The sidebar's
              “View completed” works either way.
            </div>
          </>
        )}

        {section === 'notifications' && (
          <>
            <div className="hintline">{tr('notif.intro')}</div>
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
              A shorter sign-in applies at once, on this device and any other. A
              longer one starts from your next sign-in.
            </div>

            <div className="menu-head">{tr('settings.connectedApps')}</div>
            <ConnectionsSection onExpire={onExpire} />

            <div className="menu-actions">
              <button className="btn ghost" onClick={onLogout}>{tr('settings.logout')}</button>
            </div>
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
        {panel}
      </div>
    </>
  )

  // On a phone this is a bottom sheet, the idiom every other dialog here
  // already uses (`.overlay` + a sheet, see `.side.drawer`) — not Søren's
  // top-anchored geometry, which exists to clear a masthead Smylte does not
  // have. The scrim is also the only "tap outside" left once the sheet spans
  // the width.
  if (isMobile) {
    return (
      <div className="overlay set-overlay" onClick={onClose}>
        <div ref={panelRef} className="settings-menu set-sheet" data-view={view}
          role="dialog" aria-modal="true" aria-label={tr('app.settings')}
          onClick={(e) => e.stopPropagation()}>
          {body}
        </div>
      </div>
    )
  }

  return (
    <div ref={panelRef} className="menu settings-menu" data-view="panel"
      role="dialog" aria-label={tr('app.settings')}>
      {body}
    </div>
  )
}
