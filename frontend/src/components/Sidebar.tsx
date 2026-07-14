import { useState, type CSSProperties, type DragEvent, type KeyboardEvent } from 'react'
import { clientId, type List, type TaskGroup } from '../api'
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
  collapsed, onToggle, allLabel, hiddenIds, onHiddenChange, onArchive, archivedIds,
  groups, onGroupsChange, collapsedGroups, onCollapsedGroupsChange }: {
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
  // Visibility mode (opt-in): when onHiddenChange is provided, each collection
  // carries a show/hide toggle. `hiddenIds` holds the ids currently hidden.
  //   • without onSelect (Calendar): the whole row is the toggle.
  //   • with onSelect (Tasks): the row still single-selects to focus one list,
  //     and the swatch doubles as the visibility checkbox — no extra width.
  hiddenIds?: Set<string>
  onHiddenChange?: (next: string[]) => void
  // Archive (opt-in): when provided, the edit modal offers a non-destructive
  // "Archive" alongside Delete. Only the Calendar view wires this.
  onArchive?: (id: string) => void
  // Archived rows are removed from the rail/list entirely (unlike hidden ones,
  // which stay dimmed). `items` still holds the full set so reorder/drag operate
  // on the real order — this only filters what renders.
  archivedIds?: Set<string>
  // Groups (opt-in, Tasks only): named collapsible headers that lists sit under.
  // Membership is a set; render order still follows the global `items` order, so
  // drag-reorder and the wire order are untouched.
  groups?: TaskGroup[]
  onGroupsChange?: (next: TaskGroup[]) => void
  collapsedGroups?: string[]
  onCollapsedGroupsChange?: (next: string[]) => void
}) {
  const isMobile = useIsMobile()
  const canSelect = !!onSelect
  const canToggle = !!onHiddenChange
  const groupsOn = !!groups && !!onGroupsChange
  const hidden = hiddenIds ?? new Set<string>()
  const collapsedSet = new Set(collapsedGroups ?? [])
  // What actually renders: the full `items` minus any archived ids. Mutation
  // handlers (create/save/remove/drop) keep using `items` so the full set and
  // wire order stay intact.
  const shown = archivedIds ? items.filter((l) => !archivedIds.has(l.id)) : items
  const [adding, setAdding] = useState(false)
  const [addingGroup, setAddingGroup] = useState(false)
  const [editing, setEditing] = useState<List | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  const [overGroup, setOverGroup] = useState<string | null>(null)

  const create = async (name: string) => {
    const l = await api.create(name)
    setAdding(false)
    // A new item is simply not hidden, so it shows by default. In select mode we
    // also focus it; in pure-visibility mode there is no selection to move.
    if (l) { onItems([...items, l]); if (canSelect) onSelect?.(l.id) }
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
    if (canSelect && sel === id) onSelect?.(left[0]?.id || '')
    // Drop the deleted list out of any group so the stored blob stays tidy.
    if (groupsOn && groups!.some((g) => g.lists.includes(id))) {
      onGroupsChange!(groups!.map((g) => ({ ...g, lists: g.lists.filter((x) => x !== id) })))
    }
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

  // ── visibility helpers ────────────────────────────────────────────────────
  const toggleVisible = (id: string) => {
    if (!onHiddenChange) return
    onHiddenChange(hidden.has(id) ? [...hidden].filter((x) => x !== id) : [...hidden, id])
  }
  // Hide or show a batch at once (a group toggle) in a single write.
  const setHiddenBulk = (ids: string[], hide: boolean) => {
    if (!onHiddenChange) return
    const set = new Set(hidden)
    ids.forEach((id) => (hide ? set.add(id) : set.delete(id)))
    onHiddenChange([...set])
  }

  // ── group helpers ─────────────────────────────────────────────────────────
  // Each list belongs to the first group that lists it (dedupe defensively).
  const groupOf = new Map<string, string>()
  if (groupsOn) {
    for (const g of groups!) for (const id of g.lists) if (!groupOf.has(id)) groupOf.set(id, g.id)
  }
  const membersOf = (g: TaskGroup) => shown.filter((l) => groupOf.get(l.id) === g.id)
  const ungrouped = shown.filter((l) => !groupOf.has(l.id))

  const createGroup = (name: string) => {
    setAddingGroup(false)
    if (onGroupsChange) onGroupsChange([...(groups ?? []), { id: clientId(), name, lists: [] }])
  }
  const renameGroup = (id: string, name: string) =>
    onGroupsChange?.((groups ?? []).map((g) => (g.id === id ? { ...g, name } : g)))
  const removeGroup = (id: string) =>       // members fall back to ungrouped
    onGroupsChange?.((groups ?? []).filter((g) => g.id !== id))
  const moveListToGroup = (listId: string, groupId: string | null) => {
    if (!onGroupsChange) return
    const cleaned = (groups ?? []).map((g) => ({ ...g, lists: g.lists.filter((x) => x !== listId) }))
    onGroupsChange(groupId
      ? cleaned.map((g) => (g.id === groupId ? { ...g, lists: [...g.lists, listId] } : g))
      : cleaned)
  }
  const toggleCollapse = (id: string) => {
    if (!onCollapsedGroupsChange) return
    const cur = collapsedGroups ?? []
    onCollapsedGroupsChange(cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id])
  }

  // Swatch fill: a visible item shows its solid color; a hidden one (visibility
  // mode) shows a hollow ring so the color still reads at a glance.
  const swatchStyle = (l: List): CSSProperties | undefined => {
    if (canToggle && hidden.has(l.id)) {
      return { background: 'transparent', boxShadow: `inset 0 0 0 1.5px ${l.color || 'var(--fg-faint)'}` }
    }
    return l.color ? { background: l.color } : undefined
  }

  // One list row — reused by both the grouped and ungrouped sections. When the
  // view both selects and toggles, the swatch becomes the visibility checkbox
  // and the rest of the row selects; otherwise the whole row is one action.
  const renderRow = (l: List) => {
    const isHidden = canToggle && hidden.has(l.id)
    const primary = () => (canSelect ? onSelect?.(l.id) : canToggle ? toggleVisible(l.id) : undefined)
    const rowToggles = canToggle && !canSelect        // Calendar: row is the toggle
    const swatchToggles = canToggle && canSelect       // Tasks: swatch is the toggle
    return (
      <div key={l.id}
        className={`side-item ${canSelect && l.id === sel ? 'active' : ''} ${isHidden ? 'cal-hidden' : ''} ${overId === l.id && dragId !== l.id ? 'drag-over' : ''}`}
        draggable
        role={rowToggles ? 'checkbox' : undefined}
        aria-checked={rowToggles ? !isHidden : undefined}
        tabIndex={rowToggles ? 0 : undefined}
        onKeyDown={rowToggles ? (e: KeyboardEvent) => {
          if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); primary() }
        } : undefined}
        onDragStart={(e: DragEvent) => { setDragId(l.id); e.dataTransfer.effectAllowed = 'move' }}
        // stopPropagation so a drop ON a row reorders only — it must not also
        // reach the enclosing group/ungrouped drop target (membership change).
        onDragOver={(e: DragEvent) => { e.preventDefault(); e.stopPropagation(); setOverId(l.id); setOverGroup(null) }}
        onDragLeave={() => setOverId((o) => (o === l.id ? null : o))}
        onDrop={(e: DragEvent) => { e.preventDefault(); e.stopPropagation(); drop(l.id); setDragId(null); setOverId(null); setOverGroup(null) }}
        onDragEnd={() => { setDragId(null); setOverId(null); setOverGroup(null) }}
        onClick={primary}>
        {swatchToggles ? (
          <button className="swatch-btn" title={isHidden ? 'Show in All lists' : 'Hide from All lists'}
            aria-label={isHidden ? 'Show in All lists' : 'Hide from All lists'}
            aria-pressed={!isHidden}
            onClick={(e) => { e.stopPropagation(); toggleVisible(l.id) }}>
            <span className="swatch" style={swatchStyle(l)} />
          </button>
        ) : (
          <span className="swatch" style={swatchStyle(l)} />
        )}
        <span className="name">{l.name}</span>
        <span className="count">{countOf(l)}</span>
        <button className="side-edit" title="Edit"
          onClick={(e) => { e.stopPropagation(); setEditing(l) }}>⋯</button>
      </div>
    )
  }

  // Collapsed: a thin rail of color dots — collections stay one click away. The
  // mobile layout is already a compact strip, so collapse is a desktop-only
  // affordance. Groups don't render here (the rail is too thin); every list dot
  // still shows so nothing becomes unreachable.
  if (collapsed && !isMobile) {
    return (
      <div className="side collapsed">
        <button className="icon-btn side-toggle" title="Expand sidebar"
          aria-label="Expand sidebar" onClick={onToggle}>»</button>
        <div className="side-rail">
          {allLabel && items.length > 1 && (
            <button className={`rail-dot ${sel === ALL_ID ? 'active' : ''}`}
              title={allLabel} onClick={() => onSelect?.(ALL_ID)}>
              <span className="swatch swatch-all" />
            </button>
          )}
          {shown.map((l) => {
            const isHidden = canToggle && hidden.has(l.id)
            const primary = () => (canSelect ? onSelect?.(l.id) : toggleVisible(l.id))
            return (
              <button key={l.id}
                className={`rail-dot ${canSelect && l.id === sel ? 'active' : ''} ${isHidden ? 'cal-hidden' : ''}`}
                title={l.name}
                aria-pressed={canToggle && !canSelect ? !isHidden : undefined}
                onClick={primary}>
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
          {groupsOn && !isMobile && (
            <button className="icon-btn" title="New group"
              aria-label="New group" onClick={() => setAddingGroup(true)}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v3" />
                <path d="M3 7v11a2 2 0 0 0 2 2h6" />
                <path d="M16 16h6M19 13v6" />
              </svg>
            </button>
          )}
          <button className="icon-btn" title={`New ${placeholder.toLowerCase()}`}
            onClick={() => setAdding(true)}>+</button>
          {onToggle && (
            <button className="icon-btn side-toggle" title="Collapse sidebar"
              aria-label="Collapse sidebar" onClick={onToggle}>«</button>
          )}
        </span>
      </div>
      <div className="side-list">
        {allLabel && items.length > 1 && (
          <div className={`side-item all-row ${sel === ALL_ID ? 'active' : ''}`}
            onClick={() => onSelect?.(ALL_ID)}>
            <span className="swatch swatch-all" />
            <span className="name">{allLabel}</span>
            <span className="count">
              {items.reduce((n, l) => n + (canToggle && hidden.has(l.id) ? 0 : countOf(l)), 0)}
            </span>
          </div>
        )}

        {/* Groups are a desktop organizational layer. On the mobile horizontal
            strip (and for views without grouping, e.g. Calendar) every list
            renders flat so nothing nests inside a wrapper that would break the
            chip strip or hide a collapsed list with no way to reopen it. */}
        {groupsOn && !isMobile ? (
          <>
            {groups!.map((g) => {
              const members = membersOf(g)
              const isCollapsed = collapsedSet.has(g.id)
              const anyVisible = canToggle && members.some((l) => !hidden.has(l.id))
              return (
                <div key={g.id} className={`side-group ${overGroup === g.id ? 'drag-over' : ''}`}
                  onDragOver={(e: DragEvent) => { if (dragId) { e.preventDefault(); setOverGroup(g.id) } }}
                  onDragLeave={() => setOverGroup((o) => (o === g.id ? null : o))}
                  onDrop={(e: DragEvent) => {
                    e.preventDefault()
                    if (dragId) moveListToGroup(dragId, g.id)
                    setDragId(null); setOverId(null); setOverGroup(null)
                  }}>
                  <GroupHeader group={g} count={members.reduce((n, l) => n + countOf(l), 0)}
                    collapsed={isCollapsed} canToggle={canToggle} anyVisible={anyVisible}
                    onToggleCollapse={() => toggleCollapse(g.id)}
                    onToggleVisible={() => setHiddenBulk(members.map((l) => l.id), anyVisible)}
                    onRename={(name) => renameGroup(g.id, name)}
                    onDelete={() => removeGroup(g.id)} />
                  {!isCollapsed && members.map(renderRow)}
                  {!isCollapsed && members.length === 0 && (
                    <div className="group-empty">Drag a {placeholder.toLowerCase()} here</div>
                  )}
                </div>
              )
            })}
            {/* Ungrouped lists — a drop target here pulls a list back out of its group. */}
            <div className={`ungrouped ${overGroup === '' ? 'drag-over' : ''}`}
              onDragOver={(e: DragEvent) => { if (dragId) { e.preventDefault(); setOverGroup('') } }}
              onDragLeave={() => setOverGroup((o) => (o === '' ? null : o))}
              onDrop={(e: DragEvent) => {
                e.preventDefault()
                if (dragId) moveListToGroup(dragId, null)
                setDragId(null); setOverId(null); setOverGroup(null)
              }}>
              {ungrouped.map(renderRow)}
            </div>
          </>
        ) : (
          shown.map(renderRow)
        )}

        {shown.length === 0 && !adding && (
          <div className="empty" style={{ padding: '14px 16px' }}>Nothing here yet.</div>
        )}
      </div>
      {addingGroup && (
        <div className="side-add">
          <input className="input" autoFocus placeholder="Group name"
            onBlur={(e) => { if (!e.target.value.trim()) setAddingGroup(false) }}
            onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
              const v = (e.target as HTMLInputElement).value
              if (e.key === 'Enter' && v.trim()) createGroup(v.trim())
              if (e.key === 'Escape') setAddingGroup(false)
            }} />
        </div>
      )}
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
          groups={groupsOn ? groups! : undefined}
          groupId={groupsOn ? (groupOf.get(editing.id) ?? null) : undefined}
          onSetGroup={groupsOn ? (gid) => moveListToGroup(editing.id, gid) : undefined}
          onClose={() => setEditing(null)} onSave={save} onDelete={remove}
          onArchive={onArchive && ((id) => { setEditing(null); onArchive(id) })} />
      )}
    </div>
  )
}

// A collapsible group header. Rename edits inline; delete asks once. All actions
// live behind a hover-revealed ⋯ so the resting row stays a compact single line.
function GroupHeader({ group, count, collapsed, canToggle, anyVisible,
  onToggleCollapse, onToggleVisible, onRename, onDelete }: {
  group: TaskGroup; count: number; collapsed: boolean
  canToggle: boolean; anyVisible: boolean
  onToggleCollapse: () => void; onToggleVisible: () => void
  onRename: (name: string) => void; onDelete: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [name, setName] = useState(group.name)

  if (renaming) {
    return (
      <div className="side-add group-rename">
        <input className="input" autoFocus value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => setRenaming(false)}
          onKeyDown={(e: KeyboardEvent) => {
            if (e.key === 'Enter') { if (name.trim()) onRename(name.trim()); setRenaming(false) }
            if (e.key === 'Escape') { setName(group.name); setRenaming(false) }
          }} />
      </div>
    )
  }
  return (
    <div className="group-head">
      <button className="group-caret" title={collapsed ? 'Expand' : 'Collapse'}
        aria-expanded={!collapsed} onClick={onToggleCollapse}>
        <span className={`caret ${collapsed ? '' : 'open'}`}>▸</span>
      </button>
      <button className="group-name" onClick={onToggleCollapse}>{group.name}</button>
      <span className="count">{count}</span>
      {canToggle && (
        <button className="group-eye" title={anyVisible ? 'Hide all in group' : 'Show all in group'}
          aria-label={anyVisible ? 'Hide all in group' : 'Show all in group'}
          aria-pressed={anyVisible} onClick={onToggleVisible}>
          {anyVisible ? '◉' : '◌'}
        </button>
      )}
      {confirming ? (
        <button className="group-btn danger" title="Delete group (lists are kept)"
          onClick={onDelete}>delete?</button>
      ) : (
        <span className="group-actions">
          <button className="group-btn" title="Rename group"
            onClick={() => { setName(group.name); setRenaming(true) }}>✎</button>
          <button className="group-btn" title="Delete group"
            onClick={() => setConfirming(true)}>✕</button>
        </span>
      )}
    </div>
  )
}

function EditModal({ item, placeholder, groups, groupId, onSetGroup, onClose, onSave, onDelete, onArchive }: {
  item: List
  placeholder: string
  groups?: TaskGroup[]
  groupId?: string | null
  onSetGroup?: (groupId: string | null) => void
  onClose: () => void
  onSave: (id: string, body: { name?: string; color?: string | null }) => void
  onDelete: (id: string) => void
  onArchive?: (id: string) => void
}) {
  const [name, setName] = useState(item.name)
  // Wire colors may carry an alpha byte (#RRGGBBAA); compare on the RGB part.
  const [color, setColor] = useState<string | null>(item.color ? item.color.slice(0, 7) : null)
  const [confirming, setConfirming] = useState(false)

  const save = () => {
    onSave(item.id, { name: name.trim() || item.name, color })
  }

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
        {groups && onSetGroup && (
          <div className="field">
            <label className="label">Group</label>
            <select className="input" value={groupId ?? ''}
              onChange={(e) => onSetGroup(e.target.value || null)}>
              <option value="">No group</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </div>
        )}
        <div className="modal-actions">
          <button className={`btn ghost ${confirming ? 'danger' : ''}`}
            onClick={() => (confirming ? onDelete(item.id) : setConfirming(true))}>
            {confirming ? 'Really delete?' : 'Delete'}
          </button>
          {onArchive && !confirming && (
            <button className="btn ghost" title="Hide without deleting — restore later from Settings"
              onClick={() => onArchive(item.id)}>Archive</button>
          )}
          <span className="spacer" />
          <button className="btn" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  )
}
