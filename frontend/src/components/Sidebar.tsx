import { useState, type DragEvent, type KeyboardEvent } from 'react'
import type { List } from '../api'

// Preset collection colors — muted, editorial, distinct from the accent.
const SWATCHES = [
  '#D9480F', '#C0392B', '#B8860B', '#2E7D32',
  '#00838F', '#1565C0', '#6A1B9A', '#546E7A',
]

export interface CollectionApi {
  create: (name: string) => Promise<List | undefined>
  update: (id: string, body: { name?: string; color?: string | null }) => Promise<List | undefined>
  remove: (id: string) => Promise<unknown>
  reorder: (ids: string[]) => Promise<unknown>
}

export function Sidebar({ title, placeholder, items, sel, countOf, onSelect, onItems, api }: {
  title: string
  placeholder: string
  items: List[]
  sel: string
  countOf: (l: List) => number
  onSelect: (id: string) => void
  onItems: (items: List[]) => void
  api: CollectionApi
}) {
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<List | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)

  const create = async (name: string) => {
    const l = await api.create(name)
    setAdding(false)
    if (l) { onItems([...items, l]); onSelect(l.id) }
  }

  const save = async (id: string, body: { name?: string; color?: string | null }) => {
    const updated = await api.update(id, body)
    if (updated) onItems(items.map((l) => (l.id === id ? updated : l)))
    setEditing(null)
  }

  const remove = async (id: string) => {
    await api.remove(id)
    const left = items.filter((l) => l.id !== id)
    onItems(left)
    if (sel === id) onSelect(left[0]?.id || '')
    setEditing(null)
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

  return (
    <div className="side">
      <div className="side-head">
        <span className="label">{title}</span>
        <button className="icon-btn" title={`New ${placeholder.toLowerCase()}`}
          onClick={() => setAdding(true)}>+</button>
      </div>
      <div className="side-list">
        {items.map((l) => (
          <div key={l.id}
            className={`side-item ${l.id === sel ? 'active' : ''} ${overId === l.id && dragId !== l.id ? 'drag-over' : ''}`}
            draggable
            onDragStart={(e: DragEvent) => { setDragId(l.id); e.dataTransfer.effectAllowed = 'move' }}
            onDragOver={(e: DragEvent) => { e.preventDefault(); setOverId(l.id) }}
            onDragLeave={() => setOverId((o) => (o === l.id ? null : o))}
            onDrop={(e: DragEvent) => { e.preventDefault(); drop(l.id); setDragId(null); setOverId(null) }}
            onDragEnd={() => { setDragId(null); setOverId(null) }}
            onClick={() => onSelect(l.id)}>
            <span className="swatch" style={l.color ? { background: l.color } : undefined} />
            <span className="name">{l.name}</span>
            <span className="count">{countOf(l)}</span>
            <button className="side-edit" title="Edit"
              onClick={(e) => { e.stopPropagation(); setEditing(l) }}>⋯</button>
          </div>
        ))}
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
