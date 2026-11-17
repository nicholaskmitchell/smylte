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
// Motion is CSS only (fieldnotes.css), so the reduced-motion rule in
// ds/app-motion.css stops all of it: the line boil (three frames at 8fps, the
// one thing on screen that moves at rest), the focus loop at 6fps, and the
// reward's grow. An offscreen drawing stops boiling, and a hidden tab stops all
// CSS animation by itself.
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
      {/* The loop's keyframes are written for six frames (one second at 6fps). */}
      {amb && amb.frames.length === 6 && (
        <g className="dm-ambient" style={{ ['--n' as string]: amb.frames.length }}>
          {amb.frames.map((frame, f) => (
            <g key={f} className="amb" style={{ ['--k' as string]: f }}>
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
