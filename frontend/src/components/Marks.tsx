// Field notes' hand-drawn marks: the drawn checkbox and its tick, the wavy
// strike through a finished title, the active tab's underline, the tab icons and
// the add button's ink edge.
//
// Every mark here DECORATES markup that already exists rather than replacing
// it. The check is still `<button className="check" aria-pressed>`, the title
// is still `.today-title`, the tab is still `.tab` — the contracts the tests and
// the screen reader rely on are untouched, and each mark is `aria-hidden`
// inline SVG (the CSP refuses data-URI images, so it could not be a background).
//
// Under a preset the marks are not drawn: app.css hides them, and only
// fieldnotes.css, scoped to `[data-surface="app"]`, shows them. So Classic,
// Workspace and the Sep 2026 design keep their own check, line-through and tab.
//
// Geometry is on the design system's pen: a 24px grid (28px for the check),
// strokes set by --stroke-pen / --stroke-tick / --stroke-strike in CSS, round
// caps and joins, and each point a little off true — up to --wobble. Colour and
// motion are CSS too (fieldnotes.css); nothing here names a colour or a time.
import { useLayoutEffect, useRef, useState } from 'react'
import type { Tab } from '../tabs'

/** A small, stable hash: the same seed always draws the same hand. */
export function seedOf(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

// ── the check ──────────────────────────────────────────────────────────────
// Three hands for the frame and the tick, so a column of checkboxes reads as
// drawn one at a time rather than stamped. The tick overruns the frame's top
// corner, as a quick pen does.
const FRAMES = [
  'M5.2 4.6C10 4.1 18.4 4.3 23.1 5.2C23.8 10 23.6 18.3 22.9 23.2C18 23.7 9.8 23.9 4.9 23.1C4.3 18.4 4.4 9.6 5.2 4.6Z',
  'M4.8 5.1C9.9 4.4 18 4.6 23.3 4.8C23.5 10.1 23.9 18 23.1 22.9C18.2 23.5 10 23.4 5.1 23.4C4.6 18.1 4.2 10.2 4.8 5.1Z',
  'M5.4 4.9C10.4 4.2 18.2 4.1 22.8 4.7C23.6 9.8 23.4 18.4 23.2 23C18.1 23.9 10.1 23.6 4.7 22.8C4.5 18 4.6 10 5.4 4.9Z',
]
const TICKS = [
  'M8.6 14.6C10 15.8 11.4 17.6 12.4 19C14.6 14.4 18.6 9.2 23.8 5.8',
  'M8.9 14.2C10.2 15.5 11.6 17.3 12.6 18.6C14.9 14 18.9 9.4 23.6 6.2',
  'M8.4 14.9C9.9 16 11.2 17.8 12.2 19.3C14.4 14.6 18.4 9 23.9 5.5',
]

/** The drawn frame and tick inside a `.check` button. The tick draws itself
 *  when the button gets `.on` (fieldnotes.css); a check that mounts already on
 *  shows it finished. */
export function CheckInk({ seed = '' }: { seed?: string }) {
  const hand = seedOf(seed) % FRAMES.length
  return (
    <svg className="check-ink" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
      <path className="check-frame" d={FRAMES[hand]} />
      <path className="check-tick ink" pathLength={1} d={TICKS[hand]} />
    </svg>
  )
}

// ── the strike ─────────────────────────────────────────────────────────────

type Line = { x: number; y: number; w: number; h: number }

/** The boxes of `el`'s own text, one per line, relative to `el`. A title that
 *  wraps gets a strike per line, not one through the gap between them. */
function lineBoxes(el: HTMLElement, skip: Element): Line[] {
  const box = el.getBoundingClientRect()
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  const lines: Line[] = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (skip.contains(n) || !n.textContent?.trim() || n.parentElement?.closest('.chip')) continue
    const range = document.createRange()
    // jsdom has no layout, and no getClientRects on a Range: nothing to draw.
    if (typeof range.getClientRects !== 'function') return []
    range.selectNodeContents(n)
    for (const r of Array.from(range.getClientRects())) {
      if (r.width < 1) continue
      const same = lines.find((l) => Math.abs(l.y - (r.top - box.top)) < r.height / 2)
      if (same) {
        const right = Math.max(same.x + same.w, r.right - box.left)
        same.x = Math.min(same.x, r.left - box.left)
        same.w = right - same.x
      } else {
        lines.push({ x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height })
      }
    }
  }
  return lines
}

/** A wavy line across one line box, a little different each time. */
function wave(l: Line, seed: number): string {
  const y = l.y + l.h * 0.56
  const amp = 1.1
  const steps = Math.max(2, Math.round(l.w / 18))
  const step = (l.w + 4) / steps
  let d = `M${(l.x - 2).toFixed(1)} ${y.toFixed(1)}`
  for (let i = 0; i < steps; i++) {
    const x0 = l.x - 2 + i * step
    const lift = ((seed >> (i % 16)) & 1 ? 1 : -1) * amp * (0.7 + ((seed >> ((i + 5) % 16)) & 3) / 10)
    d += ` C${(x0 + step / 3).toFixed(1)} ${(y - lift).toFixed(1)} ${(x0 + (2 * step) / 3).toFixed(1)} ${(y + lift).toFixed(1)} ${(x0 + step).toFixed(1)} ${y.toFixed(1)}`
  }
  return d
}

/**
 * The wavy coral-ink strike through a finished title. Rendered INSIDE the
 * title element, which it measures: one stroke per line of text. When `on`
 * turns true it measures, draws the strokes undrawn, and draws them on in the
 * next frame; when it turns false they draw back off. A title that mounts
 * already finished shows its strike at once. Renders nothing measurable where
 * there is no layout (jsdom), so text and structure are unchanged for tests.
 */
export function StrikeInk({ on, seed = '' }: { on: boolean; seed?: string }) {
  const ref = useRef<SVGSVGElement>(null)
  const mounted = useRef(false)
  const [lines, setLines] = useState<Line[]>([])
  const [size, setSize] = useState<[number, number]>([0, 0])
  const [armed, setArmed] = useState(on)

  useLayoutEffect(() => {
    const svg = ref.current
    const host = svg?.parentElement
    if (!svg || !host) return
    const first = !mounted.current
    mounted.current = true
    if (!on) { setArmed(false); return }
    const measure = () => {
      const b = host.getBoundingClientRect()
      setSize([b.width, b.height])
      setLines(lineBoxes(host, svg))
    }
    measure()
    let frame = 0
    if (first) setArmed(true)
    else {
      setArmed(false)
      frame = requestAnimationFrame(() => { frame = requestAnimationFrame(() => setArmed(true)) })
    }
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null
    ro?.observe(host)
    return () => { cancelAnimationFrame(frame); ro?.disconnect() }
  }, [on])

  const s = seedOf(seed)
  return (
    <svg ref={ref} className={`strike-ink ${armed && on ? 'on' : ''}`} aria-hidden="true" focusable="false"
      width={size[0] || undefined} height={size[1] || undefined}
      viewBox={size[0] ? `0 0 ${size[0].toFixed(1)} ${size[1].toFixed(1)}` : undefined}>
      {lines.map((l, i) => (
        <path key={i} pathLength={1} d={wave(l, s + i * 7919)} style={{ ['--line' as string]: i }} />
      ))}
    </svg>
  )
}

// ── tabs ───────────────────────────────────────────────────────────────────

/** The drawn underline under the active tab. Present on every tab so that
 *  moving between them draws one on and the other off. */
export function TabInk() {
  return (
    <svg className="tab-ink" viewBox="0 0 34 6" aria-hidden="true" focusable="false">
      <path className="ink" pathLength={1} d="M2 4C9 2.4 18 2 32 3.2" />
    </svg>
  )
}

const TAB_ICON: Record<Tab, string[]> = {
  // A sun for the day.
  today: [
    'M12.1 8.1c2.2-.1 3.9 1.7 3.8 3.9 0 2.1-1.8 3.9-3.9 3.8-2.2.1-3.9-1.7-3.8-3.8-.1-2.2 1.7-4 3.9-3.9z',
    'M12 3.4v2M12.1 18.6v2M3.4 12.1h2M18.6 11.9h2M5.9 6l1.4 1.3M16.8 16.7l1.3 1.4M5.8 18l1.5-1.3M16.7 7.2l1.4-1.3',
  ],
  // A house.
  home: [
    'M4.4 11.4c2.4-2.3 4.9-4.5 7.5-6.7 2.6 2.1 5.1 4.4 7.6 6.8',
    'M6.4 10c-.2 3.4-.1 6.8.1 10.1 3.7.2 7.4.2 11.1 0 .2-3.3.2-6.7 0-10.1',
    'M10.1 20.1c-.1-1.9-.1-3.8.1-5.5 1.3-.2 2.6-.1 3.8 0 .1 1.8.1 3.7 0 5.5',
  ],
  // Two boxes and two lines: a list.
  tasks: [
    'M4.3 5.2c1.4-.2 3.6-.1 4.9.1.2 1.4.1 3.5-.1 4.9-1.4.2-3.5.2-4.9-.1-.2-1.3-.1-3.6.1-4.9z',
    'M12.6 7.6c2.2-.2 5-.1 7.1.2',
    'M4.4 13.8c1.4-.2 3.5-.2 4.9.1.2 1.4.1 3.5-.1 4.9-1.4.2-3.5.1-4.9-.1-.2-1.4-.1-3.5.1-4.9z',
    'M12.6 16.3c2.1-.2 5.1 0 7.1.1',
  ],
  // A calendar page.
  calendar: [
    'M4.2 6.3c5.1-.5 10.6-.4 15.7.1.4 4.3.3 9.4-.1 13.5-5 .4-10.6.5-15.6 0-.4-4.3-.4-9.3 0-13.6z',
    'M8 3.6l.1 3.6M16 3.5l-.1 3.7M4.4 10.6c5-.3 10.3-.2 15.3 0',
  ],
}

/** A view's drawn icon, above its label in the phone's tab bar. */
export function TabIcon({ tab }: { tab: Tab }) {
  return (
    <svg className="tab-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {TAB_ICON[tab].map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

/** The add button's cross and its ink edge: the coral fill is 2.5:1 on light
 *  paper, so the button's shape is carried by a drawn ink outline (12.9:1). */
export function AddInk() {
  return (
    <svg className="add-ink" viewBox="0 0 56 56" aria-hidden="true" focusable="false">
      <path className="add-edge" d="M14.2 2.6C23 2.1 33.4 2.2 41.6 2.7C49.6 3.4 53.2 6.9 53.4 14.6C53.9 23.3 53.8 33.1 53.2 41.8C52.6 49.7 49 53.1 41.3 53.4C32.8 53.9 22.9 53.8 14.4 53.2C6.5 52.6 3 49.1 2.7 41.5C2.2 32.9 2.3 23.1 2.8 14.4C3.3 6.6 6.6 3.1 14.2 2.6Z" />
      <path className="add-cross" d="M28.4 17.2c-.4 7.4-.3 14.7.1 21.9M17.3 28.1c7.3-.4 14.6-.3 21.7.3" />
    </svg>
  )
}
