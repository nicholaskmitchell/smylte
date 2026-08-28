import {
  useEffect, useRef, useState, type CSSProperties, type DragEvent, type KeyboardEvent, type ReactNode,
} from 'react'
import { clientId, type List, type TaskGroup } from '../api'
import { cssColor } from '../util'
import { useEscape, useIsMobile } from '../hooks'
import { useT } from '../i18n'

// Preset collection colors — muted, editorial, distinct from the accent.
export const SWATCHES = [
  '#D9480F', '#C0392B', '#B8860B', '#2E7D32',
  '#00838F', '#1565C0', '#6A1B9A', '#546E7A',
]

// The pinned "All" row's swatch is a ring of the preset colors. Built here from
// SWATCHES rather than hand-written as a second copy in app.css, so the palette
// has exactly one definition — the two used to drift independently. The second
// red and the grey are dropped (at 8px the near-duplicate red muddies the ring
// and the grey reads as a gap), and the first color repeats to close the loop.
const RING_SKIP = new Set(['#C0392B', '#546E7A'])
const RING = SWATCHES.filter((c) => !RING_SKIP.has(c))
export const ALL_SWATCH_STYLE: CSSProperties = {
  background: `conic-gradient(${[...RING, RING[0]].join(', ')})`,
}

// Selection id for the pinned "all collections" row (rendered when the view
// supports a combined mode) — never collides with a real collection id.
export const ALL_ID = '*'

export interface CollectionApi {
  create: (name: string, color?: string | null) => Promise<List | undefined>
  update: (id: string, body: { name?: string; color?: string | null }) => Promise<List | undefined>
  remove: (id: string) => Promise<unknown>
  reorder: (ids: string[]) => Promise<unknown>
}

/**
 * Which kind of collection this sidebar manages — and, through `WORDS`, every
 * sentence that names it.
 *
 * It used to take `title="Lists"` and `placeholder="List"` and compose the rest:
 * `` `New ${placeholder.toLowerCase()}` ``, `` `Drag a ${placeholder.toLowerCase()} here` ``,
 * `` `Manage ${title.toLowerCase()}` ``. Lower-casing a noun to drop it into a
 * sentence is a rule about English orthography and nothing more — German
 * capitalises every noun, so the same trick yields "Neue liste" — and the
 * article in front of it ("a list", "a calendar") is a fact about the noun that
 * only the noun's own language knows: eine Liste, but einen Kalender.
 *
 * So the sentences are written whole, one set per kind, and the caller says
 * which kind it is rather than handing over two words to be assembled.
 */
export type CollectionKind = 'list' | 'calendar'

const WORDS: Record<CollectionKind, {
  /** The section heading: "Lists". */
  heading: string
  /** The singular, standing alone as the edit dialog's title: "List". */
  one: string
  /** "New list" — a whole label, not "New " plus a noun. */
  new: string
  manage: string
  groupEmpty: string
  dropHere: string
  /** Carries an `{archive}` slot, filled with `side.archiveClause` or nothing
   *  depending on whether this sidebar offers archiving. */
  tapHint: string
}> = {
  list: {
    heading: 'side.lists.heading', one: 'side.lists.one', new: 'side.lists.new',
    manage: 'side.lists.manage', groupEmpty: 'side.lists.groupEmpty',
    dropHere: 'side.lists.dropHere', tapHint: 'side.lists.tapHint',
  },
  calendar: {
    heading: 'side.calendars.heading', one: 'side.calendars.one',
    new: 'side.calendars.new', manage: 'side.calendars.manage',
    groupEmpty: 'side.calendars.groupEmpty', dropHere: 'side.calendars.dropHere',
    tapHint: 'side.calendars.tapHint',
  },
}

export function Sidebar({ kind, items, sel = '', countOf, onSelect, onItems, api,
  collapsed, onToggle, allLabel, hiddenIds, onHiddenChange, onArchive, archivedIds,
  groups, onGroupsChange, collapsedGroups, onCollapsedGroupsChange,
  completedActive, onToggleCompleted, extra }: {
  kind: CollectionKind
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
  // Completed view (opt-in, Tasks only): a footer button beneath the lists and
  // groups that opens a dedicated "just completed tasks" pane. When provided,
  // `completedActive` reflects whether that pane is currently showing.
  completedActive?: boolean
  onToggleCompleted?: () => void
  // A second, foreign section under the collections — the Calendar tab's task
  // lists. It is rendered rather than described because those rows are not this
  // sidebar's `items`: they are a different kind of collection, borrowed for
  // visibility only, and must not offer rename, recolor, delete or drag-reorder
  // (a reorder here would PROPPATCH calendar-order onto the *task* collections).
  // One slot, used by both the desktop panel and the mobile drawer.
  extra?: ReactNode
}) {
  const tr = useT()
  const words = WORDS[kind]
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
  // Mobile only: the vertical management drawer (bottom sheet). On phones the
  // sidebar is a single trigger bar; tapping it opens this drawer, which reuses
  // the full desktop layout — groups, per-row edit, add — so everything the
  // desktop rail can do (rename, recolor, delete, group) is reachable on touch.
  const [drawerOpen, setDrawerOpen] = useState(false)

  // An in-flight guard, the way the booking-link editor already has one. The
  // form keeps its input mounted, focused and holding the typed name for the
  // whole round trip, so a second Enter fired a second `api.create` with the
  // same name — and each one is a real MKCALENDAR/MKCOL against Radicale. The
  // account ended up with two indistinguishable collections that Tasks.org, jtx
  // and Thunderbird all see too, and deleting the right one is its own
  // destructive step.
  const creating = useRef(false)
  const create = async (name: string, color: string | null) => {
    if (creating.current) return
    creating.current = true
    let l
    try {
      l = await api.create(name, color)
    } finally {
      creating.current = false
    }
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
    const prevGroups = groups
    const left = items.filter((l) => l.id !== id)
    onItems(left)
    if (canSelect && sel === id) onSelect?.(left[0]?.id || '')
    // Drop the deleted list out of any group so the stored blob stays tidy.
    const regrouped = groupsOn && groups!.some((g) => g.lists.includes(id))
    if (regrouped) {
      onGroupsChange!(groups!.map((g) => ({ ...g, lists: g.lists.filter((x) => x !== id) })))
    }
    if ((await api.remove(id)) === undefined) {
      // Roll back BOTH. `onGroupsChange` is written straight through to the
      // server by App, so only restoring `items` brought the list back
      // ungrouped — with the loss already persisted, and nothing left to
      // undo it from.
      onItems(prev)
      if (regrouped) onGroupsChange!(prevGroups!)
    }
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
    // Through cssColor, and the hidden branch especially: interpolating a wire
    // value into a `boxShadow` SHORTHAND lets it escape the property boundary
    // far more freely than a plain `background:` does.
    const c = cssColor(l.color)
    if (canToggle && hidden.has(l.id)) {
      return { background: 'transparent', boxShadow: `inset 0 0 0 1.5px ${c ?? 'var(--fg-faint)'}` }
    }
    return c ? { background: c } : undefined
  }

  // One collection row — reused by both the grouped and ungrouped sections. In
  // visibility mode (Tasks + Calendar) the whole row is a checkbox: clicking
  // anywhere shows/hides that collection, its color swatch solid when shown and
  // a hollow ring when hidden. Where a view also selects (unused today) the row
  // single-selects instead.
  const renderRow = (l: List) => {
    const isHidden = canToggle && hidden.has(l.id)
    const primary = () => (canSelect ? onSelect?.(l.id) : canToggle ? toggleVisible(l.id) : undefined)
    const rowToggles = canToggle && !canSelect        // the whole row is the toggle
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
        <span className="swatch" style={swatchStyle(l)} />
        <span className="name">{l.name}</span>
        <span className="count">{countOf(l)}</span>
        <button className="side-edit" title={tr('side.edit')}
          aria-label={tr('side.editItem', { name: l.name })}
          onClick={(e) => { e.stopPropagation(); setEditing(l) }}>⋯</button>
      </div>
    )
  }

  // The scrollable body of collections (groups + lists) — shared by the desktop
  // sidebar and the mobile drawer. The grouped layout renders wherever groups
  // are enabled; on the phone drawer that means groups are finally reachable
  // (create / rename / delete / collapse), where the old horizontal strip had
  // no room for them at all.
  const collectionsBody = (
    <>
      {allLabel && items.length > 1 && (
        <div className={`side-item all-row ${sel === ALL_ID ? 'active' : ''}`}
          onClick={() => onSelect?.(ALL_ID)}>
          <span className="swatch swatch-all" style={ALL_SWATCH_STYLE} />
          <span className="name">{allLabel}</span>
          <span className="count">
            {items.reduce((n, l) => n + (canToggle && hidden.has(l.id) ? 0 : countOf(l)), 0)}
          </span>
        </div>
      )}

      {groupsOn ? (
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
                  <div className="group-empty">
                    {isMobile ? tr(words.groupEmpty) : tr(words.dropHere)}
                  </div>
                )}
              </div>
            )
          })}
          {/* Ungrouped lists — a drop target here pulls a list back out of its group. */}
          <div className={`ungrouped ${ungrouped.length === 0 ? 'is-empty' : ''} ${overGroup === '' ? 'drag-over' : ''}`}
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
        <div className="empty" style={{ padding: '14px 16px' }}>{tr('side.nothingHere')}</div>
      )}
    </>
  )

  // The inline "add a group" / "add a collection" text inputs, shared by both
  // layouts. They live just below the collection list.
  const addInputs = (
    <>
      {addingGroup && (
        <div className="side-add">
          <input className="input" autoFocus placeholder={tr('side.groupName')}
            onBlur={(e) => { if (!e.target.value.trim()) setAddingGroup(false) }}
            onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
              const v = (e.target as HTMLInputElement).value
              if (e.key === 'Enter' && v.trim()) createGroup(v.trim())
              if (e.key === 'Escape') setAddingGroup(false)
            }} />
        </div>
      )}
      {adding && (
        <AddForm placeholder={tr(words.one)} onCancel={() => setAdding(false)} onCreate={create} />
      )}
    </>
  )

  const completedFooter = onToggleCompleted && (
    <button className={`side-completed ${completedActive ? 'active' : ''}`}
      aria-pressed={completedActive} onClick={onToggleCompleted}>
      {completedActive ? tr('side.backToTasks') : tr('side.viewCompleted')}
    </button>
  )

  const editModal = editing && (
    <EditModal item={editing} placeholder={tr(words.one)}
      groups={groupsOn ? groups! : undefined}
      groupId={groupsOn ? (groupOf.get(editing.id) ?? null) : undefined}
      onSetGroup={groupsOn ? (gid) => moveListToGroup(editing.id, gid) : undefined}
      onClose={() => setEditing(null)} onSave={save} onDelete={remove}
      onArchive={onArchive && ((id) => { setEditing(null); onArchive(id) })} />
  )

  // ── mobile: a trigger bar that opens a full-height management drawer ────────
  // The phone layout used to be a horizontal chip strip with no room to rename,
  // delete, or group anything (the edit affordance was hover-only and unreachable
  // on touch). Instead we surface a single bar; tapping it opens a bottom-sheet
  // drawer that reuses the desktop vertical layout, where every action lives.
  if (isMobile) {
    const total = shown.length
    const shownCount = canToggle ? shown.filter((l) => !hidden.has(l.id)).length : total
    const summary = total === 0
      ? tr('side.noneYet')
      : canToggle ? tr('side.shownOf', { shown: shownCount, total }) : `${total}`
    const closeDrawer = () => { setDrawerOpen(false); setAdding(false); setAddingGroup(false) }
    return (
      <>
        <div className="side-mobilebar">
          <button className="side-mobiletrigger" onClick={() => setDrawerOpen(true)}
            aria-haspopup="dialog" aria-expanded={drawerOpen}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
              strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="4" y1="7" x2="20" y2="7" /><line x1="4" y1="12" x2="20" y2="12" />
              <line x1="4" y1="17" x2="20" y2="17" />
            </svg>
            <span className="mb-title">{tr(words.heading)}</span>
            <span className="mb-summary">{summary}</span>
            <span className="mb-caret" aria-hidden="true">▾</span>
          </button>
          {completedFooter && (
            <button className={`side-mobile-completed ${completedActive ? 'active' : ''}`}
              title={completedActive
                ? tr('side.backToTasksShort') : tr('side.viewCompletedShort')}
              aria-pressed={completedActive} onClick={onToggleCompleted}>✓</button>
          )}
          <button className="side-mobile-add" title={tr(words.new)}
            aria-label={tr(words.new)}
            onClick={() => { setDrawerOpen(true); setAdding(true) }}>+</button>
        </div>

        {drawerOpen && (
          <div className="overlay drawer-overlay" onClick={closeDrawer}>
            <div className="side drawer" role="dialog" aria-label={tr(words.manage)}
              onClick={(e) => e.stopPropagation()}>
              <div className="side-head">
                <span className="label">{tr(words.heading)}</span>
                <span className="side-head-actions">
                  {groupsOn && (
                    <button className="icon-btn" title={tr('side.newGroup')}
                      aria-label={tr('side.newGroup')}
                      onClick={() => setAddingGroup(true)}>
                      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
                        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v3" />
                        <path d="M3 7v11a2 2 0 0 0 2 2h6" />
                        <path d="M16 16h6M19 13v6" />
                      </svg>
                    </button>
                  )}
                  <button className="icon-btn" title={tr(words.new)}
                    aria-label={tr(words.new)}
                    onClick={() => setAdding(true)}>+</button>
                  <button className="icon-btn" title={tr('side.drawerDone')}
                    aria-label={tr('common.close')}
                    onClick={closeDrawer}>✕</button>
                </span>
              </div>
              {canToggle && (
                <p className="drawer-hint">
                  {tr(words.tapHint,
                    { archive: onArchive ? tr('side.archiveClause') : '' })}
                </p>
              )}
              <div className="side-list">{collectionsBody}{extra}</div>
              {addInputs}
              {completedFooter}
            </div>
          </div>
        )}
        {editModal}
      </>
    )
  }

  // Collapsed: a thin rail of color dots — collections stay one click away. The
  // mobile layout is already a compact strip, so collapse is a desktop-only
  // affordance. Groups don't render here (the rail is too thin); every list dot
  // still shows so nothing becomes unreachable.
  if (collapsed) {
    return (
      <div className="side collapsed">
        <button className="icon-btn side-toggle" title={tr('side.expand')}
          aria-label={tr('side.expand')} onClick={onToggle}>»</button>
        <div className="side-rail">
          {allLabel && items.length > 1 && (
            <button className={`rail-dot ${sel === ALL_ID ? 'active' : ''}`}
              title={allLabel} onClick={() => onSelect?.(ALL_ID)}>
              <span className="swatch swatch-all" style={ALL_SWATCH_STYLE} />
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
        {onToggleCompleted && (
          <button className={`icon-btn side-completed-rail ${completedActive ? 'active' : ''}`}
            title={completedActive
              ? tr('side.backToTasksShort') : tr('side.viewCompletedShort')}
            aria-pressed={completedActive} onClick={onToggleCompleted}>✓</button>
        )}
      </div>
    )
  }

  return (
    <div className="side">
      <div className="side-head">
        <span className="label">{tr(words.heading)}</span>
        <span className="side-head-actions">
          {groupsOn && (
            <button className="icon-btn" title={tr('side.newGroup')}
              aria-label={tr('side.newGroup')} onClick={() => setAddingGroup(true)}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v3" />
                <path d="M3 7v11a2 2 0 0 0 2 2h6" />
                <path d="M16 16h6M19 13v6" />
              </svg>
            </button>
          )}
          {/* aria-label as well as title, matching the drawer's copy of this
              button. Its text content is "+", and `title` is only the
              last-resort step of the accessible-name algorithm. */}
          <button className="icon-btn" title={tr(words.new)}
            aria-label={tr(words.new)}
            onClick={() => setAdding(true)}>+</button>
          {onToggle && (
            <button className="icon-btn side-toggle" title={tr('side.collapse')}
              aria-label={tr('side.collapse')} onClick={onToggle}>«</button>
          )}
        </span>
      </div>
      <div className="side-list">{collectionsBody}{extra}</div>
      {completedFooter}
      {addInputs}
      {editModal}
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
  const tr = useT()
  const [renaming, setRenaming] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [name, setName] = useState(group.name)

  // Disarm on Escape, and whenever the header changes shape underneath the armed
  // state — collapsing, renaming, or the group itself changing.
  useEscape(() => setConfirming(false))
  useEffect(() => { setConfirming(false) }, [group.id, collapsed, renaming])

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
      <button className="group-caret"
        title={collapsed ? tr('side.groupExpand') : tr('side.groupCollapse')}
        aria-expanded={!collapsed} onClick={onToggleCollapse}>
        <span className={`caret ${collapsed ? '' : 'open'}`}>▸</span>
      </button>
      <button className="group-name" onClick={onToggleCollapse}>{group.name}</button>
      <span className="count">{count}</span>
      {canToggle && (
        <button className="group-eye"
          title={anyVisible ? tr('side.hideAllInGroup') : tr('side.showAllInGroup')}
          aria-label={anyVisible ? tr('side.hideAllInGroup') : tr('side.showAllInGroup')}
          aria-pressed={anyVisible} onClick={onToggleVisible}>
          {anyVisible ? '◉' : '◌'}
        </button>
      )}
      {confirming ? (
        // A way BACK OUT. `confirming` was set to true by the ✕ and set back to
        // false by nothing — no Escape, no blur, no cancel — so arming the
        // delete replaced the whole action cluster (the rename ✎ included) with
        // a red button that deletes on the next click, permanently, with the
        // only escape being to unmount the sidebar by switching tabs or closing
        // the drawer. Neither is discoverable, and the two controls that arm it
        // sit one pixel apart in the drawer.
        <span className="group-actions">
          {/* The visible word stays IN the accessible name — it is what the
              button says and what a sighted user reads back; the group is
              appended because ✎ / ✕ / delete? repeat once per group. */}
          <button className="group-btn danger" title={tr('side.deleteGroupTitle')}
            aria-label={tr('side.deleteGroupConfirmAria', { name: group.name })}
            onClick={onDelete}>{tr('side.deleteGroupConfirm')}</button>
          <button className="group-btn" title={tr('side.keepGroup')}
            aria-label={tr('common.cancel')} onClick={() => setConfirming(false)}>✕</button>
        </span>
      ) : (
        <span className="group-actions">
          <button className="group-btn" title={tr('side.renameGroup')}
            aria-label={tr('side.renameGroupOf', { name: group.name })}
            onClick={() => { setName(group.name); setRenaming(true) }}>✎</button>
          <button className="group-btn" title={tr('side.deleteGroup')}
            aria-label={tr('side.deleteGroupOf', { name: group.name })}
            onClick={() => setConfirming(true)}>✕</button>
        </span>
      )}
    </div>
  )
}

/** The clear, the eight presets, and the way past them.
 *
 * One definition for both the places a collection's color is chosen — the add
 * form and the edit modal — so the two cannot drift, which is the same reason
 * ALL_SWATCH_STYLE is built from SWATCHES rather than written out again.
 */
function ColorRow({ color, onPick }: { color: string | null; onPick: (c: string | null) => void }) {
  const tr = useT()
  // Compare on the RGB prefix: the wire value may carry an alpha byte (Apple
  // Calendar and DAVx5 both write one) and it has to keep matching its preset.
  const isSwatch = (c: string) => color?.slice(0, 7).toLowerCase() === c.toLowerCase()
  // Eight presets run out once you keep more than eight collections, and a color
  // another CalDAV client wrote is rarely one of ours — so anything set that no
  // preset covers belongs to the custom square, which is what makes exactly one
  // square in the row read as selected. Through cssColor like every other place
  // this value reaches a style: it is whatever another client PROPPATCHed, and
  // this paints a live `background` (see the hostile-wire-color suite). Junk
  // lights nothing, which is honest — no square represents it.
  const customColor = SWATCHES.some(isSwatch) ? null : cssColor(color)

  return (
    <div className="color-row">
      <button className={`color-dot none ${color === null ? 'on' : ''}`}
        title={tr('side.noColor')}
        onClick={() => onPick(null)}>✕</button>
      {SWATCHES.map((c) => (
        <button key={c} className={`color-dot ${isSwatch(c) ? 'on' : ''}`}
          style={{ background: c }} title={c} onClick={() => onPick(c)} />
      ))}
      {/* The escape hatch past the presets. Native rather than a drawn picker:
          it is the browser's own dialog, so it brings a hex field and an
          eyedropper for free, needs no dependency, and is the control
          AppearancePanel already uses. The input is wrapped and made invisible
          rather than styled directly, because a color input can only ever paint
          its own value and has no value meaning "not custom" — so the label
          draws the fill (a spectrum until a color is chosen) and the input,
          stretched over it at full size, is what every click and Tab lands on.
          It takes exactly `#rrggbb`: anything longer or upper-case is sanitized
          by the DOM, which then fights the value React writes back, so trim and
          lower it here. Picking drops any alpha byte on purpose — the dialog
          cannot show alpha, so re-attaching the old one would keep a
          translucency the user never saw. */}
      <label className={`color-dot custom ${customColor ? 'on' : ''}`}
        title={tr('side.customColor')}
        style={customColor ? { background: customColor } : undefined}>
        <input type="color" aria-label={tr('side.customColor')}
          value={(cssColor(color)?.slice(0, 7) ?? '#808080').toLowerCase()}
          onChange={(e) => onPick(e.target.value)} />
      </label>
    </div>
  )
}

/** A new collection: its name, and its color up front.
 *
 * The color is here so a new list or calendar arrives already distinguishable,
 * rather than landing uncolored and needing a second trip through the edit
 * modal — which matters most at exactly the point you are adding the ninth one.
 */
function AddForm({ placeholder, onCancel, onCreate }: {
  placeholder: string
  onCancel: () => void
  onCreate: (name: string, color: string | null) => void
}) {
  const [name, setName] = useState('')
  const [color, setColor] = useState<string | null>(null)

  return (
    // An empty form still closes when you click away, as it always has — but
    // the row below the field is part of it now, so "away" has to mean out of
    // the form entirely. Without the containment check, picking a color would
    // blur the name field and dismiss the form mid-choice.
    <div className="side-add with-color" onBlur={(e) => {
      if (!name.trim() && !e.currentTarget.contains(e.relatedTarget as Node | null)) onCancel()
    }}>
      <input className="input" autoFocus placeholder={placeholder} value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
          if (e.key === 'Enter' && name.trim()) onCreate(name.trim(), color)
          if (e.key === 'Escape') onCancel()
        }} />
      <ColorRow color={color} onPick={setColor} />
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
  const tr = useT()
  const [name, setName] = useState(item.name)
  // Hold the wire value as written. It may carry an alpha byte (#RRGGBBAA —
  // Apple Calendar and DAVx5 both write one); truncating it for the swatch
  // comparison and then saving *that* meant opening this modal to rename a list
  // PROPPATCHed the shortened color back and dropped the alpha for every other
  // client. Compare on the RGB prefix instead, and keep the original intact.
  const [color, setColor] = useState<string | null>(item.color)
  const [confirming, setConfirming] = useState(false)

  const save = () => {
    // Send the color only when the user actually picked one, so a rename never
    // rewrites a color it merely displayed — case-insensitively, now that a
    // control reporting lower-case can set it. The picker is seeded with a
    // lowered hex (it accepts nothing else), so confirming or cancelling on the
    // colour a list already had comes back as `#d9480f` against a stored
    // `#D9480F`, and a bare !== would PROPPATCH that case flip out to every
    // other client as though it were a real recolour.
    const body: { name?: string; color?: string | null } = { name: name.trim() || item.name }
    const same = color === item.color
      || (color !== null && item.color !== null
        && color.toLowerCase() === item.color.toLowerCase())
    if (!same) body.color = color
    onSave(item.id, body)
  }

  // The only place a list or calendar is renamed, recoloured, regrouped,
  // archived or deleted — and on a phone the only route to any of it. It was the
  // last dialog in the app with no Escape, no dialog role and a bare
  // click-to-close scrim over a form.
  useEscape(onClose)
  const scrimPress = useRef(false)

  return (
    <div className="overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={placeholder}
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{placeholder}</span>
          <button className="icon-btn" onClick={onClose} aria-label={tr('common.close')}>✕</button>
        </div>
        <div className="field">
          <label className="label">{tr('side.name')}</label>
          <input className="input" autoFocus value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') save() }} />
        </div>
        <div className="field">
          <label className="label">{tr('side.color')}</label>
          <ColorRow color={color} onPick={setColor} />
        </div>
        {groups && onSetGroup && (
          <div className="field">
            <label className="label">{tr('side.group')}</label>
            <select className="input" value={groupId ?? ''}
              onChange={(e) => onSetGroup(e.target.value || null)}>
              <option value="">{tr('side.noGroup')}</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </div>
        )}
        <div className="modal-actions">
          <button className={`btn ghost ${confirming ? 'danger' : ''}`}
            onClick={() => (confirming ? onDelete(item.id) : setConfirming(true))}>
            {confirming ? tr('side.reallyDelete') : tr('common.delete')}
          </button>
          {onArchive && !confirming && (
            <button className="btn ghost" title={tr('side.archiveTitle')}
              onClick={() => onArchive(item.id)}>{tr('side.archive')}</button>
          )}
          <span className="spacer" />
          <button className="btn" onClick={save}>{tr('common.save')}</button>
        </div>
      </div>
    </div>
  )
}
