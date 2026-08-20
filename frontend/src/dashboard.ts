// Home dashboard layout — the grid math, kept free of React so it can be
// reasoned about and tested on its own.
//
// The model is a 12-column grid with a fixed row height. A module owns a
// rectangle of cells; overlaps are illegal and resolved by pushing the loser
// downward (the Squarespace behaviour — things get out of the way rather than
// refusing the drop). Every mutation runs through `packDown`, so a layout that
// leaves this module is always overlap-free and top-justified.

export const COLS = 12
export const ROW_H = 44        // px per grid row; mirrored by --dash-row in app.css
export const GAP = 12          // px between modules

export type ModuleKind =
  | 'today' | 'overdue' | 'upcoming' | 'mini_calendar'
  | 'completed' | 'booking_links' | 'bookings' | 'quick_add'

export interface DashboardModule {
  id: string
  kind: ModuleKind
  x: number
  y: number
  w: number
  h: number
}

export interface ModuleSpec {
  label: string
  blurb: string
  w: number
  h: number
  minW: number
  minH: number
}

/** What each module is, and how big it wants to be when first placed. */
export const MODULE_SPECS: Record<ModuleKind, ModuleSpec> = {
  today: { label: 'Today', blurb: 'Tasks due today, across every list.', w: 4, h: 6, minW: 3, minH: 3 },
  overdue: { label: 'Overdue', blurb: 'Anything past its due date.', w: 4, h: 5, minW: 3, minH: 3 },
  upcoming: { label: 'Upcoming', blurb: 'The next seven days of tasks.', w: 4, h: 6, minW: 3, minH: 3 },
  mini_calendar: { label: 'Mini calendar', blurb: "This month, dotted in each calendar's color.", w: 4, h: 6, minW: 3, minH: 5 },
  completed: { label: 'Recently completed', blurb: 'What you have finished lately.', w: 4, h: 5, minW: 3, minH: 3 },
  booking_links: { label: 'Booking links', blurb: 'Your scheduling links and their state.', w: 6, h: 5, minW: 3, minH: 3 },
  bookings: { label: 'Upcoming bookings', blurb: 'Who has booked time with you.', w: 6, h: 5, minW: 3, minH: 3 },
  quick_add: { label: 'Quick add', blurb: 'Drop a task straight onto a list.', w: 4, h: 3, minW: 3, minH: 2 },
}

export const MODULE_KINDS = Object.keys(MODULE_SPECS) as ModuleKind[]

/** What a fresh dashboard looks like before the user touches it. */
export const DEFAULT_LAYOUT: DashboardModule[] = [
  { id: 'm-today', kind: 'today', x: 0, y: 0, w: 4, h: 6 },
  { id: 'm-upcoming', kind: 'upcoming', x: 4, y: 0, w: 4, h: 6 },
  { id: 'm-calendar', kind: 'mini_calendar', x: 8, y: 0, w: 4, h: 6 },
  { id: 'm-overdue', kind: 'overdue', x: 0, y: 6, w: 6, h: 5 },
  { id: 'm-completed', kind: 'completed', x: 6, y: 6, w: 6, h: 5 },
]

const MAX_MODULES = 40
// How far down the grid a module may sit, and how tall it may be. These are two
// different bounds and were sharing one: clamping HEIGHT to 200 rows let the
// editor build a module the server's `h: le=40` rejects, so the whole settings
// PUT 422'd and the layout was silently kept local and lost on reload.
const MAX_ROWS = 200
const MAX_MODULE_H = 40

// ── geometry ────────────────────────────────────────────────────────────────

export function overlaps(a: DashboardModule, b: DashboardModule): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

/** Clamp a module's rectangle into the grid, honouring its kind's minimums. */
export function clampToGrid(m: DashboardModule): DashboardModule {
  const spec = MODULE_SPECS[m.kind]
  const minW = spec?.minW ?? 2
  const minH = spec?.minH ?? 2
  const w = Math.min(COLS, Math.max(minW, Math.round(m.w) || minW))
  const h = Math.min(MAX_MODULE_H, Math.max(minH, Math.round(m.h) || minH))
  const x = Math.min(COLS - w, Math.max(0, Math.round(m.x) || 0))
  const y = Math.min(MAX_ROWS, Math.max(0, Math.round(m.y) || 0))
  return { ...m, x, y, w, h }
}

/**
 * Resolve overlaps and close vertical gaps.
 *
 * Modules are settled in reading order (top-to-bottom, then left-to-right) and
 * each one floats up until it would touch a module already placed. `pinned`
 * keeps its row — that is the module the user is actively dragging, and letting
 * it float would fight the pointer.
 */
export function packDown(mods: DashboardModule[], pinned?: string): DashboardModule[] {
  const order = [...mods].sort((a, b) => (a.y - b.y) || (a.x - b.x))
  const placed: DashboardModule[] = []
  for (const mod of order) {
    const m = clampToGrid(mod)
    if (m.id === pinned) {
      // Push anything already placed that collides with the pinned module out
      // of its way, then keep its row exactly.
      //
      // `if`, not `while`, and the difference is not style: one push always
      // clears the overlap by construction (the pushed module starts at the
      // pinned one's bottom edge), and with the MAX_ROWS clamp below a `while`
      // can never terminate — a clamped y can still overlap, so the loop spins
      // forever rather than failing a test.
      for (let i = 0; i < placed.length; i++) {
        if (overlaps(placed[i], m)) {
          placed[i] = { ...placed[i], y: Math.min(MAX_ROWS, m.y + m.h) }
        }
      }
      placed.push(m)
      continue
    }
    let y = m.y
    // Float up through empty space…
    while (y > 0 && !placed.some((p) => overlaps(p, { ...m, y: y - 1 }))) y--
    // …then down past anything it landed on.
    while (placed.some((p) => overlaps(p, { ...m, y }))) y++
    // Clamped to the same bound `clampToGrid` applies and the server enforces
    // (`y: le=200` in app.py). Stacking past it produced a layout the settings
    // PUT answers 422 for, so the WHOLE settings write was refused and the new
    // layout was kept only locally — lost on the next reload, with no error the
    // user could act on. Two modules can now share a row at the very bottom of a
    // 200-row grid, which is reachable only from an absurd layout and is
    // strictly better than losing the write.
    placed.push({ ...m, y: Math.min(MAX_ROWS, y) })
  }
  return placed
}

export function moveModule(
  mods: DashboardModule[], id: string, x: number, y: number,
): DashboardModule[] {
  const next = mods.map((m) => (m.id === id ? clampToGrid({ ...m, x, y }) : m))
  return packDown(next, id)
}

export function resizeModule(
  mods: DashboardModule[], id: string, w: number, h: number,
): DashboardModule[] {
  const next = mods.map((m) => (m.id === id ? clampToGrid({ ...m, w, h }) : m))
  return packDown(next, id)
}

/** Append a module of `kind` below everything else. */
export function addModule(mods: DashboardModule[], kind: ModuleKind, id: string): DashboardModule[] {
  if (mods.length >= MAX_MODULES) return mods
  const spec = MODULE_SPECS[kind]
  if (!spec) return mods
  const bottom = mods.reduce((acc, m) => Math.max(acc, m.y + m.h), 0)
  return packDown([...mods, { id, kind, x: 0, y: bottom, w: spec.w, h: spec.h }])
}

export function removeModule(mods: DashboardModule[], id: string): DashboardModule[] {
  return packDown(mods.filter((m) => m.id !== id))
}

/** Total grid rows the layout occupies — what the container's height is sized to. */
export function layoutRows(mods: DashboardModule[]): number {
  return mods.reduce((acc, m) => Math.max(acc, m.y + m.h), 0)
}

// ── validation ──────────────────────────────────────────────────────────────

/**
 * Coerce arbitrary parsed JSON into a legal layout. Never throws: a blob that
 * was hand-edited, written by an older schema, or truncated should cost the
 * user their arrangement, not the whole Home tab.
 */
export function sanitizeLayout(raw: unknown): DashboardModule[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: DashboardModule[] = []
  for (const item of raw.slice(0, MAX_MODULES)) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    if (typeof o.id !== 'string' || !o.id || seen.has(o.id)) continue
    if (typeof o.kind !== 'string' || !(o.kind in MODULE_SPECS)) continue
    const nums = [o.x, o.y, o.w, o.h]
    if (nums.some((n) => typeof n !== 'number' || !Number.isFinite(n))) continue
    seen.add(o.id)
    out.push(clampToGrid({
      id: o.id.slice(0, 64),
      kind: o.kind as ModuleKind,
      x: o.x as number, y: o.y as number, w: o.w as number, h: o.h as number,
    }))
  }
  return packDown(out)
}

// ── pointer → grid ──────────────────────────────────────────────────────────

/** Convert a pixel offset inside the grid container to a cell coordinate. */
export function pxToCell(px: number, py: number, containerW: number): { x: number; y: number } {
  const colW = containerW / COLS
  return {
    x: colW > 0 ? Math.round(px / colW) : 0,
    y: Math.round(py / (ROW_H + GAP)),
  }
}

/** Convert a pixel delta to a cell delta (used while dragging and resizing). */
export function pxToCellDelta(dx: number, dy: number, containerW: number): { dx: number; dy: number } {
  const colW = containerW / COLS
  return {
    dx: colW > 0 ? Math.round(dx / colW) : 0,
    dy: Math.round(dy / (ROW_H + GAP)),
  }
}
