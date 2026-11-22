// The motion tokens (ds/app-motion.css), read where a script has to wait for
// what the stylesheet draws.

/** A CSS time token in milliseconds: `.5s` is 500 and `60ms` is 60. NaN when the
 *  token is absent (a preset declares none of the ink tokens) or unreadable. */
export function parseTime(v: string): number {
  const m = /^(\d*\.?\d+)(ms|s)$/.exec(v.trim())
  return m ? Number(m[1]) * (m[2] === 's' ? 1000 : 1) : Number.NaN
}

/**
 * How long a row ticked in Tasks stays where it is, and how long it then takes
 * to leave, in milliseconds.
 *
 * `ink` is the tick and strike drawing in full (fieldnotes.css: the strike's
 * line n starts `--stagger` × (2 + n) after the tick and draws over
 * `--dur-stroke`; four staggers is the third line of a title that wraps), then a
 * beat of `--dur` so the finished mark is seen. `leave` is `--dur-slow`, the
 * design system's enter/exit for rows. At the shipped tokens that is 980 and 450.
 *
 * Null when there is nothing to wait for: under a preset, which has no ink
 * tokens, and under reduced motion, which sets every token to zero.
 */
export function tickExit(root: Element = document.documentElement): { ink: number; leave: number } | null {
  const cs = getComputedStyle(root)
  const stagger = parseTime(cs.getPropertyValue('--stagger'))
  const stroke = parseTime(cs.getPropertyValue('--dur-stroke'))
  const beat = parseTime(cs.getPropertyValue('--dur'))
  const leave = parseTime(cs.getPropertyValue('--dur-slow'))
  if (![stagger, stroke, beat, leave].every(Number.isFinite)) return null
  const ink = 4 * stagger + stroke + beat
  return ink > 0 ? { ink, leave } : null
}
