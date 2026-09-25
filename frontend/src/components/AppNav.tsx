// The sidebar layout's navigation (see layout.ts): a paper column down the left
// on a desktop, a bar along the bottom on a phone. Classic's top bar is still
// drawn inline in App.tsx, untouched, which is what keeps that frame the one it
// always was.
//
// Both carry the same buttons as Classic's strip, with the same classes and the
// same semantics: `.tabs .tab`, `aria-current="page"` on the view that is open
// (not `role="tab"` — this is page-level navigation, and Settings' own nav is
// the tablist), and the settings button that opens the menu. The menu itself
// is not drawn in here: App renders it beside the nav (see the frame there).
import type { Ref, RefObject } from 'react'
import { useT } from '../i18n'
import { TAB_LABELS, type Tab } from '../tabs'

interface NavProps {
  tabOrder: Tab[]
  tab: Tab
  onTab: (t: Tab) => void
  /** `/api/me` is in flight: the views are real (seeded from the boot cache)
   *  and a click on one sticks, but there is no account to open settings for
   *  yet — the same rule Classic's gear follows. */
  booting: boolean
  gearRef: RefObject<HTMLButtonElement>
  settingsOpen: boolean
  onToggleSettings: () => void
}

/** The gear. A functional glyph, the one Classic's top bar draws. */
export function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
      strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

function ViewButtons({ tabOrder, tab, onTab }: Pick<NavProps, 'tabOrder' | 'tab' | 'onTab'>) {
  const tr = useT()
  return (
    <>
      {tabOrder.map((t) => (
        <button key={t} type="button" className={`tab ${tab === t ? 'active' : ''}`}
          aria-current={tab === t ? 'page' : undefined}
          onClick={() => onTab(t)}>
          {tr(TAB_LABELS[t])}
        </button>
      ))}
    </>
  )
}

/**
 * The app sidebar. Top to bottom: the wordmark and the fold, the views, the
 * slot the open view lends its collections to (Lists on Tasks, Calendars on
 * Calendar — see shell.tsx), and Settings at the foot.
 *
 * Folded, it is a rail: the unfold, the collections' own rail of dots, and the
 * gear. The views are not on the rail. There is no icon to stand for Home or
 * Scheduling in a system that draws only functional glyphs, and a letter each
 * would be two T's for Today and Tasks — so the rail is for the view you are
 * working in, and one press brings the rest back.
 */
export function AppNav({ collapsed, onToggleCollapsed, slotRef, ...p }: NavProps & {
  collapsed: boolean
  onToggleCollapsed: () => void
  /** A callback ref: the shell has to re-render its views once the slot exists. */
  slotRef: Ref<HTMLDivElement>
}) {
  const tr = useT()
  const fold = collapsed ? tr('side.expand') : tr('side.collapse')
  return (
    <nav className={`appnav ${collapsed ? 'collapsed' : ''}`} aria-label={tr('app.nav')}>
      <div className="appnav-head">
        {!collapsed && <span className="brand">Smylte<span className="dot">.</span></span>}
        <button type="button" className="icon-btn appnav-fold" title={fold} aria-label={fold}
          aria-expanded={!collapsed} onClick={onToggleCollapsed}>
          {collapsed ? '»' : '«'}
        </button>
      </div>
      {!collapsed && (
        <div className="tabs appnav-tabs">
          <ViewButtons tabOrder={p.tabOrder} tab={p.tab} onTab={p.onTab} />
        </div>
      )}
      <div className="appnav-slot" ref={slotRef} />
      {!p.booting && (
        <div className="appnav-foot">
          <button ref={p.gearRef} type="button"
            className={`appnav-settings ${p.settingsOpen ? 'active' : ''}`}
            title={tr('app.settings')} aria-label={tr('app.settings')}
            aria-expanded={p.settingsOpen} onClick={p.onToggleSettings}>
            <GearIcon />
            {!collapsed && <span className="appnav-settings-word">{tr('app.settings')}</span>}
          </button>
        </div>
      )}
    </nav>
  )
}

/**
 * The phone's navigation, along the bottom where a thumb reaches it. Every view
 * fits, so nothing scrolls sideways and nothing starts off-screen — the strip's
 * problem on a phone under Classic — and the gear sits at the end. Settings on a
 * phone is a bottom sheet anchored to the viewport, so where the gear is does
 * not move it.
 */
export function TabBar(p: NavProps) {
  const tr = useT()
  return (
    <nav className="tabbar" aria-label={tr('app.nav')}>
      <ViewButtons tabOrder={p.tabOrder} tab={p.tab} onTab={p.onTab} />
      {!p.booting && (
        <button ref={p.gearRef} type="button"
          className={`icon-btn ${p.settingsOpen ? 'active' : ''}`}
          title={tr('app.settings')} aria-label={tr('app.settings')}
          aria-expanded={p.settingsOpen} onClick={p.onToggleSettings}>
          <GearIcon />
        </button>
      )}
    </nav>
  )
}
