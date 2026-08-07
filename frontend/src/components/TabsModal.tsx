// Tab strip editor: the order the tabs sit in, and which one the app opens on.
// Reordering is ↑/↓ rather than drag — there are four rows, and buttons are
// keyboard- and touch-usable without any of the pointer plumbing the Home
// dashboard needs for a free canvas.

import { useEffect, useRef } from 'react'
import { TAB_LABELS, moveTab, type Tab, type TabStart } from '../tabs'

export function TabsModal({ order, start, onOrderChange, onStartChange, onClose }: {
  order: Tab[]
  start: TabStart
  onOrderChange: (next: Tab[]) => void
  onStartChange: (next: TabStart) => void
  onClose: () => void
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const move = (t: Tab, dir: -1 | 1) => {
    refocus.current = `${t}:${dir}`
    onOrderChange(moveTab(order, t, dir))
  }

  const arrow = (t: Tab, dir: -1 | 1, disabled: boolean) => (
    <button className="icon-btn" disabled={disabled}
      ref={(el) => { if (el) arrows.current.set(`${t}:${dir}`, el) }}
      aria-label={`Move ${TAB_LABELS[t]} ${dir === -1 ? 'left' : 'right'}`}
      onClick={() => move(t, dir)}>
      {dir === -1 ? '↑' : '↓'}
    </button>
  )

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-label="Tabs">
        <div className="modal-head">
          <span className="modal-title">Tabs</span>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>

        <div className="tab-order">
          {order.map((t, i) => (
            <div key={t} className="tab-order-row">
              <span className="mono num">{i + 1}</span>
              <span className="name">{TAB_LABELS[t]}</span>
              {arrow(t, -1, i === 0)}
              {arrow(t, 1, i === order.length - 1)}
            </div>
          ))}
        </div>

        <div className="menu-row">
          <label htmlFor="start-tab">Opens on</label>
          <select id="start-tab" className="input" value={start}
            onChange={(e) => onStartChange(e.target.value as TabStart)}>
            {order.map((t) => <option key={t} value={t}>{TAB_LABELS[t]}</option>)}
            <option value="last">Last used tab</option>
          </select>
        </div>

        <p className="hintline">
          The order here is the order across the top. “Last used tab” reopens
          wherever you left off, on every device signed into this account.
        </p>
      </div>
    </div>
  )
}
