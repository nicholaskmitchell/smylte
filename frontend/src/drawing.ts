// The day's drawing, as the server sends it (backend/smylted/drawing/).
//
// The server draws: one engine for every device and for the e-paper desk unit,
// so the same day is the same picture everywhere, and the per-install salt that
// makes it unpredictable never leaves the server. The client only renders what
// it is sent (components/DayDrawing.tsx) and decides, from the day as it is
// right now, which of the drawing's conditional parts are showing — so a tick
// grows a fruit at once, offline included, without asking the server again.
//
// Everything here is pure and DOM-free except the cache, which is localStorage.
import { api } from './api'
import { lastCacheUser } from './cache'

/** What the drawing reacts to. Every field is also said in text on the screen
 *  the drawing sits on; the drawing never carries information of its own. */
export type DayState = {
  progress: number        // done / planned today, 0..1
  rewards: number         // tasks finished today, one reward each
  focusActive: boolean    // a focus session is running
  allDone: boolean        // everything planned is done
  nothingPlanned: boolean // nothing is planned
  overdue: number         // overdue tasks in view
  hour: number            // local hour, 0..23
}

export const EMPTY_DAY: DayState = {
  progress: 0, rewards: 0, focusActive: false, allDone: false, nothingPlanned: true, overdue: 0, hour: 12,
}

/** The rewards a drawing has slots for. Past this it stays full; the count in
 *  text still carries the number. */
export const MAX_REWARDS = 12
const OVERDUE_LEVELS = 3

export type Atom =
  | ['reward', number] | ['focus'] | ['allDone'] | ['notAllDone'] | ['nothingPlanned'] | ['planned']
  | ['overdue', number] | ['calm'] | ['progress', number] | ['hour', number, number]

export type Role = 'line' | 'wash' | 'accent'

export type DrawMark = {
  id: string
  role: Role
  /** Three boil frames for a line, one path for a wash or an accent. */
  frames: string[]
  when: Atom[]
  reward: number | null
}

export type DrawingPayload = {
  view: 'today' | 'tasks' | 'calendar' | 'settings'
  day: string | null
  subject: string
  theme: 'light' | 'dark'
  viewBox: [number, number, number, number]
  marks: DrawMark[]
  ambient: { seconds: number; when: Atom[]; frames: DrawMark[][] } | null
}

/** Is this atom true of `s`? The server's conditions.py, mirrored. */
function holds(a: Atom, s: DayState): boolean {
  switch (a[0]) {
    case 'reward': return Math.min(s.rewards, MAX_REWARDS) > a[1]
    case 'focus': return s.focusActive
    case 'allDone': return s.allDone
    case 'notAllDone': return !s.allDone
    case 'nothingPlanned': return s.nothingPlanned
    case 'planned': return !s.nothingPlanned
    case 'overdue': return Math.min(s.overdue, OVERDUE_LEVELS) >= a[1]
    case 'calm': return s.overdue === 0
    case 'progress': return s.progress >= a[1]
    case 'hour': {
      const [, from, to] = a
      return from < to ? s.hour >= from && s.hour < to : s.hour >= from || s.hour < to
    }
  }
}

/** A condition list is its atoms ANDed; an empty one always holds. */
export function evaluate(when: Atom[], s: DayState): boolean {
  return when.every((a) => holds(a, s))
}

// ── validation ─────────────────────────────────────────────────────────────
// Path data goes straight into the DOM, and the cached copy lives in
// localStorage, which anything with script on this origin can write. So the
// payload is checked to the letter before it is used: path data in the
// server's own alphabet (move, line, cubic and close, numbers and spaces), the
// three roles, and only atoms this file knows. Anything else is no drawing.

const PATH = /^[MLCZ0-9 .-]+$/
const ROLES = new Set<Role>(['line', 'wash', 'accent'])
const ARITY: Record<string, number> = {
  reward: 1, focus: 0, allDone: 0, notAllDone: 0, nothingPlanned: 0, planned: 0,
  overdue: 1, calm: 0, progress: 1, hour: 2,
}
const MAX_MARKS = 400
const MAX_PATH = 20000

function atoms(raw: unknown): Atom[] | null {
  if (!Array.isArray(raw)) return null
  const out: Atom[] = []
  for (const a of raw) {
    if (!Array.isArray(a) || typeof a[0] !== 'string' || !(a[0] in ARITY)) return null
    if (a.length !== ARITY[a[0]] + 1 || !a.slice(1).every((n) => typeof n === 'number' && Number.isFinite(n))) return null
    out.push(a as Atom)
  }
  return out
}

function mark(raw: unknown, frames: number | null): DrawMark | null {
  if (!raw || typeof raw !== 'object') return null
  const m = raw as Record<string, unknown>
  if (typeof m.id !== 'string' || !/^[\w-]{1,24}$/.test(m.id)) return null
  if (typeof m.role !== 'string' || !ROLES.has(m.role as Role)) return null
  const want = frames ?? (m.role === 'line' ? 3 : 1)
  if (!Array.isArray(m.frames) || m.frames.length !== want) return null
  if (!m.frames.every((d) => typeof d === 'string' && d.length <= MAX_PATH && PATH.test(d))) return null
  const when = atoms(m.when ?? [])
  if (!when) return null
  const reward = m.reward === null || m.reward === undefined ? null
    : Number.isInteger(m.reward) && (m.reward as number) >= 0 && (m.reward as number) < MAX_REWARDS ? m.reward as number : -1
  if (reward === -1) return null
  return { id: m.id, role: m.role as Role, frames: m.frames as string[], when, reward }
}

/** The payload, checked, or null. */
export function sanitizeDrawing(raw: unknown): DrawingPayload | null {
  if (!raw || typeof raw !== 'object') return null
  const p = raw as Record<string, unknown>
  if (!['today', 'tasks', 'calendar', 'settings'].includes(p.view as string)) return null
  if (p.day !== null && (typeof p.day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(p.day))) return null
  if (typeof p.subject !== 'string' || !/^[\w-]{1,40}$/.test(p.subject)) return null
  if (p.theme !== 'light' && p.theme !== 'dark') return null
  const vb = p.viewBox
  if (!Array.isArray(vb) || vb.length !== 4 || !vb.every((n) => typeof n === 'number' && Number.isFinite(n))) return null
  if (!Array.isArray(p.marks) || p.marks.length > MAX_MARKS) return null
  const marks: DrawMark[] = []
  for (const m of p.marks) {
    const ok = mark(m, null)
    if (!ok) return null
    marks.push(ok)
  }
  let ambient: DrawingPayload['ambient'] = null
  if (p.ambient !== null && p.ambient !== undefined) {
    const a = p.ambient as Record<string, unknown>
    const when = atoms(a.when ?? [])
    if (!when || typeof a.seconds !== 'number' || !Array.isArray(a.frames) || a.frames.length > 24) return null
    const frames: DrawMark[][] = []
    for (const f of a.frames) {
      if (!Array.isArray(f)) return null
      const row: DrawMark[] = []
      for (const m of f) {
        const ok = mark(m, 1)
        if (!ok) return null
        row.push(ok)
      }
      frames.push(row)
    }
    ambient = { seconds: a.seconds, when, frames }
  }
  return {
    view: p.view as DrawingPayload['view'], day: p.day as string | null, subject: p.subject,
    theme: p.theme, viewBox: vb as DrawingPayload['viewBox'], marks, ambient,
  }
}

// ── fetching and the offline mirror ─────────────────────────────────────────
// One drawing per theme and view, for the day it was drawn for, so a reload
// (or a train tunnel) paints the day's picture at once and a new day is a miss.

const KEY = 'smylte-cache:drawing'

function keyFor(view: string, theme: string): string | null {
  const user = lastCacheUser()
  return user ? `${KEY}:${user}:${view}:${theme}` : null
}

export function readCachedDrawing(view: DrawingPayload['view'], day: string | null, theme: 'light' | 'dark'): DrawingPayload | null {
  const key = keyFor(view, theme)
  if (!key) return null
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const d = sanitizeDrawing(JSON.parse(raw))
    return d && d.day === day && d.theme === theme ? d : null
  } catch { return null }
}

export function cacheDrawing(d: DrawingPayload): void {
  const key = keyFor(d.view, d.theme)
  if (!key) return
  try { localStorage.setItem(key, JSON.stringify(d)) } catch { /* private mode / quota */ }
}

/** The drawing for `day` in `theme`, from the server, cached; null when there
 *  is none or it cannot be read. */
export async function fetchDrawing(view: DrawingPayload['view'], day: string, theme: 'light' | 'dark'): Promise<DrawingPayload | null> {
  try {
    const d = sanitizeDrawing(await api.drawing(view, day, theme))
    if (d) cacheDrawing(d)
    return d
  } catch {
    return null
  }
}
