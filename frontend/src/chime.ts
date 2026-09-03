// A short tone at the end of an interval, made rather than shipped.
//
// The app has no audio asset and deliberately gains none here: two sine notes
// through a gain envelope are the whole sound, so there is nothing to fetch,
// nothing to cache and nothing to keep in step with the appearance layer. Two
// notes rather than one because the two ends of a pomodoro are different news
// — a rising pair says the work is done, a falling pair says the rest is.
//
// Browsers refuse to start audio that no gesture asked for, so the context is
// created — and, crucially, RESUMED — inside the click that starts or resumes a
// session (`unlockChime`), and a chime that arrives before any gesture is a
// silent no-op rather than a console error. Every entry point is try/caught
// for the same reason: this is the one place the app talks to a device it
// cannot see, and a missing AudioContext (jsdom, an old kiosk browser, a
// privacy setting) must cost the surface nothing.

type Ctx = AudioContext

let ctx: Ctx | null = null

function context(): Ctx | null {
  if (ctx) return ctx
  const Ctor = (globalThis as { AudioContext?: new () => Ctx }).AudioContext
    ?? (globalThis as { webkitAudioContext?: new () => Ctx }).webkitAudioContext
  if (!Ctor) return null
  try { ctx = new Ctor() } catch { return null }
  return ctx
}

/** Call from a user gesture — the Start or Resume click — so the browser lets
 *  the page make a sound later, when no gesture is in flight. Idempotent. */
export function unlockChime(): void {
  const c = context()
  if (!c) return
  try { if (c.state === 'suspended') void c.resume() } catch { /* no audio */ }
}

/** Whether a chime could play right now: a context exists and is not
 *  suspended. The Settings row reads this to say "will not sound until you
 *  press Start" rather than promising a sound the browser will swallow. */
export function chimeReady(): boolean {
  try { return !!ctx && ctx.state === 'running' } catch { return false }
}

const NOTES: Record<'focus' | 'break', readonly [number, number]> = {
  focus: [660, 880],   // the interval is over: up
  break: [880, 660],   // the break is over: down, back to work
}

/** Two notes, ~0.5 s. `which` is the phase that just ENDED. */
export function playChime(which: 'focus' | 'break'): void {
  const c = context()
  if (!c || c.state !== 'running') return
  try {
    const t0 = c.currentTime
    NOTES[which].forEach((hz, i) => {
      const osc = c.createOscillator()
      const gain = c.createGain()
      osc.type = 'sine'
      osc.frequency.value = hz
      const start = t0 + i * 0.22
      // 0 → 0.2 → 0: a soft attack and a longer release, so it reads as a
      // bell rather than a buzzer, and never full scale — this is a nudge.
      gain.gain.setValueAtTime(0, start)
      gain.gain.linearRampToValueAtTime(0.2, start + 0.02)
      gain.gain.linearRampToValueAtTime(0, start + 0.28)
      osc.connect(gain)
      gain.connect(c.destination)
      osc.start(start)
      osc.stop(start + 0.3)
    })
  } catch { /* a device that cannot play is not an error the surface can act on */ }
}

/** Tests only: forget the context so a suite can install a fake. */
export function _resetChime(): void {
  ctx = null
}
