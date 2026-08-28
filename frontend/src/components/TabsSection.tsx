// Tab strip editor: the order the tabs sit in, and which one the app opens on.
// Reordering is ↑/↓ rather than drag — there are four rows, and buttons are
// keyboard- and touch-usable without any of the pointer plumbing the Home
// dashboard needs for a free canvas.
//
// A section body inside the settings panel, not a dialog of its own: the panel
// column owns the scrolling, the heading and the way out, so this renders only
// its own rows.

import { useEffect, useRef } from 'react'
import { TAB_LABELS, moveTab, type Tab, type TabStart } from '../tabs'
import { useT } from '../i18n'

export function TabsSection({ order, start, onOrderChange, onStartChange }: {
  order: Tab[]
  start: TabStart
  onOrderChange: (next: Tab[]) => void
  onStartChange: (next: TabStart) => void
}) {
  // Which arrow to put focus back on after a move: the rows swap places, so
  // without this a keyboard reorder drops focus to the body after one press.
  const refocus = useRef<string | null>(null)
  const arrows = useRef(new Map<string, HTMLButtonElement>())

  useEffect(() => {
    if (!refocus.current) return
    arrows.current.get(refocus.current)?.focus()
    refocus.current = null
  }, [order])

  const tr = useT()

  const move = (t: Tab, dir: -1 | 1) => {
    refocus.current = `${t}:${dir}`
    onOrderChange(moveTab(order, t, dir))
  }

  const arrow = (t: Tab, dir: -1 | 1, disabled: boolean) => (
    <button className="icon-btn" disabled={disabled}
      ref={(el) => { if (el) arrows.current.set(`${t}:${dir}`, el) }}
      aria-label={tr(dir === -1 ? 'tabs.moveLeft' : 'tabs.moveRight',
        { tab: tr(TAB_LABELS[t]) })}
      onClick={() => move(t, dir)}>
      {dir === -1 ? '↑' : '↓'}
    </button>
  )

  return (
    <>
      <div className="tab-order">
        {order.map((t, i) => (
          <div key={t} className="tab-order-row">
            <span className="mono num">{i + 1}</span>
            <span className="name">{tr(TAB_LABELS[t])}</span>
            {arrow(t, -1, i === 0)}
            {arrow(t, 1, i === order.length - 1)}
          </div>
        ))}
      </div>

      <div className="menu-row">
        <label htmlFor="start-tab">{tr('tabs.opensOn')}</label>
        <select id="start-tab" className="input" value={start}
          onChange={(e) => onStartChange(e.target.value as TabStart)}>
          {order.map((x) => <option key={x} value={x}>{tr(TAB_LABELS[x])}</option>)}
          <option value="last">{tr('tabs.lastUsed')}</option>
        </select>
      </div>

      <p className="hintline">{tr('tabs.hint')}</p>
    </>
  )
}
