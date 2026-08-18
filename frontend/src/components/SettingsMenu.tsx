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
import { calendarFitLabel, type CalendarFit } from '../calendar'
import { useIsMobile } from '../hooks'
import { sessionLabel } from '../session'
import { timeFormatLabel, type TimeFormat } from '../time'
import type { List } from '../api'
import type { Tab, TabStart } from '../tabs'
import { ArchivedCalendarsSection } from './ArchivedCalendarsSection'
import { ConnectionsSection } from './ConnectionsSection'
import { TabsSection } from './TabsSection'

// The nav, in order. `label` is the accessible name of both the nav item and,
// on a phone, the title bar — Søren's test asserts they agree.
const SECTIONS = [
  { id: 'general', label: 'General' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'calendar', label: 'Calendar' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'account', label: 'Account' },
] as const

type Section = (typeof SECTIONS)[number]['id']

export function SettingsMenu({
  theme, onToggleTheme, onCustomizeAppearance,
  tabOrder, startTab, onTabOrderChange, onStartTabChange,
  timeFormat, onToggleTimeFormat,
  homeTz, onToggleHomeTz,
  calFit, onToggleCalFit,
  archivedCals, onArchivedCalsChange,
  showCompleted, onToggleShowCompleted,
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
  onToggleTimeFormat: () => void
  homeTz: string
  onToggleHomeTz: () => void
  calFit: CalendarFit
  onToggleCalFit: () => void
  archivedCals: string[]
  onArchivedCalsChange: (next: string[]) => void
  showCompleted: boolean
  onToggleShowCompleted: () => void
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') back() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [back])

  const active = SECTIONS.find((s) => s.id === section)!
  // What the title bar says. Beside a visible nav it would only be saying the
  // section's name twice, so on a desktop it stays "Settings".
  const title = viewingCal ? viewingCal.name
    : isMobile && view === 'panel' ? active.label
    : 'Settings'
  // The back arrow appears wherever there is a step to take back.
  const canGoBack = !!viewingCal || (isMobile && view === 'panel')

  const nav = (
    <div className="set-nav" role="tablist" aria-label="Settings sections">
      {SECTIONS.map((s) => (
        // `role="tab"`, not a plain button: the topbar already has a *Tasks*
        // tab and so does this nav, and the roles are what keep the two apart.
        <button key={s.id} type="button" role="tab" id={`set-tab-${s.id}`}
          className={`set-nav-item ${section === s.id ? 'active' : ''}`}
          aria-selected={section === s.id} aria-controls={`set-panel-${s.id}`}
          onClick={() => show(s.id)}>
          {s.label}
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
            <div className="menu-head">Tabs</div>
            <TabsSection order={tabOrder} start={startTab}
              onOrderChange={onTabOrderChange} onStartChange={onStartTabChange} />

            <div className="menu-head">Clock</div>
            <div className="menu-row">
              <label>Clock</label>
              <button className="menu-toggle" onClick={onToggleTimeFormat}
                aria-label="12- or 24-hour clock">
                {timeFormatLabel(timeFormat)}
              </button>
            </div>
            <div className="hintline">
              The clock covers every time the app draws itself. Date and time
              pickers are drawn by the browser — Chrome, Edge and the Windows
              app follow this setting, Firefox follows your system's.
            </div>

            <div className="menu-head">Time zone</div>
            <div className="menu-row">
              <label>Home timezone</label>
              <button className="menu-toggle" onClick={onToggleHomeTz}
                aria-label="Timezone your events are written in"
                title="Which clock your events are written on. Scheduling links use it to know when you are really busy.">
                {homeTz || 'Not set'}
              </button>
            </div>
          </>
        )}

        {section === 'appearance' && (
          <>
            <div className="menu-row">
              <label>Theme</label>
              <button className="menu-toggle" onClick={onToggleTheme}>
                {theme === 'dark' ? 'Dark' : 'Light'}
              </button>
            </div>
            <div className="menu-row">
              <label>Appearance</label>
              <button className="menu-toggle" aria-label="Customize appearance"
                onClick={onCustomizeAppearance}>
                Customize…
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
              <label>Calendar window</label>
              <button className="menu-toggle" onClick={onToggleCalFit}
                aria-label="Fixed or dynamic calendar grid"
                title="Fixed keeps every week the same height; a day with more than fits collapses into “+N more” instead of stretching its week.">
                {calendarFitLabel(calFit)}
              </button>
            </div>
            <div className="hintline">
              A fixed calendar window fits the whole month in the pane: every week
              is the same height, and a day with more than fits collapses into
              “+N more”. Dynamic lets a busy week grow and the grid scroll.
            </div>

            <div className="menu-head">Archived calendars</div>
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
              <label>Completed tasks</label>
              <button className="menu-toggle" onClick={onToggleShowCompleted}
                aria-pressed={showCompleted}>
                {showCompleted ? 'Shown' : 'Hidden'}
              </button>
            </div>
            <div className="hintline">
              Whether completed tasks stay in the main view. The sidebar's
              “View completed” works either way.
            </div>
          </>
        )}

        {section === 'account' && (
          <>
            <div className="menu-row">
              <label>Signed in as</label>
              <span className="menu-value">{user}</span>
            </div>
            <div className="menu-row">
              <label>Stay signed in</label>
              <button className="menu-toggle" onClick={onCycleSessionTtl}
                aria-label="How long to stay signed in">
                {sessionLabel(sessionTtl)}
              </button>
            </div>
            <div className="hintline">
              A shorter sign-in applies at once, on this device and any other. A
              longer one starts from your next sign-in.
            </div>

            <div className="menu-head">Connected apps</div>
            <ConnectionsSection onExpire={onExpire} />

            <div className="menu-actions">
              <button className="btn ghost" onClick={onLogout}>Log out</button>
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
          <button className="icon-btn set-back" onClick={back} aria-label="Back">‹</button>
        ) : <span className="set-back-slot" />}
        <span className="set-title">{title}</span>
        <button className="icon-btn set-close" onClick={onClose} aria-label="Close settings">✕</button>
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
          role="dialog" aria-modal="true" aria-label="Settings"
          onClick={(e) => e.stopPropagation()}>
          {body}
        </div>
      </div>
    )
  }

  return (
    <div ref={panelRef} className="menu settings-menu" data-view="panel"
      role="dialog" aria-label="Settings">
      {body}
    </div>
  )
}
