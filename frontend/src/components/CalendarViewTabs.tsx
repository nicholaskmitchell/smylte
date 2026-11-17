import { useEffect, useRef, type CSSProperties } from 'react'
import { useSegmentThumb } from '../hooks'
import { useI18n } from '../i18n'
import type { CalView } from '../tabs'

const VIEWS: [CalView, string][] = [
  ['month', 'tab.calendar'],
  ['scheduling', 'tab.scheduling'],
]

// The two-way switch at the top of Calendar. Same segmented control as the
// Tasks List / 3-Day / Week switch, so the two read as one kind of thing.
// Each of Calendar's views mounts its own copy, so a pick replaces the switch
// with a new one; `takeFocus` says whether the new one should put focus back on
// its active segment (true only right after a pick from the switch).
export function CalendarViewTabs({ view, onView, takeFocus }: {
  view: CalView; onView: (v: CalView) => void; takeFocus?: () => boolean
}) {
  const { t: tr } = useI18n()
  const ref = useRef<HTMLDivElement>(null)
  const activeRef = useRef<HTMLButtonElement>(null)
  const active = Math.max(0, VIEWS.findIndex(([v]) => v === view))
  useSegmentThumb(ref, active)
  useEffect(() => {
    if (takeFocus?.()) activeRef.current?.focus()
  }, [takeFocus])
  // The row it sits in (`.content-switch`) is the view's own, so a view can
  // put its actions beside it (Scheduling's New link).
  return (
    <div className="view-tabs" role="tablist" aria-label={tr('tab.calendar')}
      ref={ref}
      style={{ '--n': VIEWS.length, '--i': active } as CSSProperties}>
      {VIEWS.map(([v, label]) => (
        <button key={v} type="button" role="tab" aria-selected={view === v}
          ref={view === v ? activeRef : undefined}
          className={'view-tab ' + (view === v ? 'active' : '')}
          onClick={() => onView(v)}>{tr(label)}</button>
      ))}
    </div>
  )
}
