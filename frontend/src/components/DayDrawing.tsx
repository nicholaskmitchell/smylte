// The day's drawing, rendered: inline SVG from the server's marks (drawing.ts).
//
// The server sends every mark the picture could show, each with the condition
// it shows under; this decides which hold for the day as it is now and marks
// them `.on`. So a tick grows its fruit at once, an untick takes it away, and
// none of it waits on the network.
//
// Motion is CSS only (fieldnotes.css), so the reduced-motion rule in
// ds/app-motion.css stops all of it: the line boil (three frames at 8fps, the
// one thing on screen that moves at rest), the focus loop at 6fps, and the
// reward's grow. An offscreen drawing stops boiling, and a hidden tab stops all
// CSS animation by itself.
//
// `aria-hidden`: everything the drawing shows is also said in text beside it.
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import {
  evaluate, fetchDrawing, readCachedDrawing, type DayState, type DrawMark, type DrawingPayload,
} from '../drawing'
import { useThemeName } from '../hooks'

/** One mark. Memoised on the mark (the same object for the life of a drawing)
 *  and on whether it is showing, so a tick re-renders only the marks it turns
 *  on or off, not the whole picture. */
const Mark = memo(function Mark({ m, on }: { m: DrawMark; on: boolean }) {
  const conditional = m.when.length > 0
  const cls = [
    'dm', `dm-${m.role}`,
    conditional ? (m.reward !== null ? 'dm-reward' : 'dm-cond') : '',
    on ? 'on' : '',
  ].filter(Boolean).join(' ')
  if (m.role === 'line' && m.frames.length === 3) {
    return (
      <g className={cls}>
        <path className="boil f1" d={m.frames[0]} />
        <path className="boil f2" d={m.frames[1]} />
        <path className="boil f3" d={m.frames[2]} />
      </g>
    )
  }
  return <path className={cls} d={m.frames[0]} />
})

/** The marks that show whatever the day: drawn once per drawing and never
 *  re-rendered by a state change. */
const Still = memo(function Still({ marks }: { marks: DrawMark[] }) {
  return <>{marks.map((m) => <Mark key={m.id} m={m} on />)}</>
})

const ROLES = ['wash', 'accent', 'line'] as const

/** The focus loop's frames, drawn once per drawing; only its `.on` moves. */
const Ambient = memo(function Ambient({ frames }: { frames: DrawMark[][] }) {
  return (
    <>
      {frames.map((frame, f) => (
        <g key={f} className="amb" style={{ ['--k' as string]: f }}>
          {frame.map((m) => <Mark key={m.id} m={m} on />)}
        </g>
      ))}
    </>
  )
})

export const DayDrawing = memo(function DayDrawing({ drawing, state, className = '' }: {
  drawing: DrawingPayload
  state: DayState
  className?: string
}) {
  const ref = useRef<SVGSVGElement>(null)

  // Boil only while on screen. A drawing scrolled away costs nothing.
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver !== 'function') return
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) delete el.dataset.paused
      else el.dataset.paused = ''
    })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // Paint order is by role (the server sends them so), and within a role the
  // marks that always show are one memoised layer: a tick touches only the
  // handful of marks that have a condition.
  const layers = useMemo(() => ROLES.map((role) => {
    const of = drawing.marks.filter((m) => m.role === role)
    return { role, still: of.filter((m) => m.when.length === 0), cond: of.filter((m) => m.when.length > 0) }
  }), [drawing])
  const amb = drawing.ambient
  const ambOn = amb ? evaluate(amb.when, state) : false
  const [x, y, w, h] = drawing.viewBox
  return (
    <svg ref={ref} className={`day-drawing ${className}`.trim()} viewBox={`${x} ${y} ${w} ${h}`}
      aria-hidden="true" focusable="false" data-subject={drawing.subject}>
      {layers.map((l) => (
        <g key={l.role}>
          <Still marks={l.still} />
          {l.cond.map((m) => <Mark key={m.id} m={m} on={evaluate(m.when, state)} />)}
        </g>
      ))}
      {/* The loop's keyframes are written for six frames (one second at 6fps). */}
      {amb && amb.frames.length === 6 && (
        <g className={`dm-ambient ${ambOn ? 'on' : ''}`.trim()}
          style={{ ['--n' as string]: amb.frames.length }}>
          <Ambient frames={amb.frames} />
        </g>
      )}
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
