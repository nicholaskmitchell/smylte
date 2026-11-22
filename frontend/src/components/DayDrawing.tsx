// The day's drawing, rendered: inline SVG from the server's marks (drawing.ts).
//
// The server sends every mark the picture could show, each with the condition
// it shows under; this decides which hold for the day as it is now and marks
// them `.on`. So a tick grows its fruit at once, an untick takes it away, and
// none of it waits on the network.
//
// React draws the picture once per drawing. A change of state does not
// re-render it: a layout effect evaluates each conditional mark and switches
// `.on` on the few whose answer changed, before the frame paints. A tick then
// costs a few dozen condition checks and a class or two, which keeps it inside
// the 2ms budget on slow hardware too.
//
// The line boil (three frames at 8fps, the one thing on screen that moves at
// rest) and the focus loop at 6fps are stepped by one clock per drawing, here:
// it writes the frame on the svg and fieldnotes.css shows that frame's paths.
// One clock rather than an animation on every path, because per-path
// animations left an instant at each frame change with no frame showing, and a
// repaint there drew the picture blank. The clock does not run under reduced
// motion (frame one holds), stops while the drawing is offscreen, and a hidden
// tab stops it by itself. The reward's grow and the conditions' fades stay CSS,
// so the reduced-motion rule in ds/app-motion.css stops them.
//
// `aria-hidden`: everything the drawing shows is also said in text beside it.
//
// A glow (light at night: the moon, a lamp, a lit window) is the sage wash with
// a soft edge. Each drawing carries one radial gradient of it, named for the
// instance, and hands it to CSS as --dm-glow; the colour stays a token.
import { memo, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import {
  evaluate, fetchDrawing, readCachedDrawing, type DayState, type DrawMark, type DrawingPayload,
} from '../drawing'
import { useThemeName } from '../hooks'
import { parseTime } from '../motion'

/** One mark, drawn once per drawing. A conditional mark is drawn without
 *  `.on`; the drawing's layout effect owns that class from then on. */
function Mark({ m, cond }: { m: DrawMark; cond?: number }) {
  const conditional = m.when.length > 0
  const cls = [
    'dm', `dm-${m.role}`,
    conditional ? (m.reward !== null ? 'dm-reward' : 'dm-cond') : 'on',
  ].filter(Boolean).join(' ')
  // A reward grows from its own anchor (the stalk, the line), in the
  // drawing's units, not from the middle of its box.
  const style: CSSProperties | undefined = m.origin
    ? { transformBox: 'view-box', transformOrigin: `${m.origin[0]}px ${m.origin[1]}px` }
    : undefined
  if (m.role === 'line' && m.frames.length === 3) {
    return (
      <g className={cls} data-c={cond} style={style}>
        <path className="boil f1" d={m.frames[0]} />
        <path className="boil f2" d={m.frames[1]} />
        <path className="boil f3" d={m.frames[2]} />
      </g>
    )
  }
  return <path className={cls} d={m.frames[0]} data-c={cond} style={style} />
}

const ROLES = ['wash', 'glow', 'accent', 'line'] as const

/** The whole picture for a drawing: every mark, in paint order (by role, as
 *  the server sends them), and the focus loop's frames. Memoised on the
 *  drawing alone, so a change of state never re-renders it. Each conditional
 *  mark carries its index into `cond` as `data-c`. */
const Picture = memo(function Picture({ drawing, cond }: { drawing: DrawingPayload; cond: DrawMark[] }) {
  const index = new Map(cond.map((m, i) => [m, i]))
  const amb = drawing.ambient
  return (
    <>
      {ROLES.map((role) => (
        <g key={role}>
          {drawing.marks.filter((m) => m.role === role).map((m) => <Mark key={m.id} m={m} cond={index.get(m)} />)}
        </g>
      ))}
      {/* The loop is stepped by the clock's data-amb (0-5) and six nth-child rules in
          fieldnotes.css, so it has at most six frames. */}
      {amb && amb.frames.length === 6 && (
        <g className="dm-ambient">
          {amb.frames.map((frame, f) => (
            <g key={f} className="amb">
              {frame.map((m) => <Mark key={m.id} m={m} />)}
            </g>
          ))}
        </g>
      )}
    </>
  )
})

export const DayDrawing = memo(function DayDrawing({ drawing, state, className = '' }: {
  drawing: DrawingPayload
  state: DayState
  className?: string
}) {
  const ref = useRef<SVGSVGElement>(null)

  // The drawing's one clock: it writes the boil's frame (data-frame, 1-3) and
  // the focus loop's (data-amb, 0-5) on the svg, and fieldnotes.css shows the
  // paths of that frame alone. It runs only while the drawing is on screen (a
  // drawing scrolled away costs nothing and holds its frame) and never under
  // reduced motion, where the attributes are absent and frame one shows.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const reduce = typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)') : null
    let onScreen = true
    let raf = 0
    let start = -1
    let cycle = 375
    let fps = 6
    let frame = ''
    let amb = ''
    const tick = (now: number) => {
      if (start < 0) start = now
      const elapsed = now - start
      const f = String(Math.floor(elapsed / (cycle / 3)) % 3 + 1)
      const a = String(Math.floor(elapsed * fps / 1000) % 6)
      if (f !== frame) { el.setAttribute('data-frame', f); frame = f }
      if (a !== amb) { el.setAttribute('data-amb', a); amb = a }
      raf = requestAnimationFrame(tick)
    }
    const update = () => {
      const still = !!reduce?.matches
      if (onScreen && !still && !raf) {
        // The tokens are the source of truth; 375ms and 6fps (their values in
        // ds/app-motion.css) only stand in when one is missing or unreadable.
        const cs = getComputedStyle(el)
        const c = parseTime(cs.getPropertyValue('--boil-cycle'))
        const r = Number.parseFloat(cs.getPropertyValue('--ambient-fps'))
        cycle = c > 0 ? c : 375
        fps = r > 0 ? r : 6
        start = -1
        raf = requestAnimationFrame(tick)
      } else if ((!onScreen || still) && raf) {
        cancelAnimationFrame(raf)
        raf = 0
      }
      if (still) {
        el.removeAttribute('data-frame')
        el.removeAttribute('data-amb')
        frame = ''
        amb = ''
      }
    }
    const io = typeof IntersectionObserver === 'function'
      ? new IntersectionObserver((entries) => {
        // The last entry is the current state: a quick scroll out and back can deliver both in one
        // callback.
        const e = entries[entries.length - 1]
        onScreen = e.isIntersecting
        if (onScreen) delete el.dataset.paused
        else el.dataset.paused = ''
        update()
      })
      : null
    io?.observe(el)
    reduce?.addEventListener('change', update)
    update()
    return () => {
      cancelAnimationFrame(raf)
      raf = 0
      io?.disconnect()
      reduce?.removeEventListener('change', update)
    }
  }, [])

  const cond = useMemo(() => drawing.marks.filter((m) => m.when.length > 0), [drawing])

  // The marks' elements, found once per drawing, and what each showed last.
  // A new drawing starts from nothing known, so every mark is set once.
  const shown = useRef<{ drawing: DrawingPayload | null; els: Element[]; on: boolean[]; amb: Element | null; ambOn: boolean | null }>(
    { drawing: null, els: [], on: [], amb: null, ambOn: null })
  useLayoutEffect(() => {
    const svg = ref.current
    if (!svg) return
    const s = shown.current
    if (s.drawing !== drawing) {
      const els: Element[] = []
      svg.querySelectorAll('[data-c]').forEach((el) => { els[Number(el.getAttribute('data-c'))] = el })
      shown.current = { drawing, els, on: [], amb: svg.querySelector('.dm-ambient'), ambOn: null }
    }
    const now = shown.current
    for (let i = 0; i < cond.length; i++) {
      const on = evaluate(cond[i].when, state)
      if (now.on[i] !== on) {
        now.els[i]?.classList.toggle('on', on)
        now.on[i] = on
      }
    }
    const ambOn = drawing.ambient ? evaluate(drawing.ambient.when, state) : false
    if (now.amb && now.ambOn !== ambOn) {
      now.amb.classList.toggle('on', ambOn)
      now.ambOn = ambOn
    }
  }, [drawing, cond, state])

  const glow = `dm-glow-${useId().replace(/[^\w-]/g, '')}`
  const hasGlow = useMemo(() => drawing.marks.some((m) => m.role === 'glow')
    || !!drawing.ambient?.frames.some((f) => f.some((m) => m.role === 'glow')), [drawing])
  const [x, y, w, h] = drawing.viewBox
  return (
    <svg ref={ref} className={`day-drawing ${className}`.trim()} viewBox={`${x} ${y} ${w} ${h}`}
      aria-hidden="true" focusable="false" data-subject={drawing.subject}
      style={hasGlow ? { ['--dm-glow' as string]: `url(#${glow})` } : undefined}>
      {hasGlow && (
        <defs>
          <radialGradient id={glow}>
            <stop className="dm-glow-stop" offset="0" />
            <stop className="dm-glow-stop" offset="0.45" />
            <stop className="dm-glow-stop dm-glow-edge" offset="1" />
          </radialGradient>
        </defs>
      )}
      <Picture drawing={drawing} cond={cond} />
    </svg>
  )
})

/**
 * The drawing for `view` on `day`, fetched once per day and theme and painted
 * from the offline mirror until it arrives, so a reload shows the day's
 * picture at once. Nothing is drawn until there is a drawing (or on a failed
 * read); the screen around it says everything the drawing would.
 */
export function ViewDrawing({ view, day, state, className }: {
  view: DrawingPayload['view']
  day: string
  state: DayState
  className?: string
}) {
  const theme = useThemeName()
  const [drawing, setDrawing] = useState<DrawingPayload | null>(
    () => readCachedDrawing(view, view === 'today' ? day : null, theme))
  useEffect(() => {
    let live = true
    const cached = readCachedDrawing(view, view === 'today' ? day : null, theme)
    setDrawing(cached)
    void fetchDrawing(view, day, theme).then((d) => { if (live && d) setDrawing(d) })
    return () => { live = false }
  }, [view, day, theme])
  if (!drawing) return null
  return <DayDrawing drawing={drawing} state={state} className={className} />
}
