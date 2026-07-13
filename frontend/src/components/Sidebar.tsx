import { useState, type CSSProperties, type DragEvent, type KeyboardEvent } from 'react'
import type { List } from '../api'
import { useIsMobile } from '../hooks'

// Preset collection colors — muted, editorial, distinct from the accent.
const SWATCHES = [
  '#D9480F', '#C0392B', '#B8860B', '#2E7D32',
  '#00838F', '#1565C0', '#6A1B9A', '#546E7A',
]

// Selection id for the pinned "all collections" row (rendered when the view
// supports a combined mode) — never collides with a real collection id.
export const ALL_ID = '*'

export interface CollectionApi {
  create: (name: string) => Promise<List | undefined>
  update: (id: string, body: { name?: string; color?: string | null }) => Promise<List | undefined>
  remove: (id: string) => Promise<unknown>
  reorder: (ids: string[]) => Promise<unknown>
}

export function Sidebar({ title, placeholder, items, sel = '', countOf, onSelect, onItems, api,
  collapsed, onToggle, allLabel, hiddenIds, onToggleVisible }: {
  title: string
  placeholder: string
  items: List[]
  sel?: string
  countOf: (l: List) => number
  onSelect?: (id: string) => void
  onItems: (items: List[]) => void
  api: CollectionApi
  collapsed?: boolean
  onToggle?: () => void
  allLabel?: string                 // when set, a pinned "all" row selects ALL_ID
  // Visibility mode (opt-in): when onToggleVisible is provided, each row becomes
  // a show/hide toggle (checkbox-like) instead of a single-select item, and the
  // pinned "all" row is dropped. hiddenIds holds the ids currently hidden.
  hiddenIds?: Set<string>
  onToggleVisible?: (id: string) => void
}) {
  const isMobile = useIsMobile()
  const visMode = !!onToggleVisible
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<List | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)

  const create = async (name: string) => {
    const l = await api.create(name)
    setAdding(false)
    // In visibility mode a new item is simply not in hiddenIds, so it shows by
    // default — there is no selection to move.
    if (l) { onItems([...items, l]); onSelect?.(l.id) }
  }

  // Rename/recolor/delete paint immediately (the modal closes at once); the
  // request settles behind, and a failure restores the previous items.
  const save = async (id: string, body: { name?: string; color?: string | null }) => {
    setEditing(null)
    const prev = items
    onItems(items.map((l) => (l.id === id
      ? { ...l, name: body.name ?? l.name, color: body.color === undefined ? l.color : body.color }
      : l)))
    const updated = await api.update(id, body)
    if (!updated) onItems(prev)
  }

  const remove = async (id: string) => {
    setEditing(null)
    const prev = items
    const left = items.filter((l) => l.id !== id)
    onItems(left)
    if (!visMode && sel === id) onSelect?.(left[0]?.id || '')
    if ((await api.remove(id)) === undefined) onItems(prev)
  }

  const drop = (targetId: string) => {
    if (!dragId || dragId === targetId) return
    const ids = items.map((l) => l.id)
    const from = ids.indexOf(dragId)
    const to = ids.indexOf(targetId)
    if (from < 0 || to < 0) return
    const next = [...items]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    onItems(next)                       // optimistic; server confirms via SSE
    api.reorder(next.map((l) => l.id))
  }

  // Swatch fill: a visible item shows its solid color; a hidden one (visibility
  // mode) shows a hollow ring so the color still reads at a glance.
  const swatchStyle = (l: List): CSSProperties | undefined => {
    if (visMode && hiddenIds?.has(l.id)) {
      return { background: 'transparent', boxShadow: `inset 0 0 0 1.5px ${l.color || 'var(--fg-faint)'}` }
    }
    return l.color ? { background: l.color } : undefined
  }

  // Collapsed: a thin rail of color dots — lists stay one click away. The mobile
  // layout is already a compact strip, so collapse is a desktop-only affordance.
  if (collapsed && !isMobile) {
    return (
      <div className="side collapsed">
        <button className="icon-btn side-toggle" title="Expand sidebar"
          aria-label="Expand sidebar" onClick={onToggle}>»</button>
        <div className="side-rail">
          {!visMode && allLabel && items.length > 1 && (
            <button className={`rail-dot ${sel === ALL_ID ? 'active' : ''}`}
              title={allLabel} onClick={() => onSelect?.(ALL_ID)}>
              <span className="swatch swatch-all" />
            </button>
          )}
          {items.map((l) => {
            const hidden = visMode && !!hiddenIds?.has(l.id)
            return (
              <button key={l.id}
                className={`rail-dot ${!visMode && l.id === sel ? 'active' : ''} ${hidden ? 'cal-hidden' : ''}`}
                title={l.name}
                aria-pressed={visMode ? !hidden : undefined}
                onClick={() => (visMode ? onToggleVisible!(l.id) : onSelect?.(l.id))}>
                <span className="swatch" style={swatchStyle(l)} />
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="side">
      <div className="side-head">
        <span className="label">{title}</span>
        <span className="side-head-actions">
          <button className="icon-btn" title={`New ${placeholder.toLowerCase()}`}
            onClick={() => setAdding(true)}>+</button>
          {onToggle && (
            <button className="icon-btn side-toggle" title="Collapse sidebar"
              aria-label="Collapse sidebar" onClick={onToggle}>«</button>
          )}
        </span>
      </div>
      <div className="side-list">
        {!visMode && allLabel && items.length > 1 && (
          <div className={`side-item ${sel === ALL_ID ? 'active' : ''}`}
            onClick={() => onSelect?.(ALL_ID)}>
            <span className="swatch swatch-all" />
            <span className="name">{allLabel}</span>
            <span className="count">{items.reduce((n, l) => n + countOf(l), 0)}</span>
          </div>
        )}
        {items.map((l) => {
          const hidden = visMode && !!hiddenIds?.has(l.id)
          const toggle = () => (visMode ? onToggleVisible!(l.id) : onSelect?.(l.id))
          return (
          <div key={l.id}
            className={`side-item ${!visMode && l.id === sel ? 'active' : ''} ${hidden ? 'cal-hidden' : ''} ${overId === l.id && dragId !== l.id ? 'drag-over' : ''}`}
            draggable
            role={visMode ? 'checkbox' : undefined}
            aria-checked={visMode ? !hidden : undefined}
            tabIndex={visMode ? 0 : undefined}
            onKeyDown={visMode ? (e: KeyboardEvent) => {
              if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle() }
            } : undefined}
            onDragStart={(e: DragEvent) => { setDragId(l.id); e.dataTransfer.effectAllowed = 'move' }}
            onDragOver={(e: DragEvent) => { e.preventDefault(); setOverId(l.id) }}
            onDragLeave={() => setOverId((o) => (o === l.id ? null : o))}
            onDrop={(e: DragEvent) => { e.preventDefault(); drop(l.id); setDragId(null); setOverId(null) }}
            onDragEnd={() => { setDragId(null); setOverId(null) }}
            onClick={toggle}>
            <span className="swatch" style={swatchStyle(l)} />
            <span className="name">{l.name}</span>
            <span className="count">{countOf(l)}</span>
            <button className="side-edit" title="Edit"
              onClick={(e) => { e.stopPropagation(); setEditing(l) }}>⋯</button>
          </div>
          )
        })}
        {items.length === 0 && !adding && (
          <div className="empty" style={{ padding: '14px 16px' }}>Nothing here yet.</div>
        )}
      </div>
      {adding && (
        <div className="side-add">
          <input className="input" autoFocus placeholder={placeholder}
            onBlur={(e) => { if (!e.target.value.trim()) setAdding(false) }}
            onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
              const v = (e.target as HTMLInputElement).value
              if (e.key === 'Enter' && v.trim()) create(v.trim())
              if (e.key === 'Escape') setAdding(false)
            }} />
        </div>
      )}
      {editing && (
        <EditModal item={editing} placeholder={placeholder}
          onClose={() => setEditing(null)} onSave={save} onDelete={remove} />
      )}
    </div>
  )
}

function EditModal({ item, placeholder, onClose, onSave, onDelete }: {
  item: List
  placeholder: string
  onClose: () => void
  onSave: (id: string, body: { name?: string; color?: string | null }) => void
  onDelete: (id: string) => void
}) {
  const [name, setName] = useState(item.name)
  // Wire colors may carry an alpha byte (#RRGGBBAA); compare on the RGB part.
  const [color, setColor] = useState<string | null>(item.color ? item.color.slice(0, 7) : null)
  const [confirming, setConfirming] = useState(false)

  const save = () => onSave(item.id, { name: name.trim() || item.name, color })

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{placeholder}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="field">
          <label className="label">Name</label>
          <input className="input" autoFocus value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') save() }} />
        </div>
        <div className="field">
          <label className="label">Color</label>
          <div className="color-row">
            <button className={`color-dot none ${color === null ? 'on' : ''}`} title="No color"
              onClick={() => setColor(null)}>✕</button>
            {SWATCHES.map((c) => (
              <button key={c} className={`color-dot ${color === c ? 'on' : ''}`}
                style={{ background: c }} title={c} onClick={() => setColor(c)} />
            ))}
          </div>
        </div>
        <div className="modal-actions">
          <button className={`btn ghost ${confirming ? 'danger' : ''}`}
            onClick={() => (confirming ? onDelete(item.id) : setConfirming(true))}>
            {confirming ? 'Really delete?' : 'Delete'}
          </button>
          <span className="spacer" />
          <button className="btn" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  )
}
