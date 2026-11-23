// The Calendar's ink under Field notes (the month as a page): the month's grid
// ruled by hand, the days already gone crossed off, today circled in coral, the
// phone's chosen day boxed in pen, and the month's name underlined.
//
// Like Marks.tsx, every mark here DECORATES markup that already says it all:
// each cell keeps its label and today carries aria-current="date", so every
// mark is aria-hidden inline SVG. Each is seeded (the same month always draws
// the same hand) and static: nothing here animates, so reduced motion needs
// nothing. Colour, width and caps are CSS (fieldnotes.css, "Calendar · the
// month as a page"); nothing here names a colour or a time.
//
// The grid's lines are ONE svg laid over `.cal-grid` (its last child, absolutely
// positioned), not a box per cell: a day cell must stay `position: static`
// (calendar.browser.test.tsx), and one memoised overlay costs a few hundredths
// of a millisecond on a re-render that leaves the month alone. It measures the
// rendered month (a layout effect, then a ResizeObserver on the grid, the
// weekday row and the first cell of each week) because a row's height comes from
// what the busiest day in it holds.
import { memo, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { seedOf } from './Marks'

/** A seeded stream of numbers in [0, 1) (mulberry32). */
export type Rand = () => number

export function rand(seed: number): Rand {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const u = (r: Rand, lo: number, hi: number) => lo + (hi - lo) * r()
const f = (v: number) => (Math.round(v * 10) / 10).toString()
type Pt = [number, number]

/** A smooth open path through the points: Catmull-Rom as cubic Béziers, as
 *  the drawing engine's pen draws (pen.to_d). */
function smooth(pts: Pt[]): string {
  const n = pts.length
  const at = (i: number) => pts[Math.min(Math.max(i, 0), n - 1)]
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`
  for (let i = 0; i < n - 1; i++) {
    const p0 = at(i - 1), p1 = at(i), p2 = at(i + 1), p3 = at(i + 2)
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C${f(c1x)} ${f(c1y)} ${f(c2x)} ${f(c2y)} ${f(p2[0])} ${f(p2[1])}`
  }
  return d
}

export type RuleOpts = { over0?: number; over1?: number; bow?: number; step?: number }

/** A line ruled by hand from (x0, y0) to (x1, y1): true to the ruler but for a
 *  faint bow and tremor, and running a little past where it was meant to stop
 *  (a negative overrun stops short). '' for a line of no length. */
export function ruled(x0: number, y0: number, x1: number, y1: number, r: Rand, o: RuleOpts = {}): string {
  const over0 = o.over0 ?? u(r, 0.5, 3.5)
  const over1 = o.over1 ?? u(r, 0.5, 3.5)
  const dx = x1 - x0, dy = y1 - y0
  const len = Math.hypot(dx, dy)
  if (!(len > 0)) return ''
  const ux = dx / len, uy = dy / len, nx = -uy, ny = ux
  const ax = x0 - ux * over0, ay = y0 - uy * over0
  const bx = x1 + ux * over1, by = y1 + uy * over1
  const L = len + over0 + over1
  const n = Math.max(2, Math.ceil(L / (o.step ?? 36)))
  const bow = (r() < 0.5 ? -1 : 1) * Math.min(o.bow ?? 1.3, 0.008 * L)
  const tilt = u(r, -0.35, 0.35)
  const pts: Pt[] = []
  for (let i = 0; i <= n; i++) {
    const t = i / n
    const off = bow * Math.sin(Math.PI * t) + tilt * (2 * t - 1) + (i > 0 && i < n ? u(r, -0.3, 0.3) : 0)
    pts.push([ax + (bx - ax) * t + nx * off, ay + (by - ay) * t + ny * off])
  }
  return smooth(pts)
}

/** A date circled in one stroke: it starts upper left and runs on past its
 *  start, a little wider on the way round, as a quick pen does. */
export function circled(cx: number, cy: number, rx: number, ry: number, r: Rand): string {
  const start = u(r, -2.7, -2.1), sweep = 2 * Math.PI + u(r, 0.45, 0.7), n = 16
  const rot = u(r, -0.12, 0.06)
  const pts: Pt[] = []
  for (let i = 0; i <= n; i++) {
    const a = start + (sweep * i) / n
    const k = 1 + u(r, -0.035, 0.035) + 0.09 * (i / n)
    const x = rx * k * Math.cos(a), y = ry * k * Math.sin(a)
    pts.push([cx + x * Math.cos(rot) - y * Math.sin(rot), cy + x * Math.sin(rot) + y * Math.cos(rot)])
  }
  return smooth(pts)
}

/** A box drawn by hand: four ruled strokes that overrun their corners. */
export function box(x0: number, y0: number, x1: number, y1: number, r: Rand): string {
  const o = (): RuleOpts => ({ over0: u(r, -0.5, 2), over1: u(r, 0.5, 2.5), bow: 0.6, step: 20 })
  return [ruled(x0, y0, x1, y0, r, o()), ruled(x1, y0, x1, y1, r, o()),
    ruled(x1, y1, x0, y1, r, o()), ruled(x0, y1, x0, y0, r, o())].join(' ')
}

/** Where the month grid's lines fall, in px from the grid's padding box (where
 *  an absolutely positioned child's 0, 0 is). Each line sits on the middle of
 *  the 1px border it stands in for. */
export type GridGeo = {
  w: number
  h: number
  /** The six lines between the seven columns. */
  xs: number[]
  /** Eight: the top edge, under the weekday row, and under each of the six weeks. */
  ys: number[]
  /** The phone's chosen day, [x0, y0, x1, y1], or null. */
  focus: [number, number, number, number] | null
}

export type InkPath = { cls: string; d: string }

/** The grid's strokes for `g`, in a fixed order from one seeded hand: six
 *  columns, eight rows (the first and last the page's heavier frame), and the
 *  chosen day's box with a hand of its own. */
export function gridPaths(g: GridGeo, seed: string, focusSeed: string | null): InkPath[] {
  const r = rand(seedOf(seed))
  const top = g.ys[0], bottom = g.ys[g.ys.length - 1]
  const out: InkPath[] = []
  for (const x of g.xs) {
    out.push({ cls: 'rule v', d: ruled(x, top, x, bottom, r, { over0: u(r, 0.5, 3), over1: u(r, 0.5, 3) }) })
  }
  g.ys.forEach((y, i) => {
    const edge = i === 0 || i === g.ys.length - 1
    out.push({
      cls: edge ? 'rule h edge' : 'rule h',
      d: ruled(-0.5, y, g.w, y, r, { over0: u(r, -1, 2), over1: u(r, -1, 2) }),
    })
  })
  if (g.focus && focusSeed) {
    const [x0, y0, x1, y1] = g.focus
    out.push({ cls: 'focus', d: box(x0 + 4, y0 + 4, x1 - 5, y1 - 5, rand(seedOf(focusSeed))) })
  }
  return out
}

const tenth = (v: number) => Math.round(v * 10) / 10

/** The rendered month's geometry, or null where nothing is laid out (jsdom, a
 *  hidden pane) or the grid is not the 42 days it always is. */
function measureGrid(grid: HTMLElement, focus: string | null): GridGeo | null {
  const cells = grid.querySelectorAll<HTMLElement>(':scope > .cal-cell')
  const w = grid.clientWidth, h = grid.clientHeight
  if (cells.length !== 42 || w <= 0 || h <= 0) return null
  const g = grid.getBoundingClientRect()
  const ox = g.left + grid.clientLeft, oy = g.top + grid.clientTop
  const rect = (el: Element) => el.getBoundingClientRect()
  const xs = [0, 1, 2, 3, 4, 5].map((c) => tenth(rect(cells[c]).right - ox - 0.5))
  const ys = [-0.5, tenth(rect(cells[0]).top - oy - 0.5),
    ...[0, 1, 2, 3, 4, 5].map((k) => tenth(rect(cells[k * 7]).bottom - oy - 0.5))]
  let at: GridGeo['focus'] = null
  if (focus) {
    const el = grid.querySelector(`:scope > .cal-cell[data-day="${focus}"]`)
    if (el) {
      const b = rect(el)
      at = [tenth(b.left - ox), tenth(b.top - oy), tenth(b.right - ox), tenth(b.bottom - oy)]
    }
  }
  return { w: tenth(w), h: tenth(h), xs, ys, focus: at }
}

/** The month's ruled grid. Render it as the LAST child of `.cal-grid`.
 *  `seed` names the month (the same month draws the same hand); `focus` is the
 *  phone's chosen day, boxed in pen, or null. */
export const GridInk = memo(function GridInk({ seed, focus }: { seed: string; focus: string | null }) {
  const ref = useRef<SVGSVGElement>(null)
  const [geo, setGeo] = useState<GridGeo | null>(null)
  useLayoutEffect(() => {
    const grid = ref.current?.parentElement
    if (!grid) return
    const measure = () => {
      const next = measureGrid(grid, focus)
      setGeo((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next))
    }
    measure()
    if (typeof ResizeObserver !== 'function') return
    // The grid's own box answers a change of width; the weekday row and the
    // first day of each week answer a row that grew or shrank with what it
    // holds, which need not change the grid's height at all.
    const ro = new ResizeObserver(measure)
    ro.observe(grid)
    const dow = grid.querySelector(':scope > .cal-dow')
    if (dow) ro.observe(dow)
    const cells = grid.querySelectorAll(':scope > .cal-cell')
    for (const i of [0, 7, 14, 21, 28, 35]) if (cells[i]) ro.observe(cells[i])
    return () => ro.disconnect()
  }, [seed, focus])
  const paths = useMemo(
    () => (geo ? gridPaths(geo, seed, focus ? `focus|${focus}` : null) : []), [geo, seed, focus])
  return (
    <svg ref={ref} className="grid-ink" aria-hidden="true" focusable="false"
      width={geo ? geo.w : undefined} height={geo ? geo.h : undefined}
      viewBox={geo ? `0 0 ${geo.w} ${geo.h}` : undefined}>
      {paths.map((p, i) => <path key={i} className={p.cls} d={p.d} />)}
    </svg>
  )
})

/** Today's date circled in coral: inside today's `.daynum`, stretched round it. */
export const TodayInk = memo(function TodayInk({ day }: { day: string }) {
  const d = useMemo(() => circled(20, 14, 16, 10.5, rand(seedOf(`today|${day}`))), [day])
  return (
    <svg className="today-ink" viewBox="0 0 40 28" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <path d={d} vectorEffect="non-scaling-stroke" />
    </svg>
  )
})

/** A day already gone, crossed off with one faint stroke: inside its `.daynum`. */
export const CrossInk = memo(function CrossInk({ day }: { day: string }) {
  const d = useMemo(() => {
    const r = rand(seedOf(`cross|${day}`))
    return ruled(6 + u(r, -1, 1), 19 + u(r, -1, 1), 24 + u(r, -1, 1), 5 + u(r, -1, 1), r,
      { over0: 0.5, over1: 1, bow: 0.8, step: 8 })
  }, [day])
  return (
    <svg className="cross-ink" viewBox="0 0 30 24" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <path d={d} vectorEffect="non-scaling-stroke" />
    </svg>
  )
})

/** The coral line under the month's name: inside `.cal-month`. */
export function MonthInk() {
  return (
    <svg className="month-ink" viewBox="0 0 100 9" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <path d="M1 6.2C18 4.6 42 3.6 66 4.1C80 4.4 90 5 99 3.4" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
