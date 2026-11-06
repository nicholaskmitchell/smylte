// Display mode: the desk unit's faces on this device, signed in, with touch
// (see displaymode.ts for why it is signed in rather than paired).
//
// The faces are DisplayView's own — the month, habits + today, now + next — so
// an iPad on a counter looks like the panel on the desk. The frame comes from
// the session-backed preview route with refs, which a token never gets, and
// the actions handed to the faces are what turn them from a poster into
// something a finger can use: a tap ticks a row, a tap on the current item
// finishes it, and a chip dragged to another day moves the event. Every write
// is the app's ordinary one, and the frame is fetched again straight after,
// so the face shows what the server now holds rather than a guess at it.
//
// It refreshes on a minute's clock and whenever the app hears of a change
// (`rev`, the same counter the views refetch on), so a task finished on a phone
// leaves the wall as quickly as it leaves any other screen.
//
// One small button in the corner, faint so it does not compete with the day,
// opens a bar with the three faces, full screen where the browser has it, and
// the way out. The bar folds itself away again after a while. The screen is
// kept awake for as long as this is up; a browser releases the lock whenever
// the page is hidden, so it is asked for again on coming back.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AuthError, api, type DisplayFrame, type DisplayMode } from '../api'
import { useT } from '../i18n'
import { makeGuard } from '../util'
import { daysBetween, shiftIso } from '../calendar'
import { DISPLAY_MODES, canFullscreen, isFullscreen, toggleFullscreen } from '../displaymode'
import { DisplayActionsProvider, DisplayFaces, type DisplayActions } from './DisplayView'

/** How long the open bar waits for another tap before folding away. */
export const BAR_IDLE_MS = 10_000

/** How often the face is fetched when nothing has said it changed. A minute,
 *  because the clock-driven parts (the day rolling over, a preview turning
 *  into a plan) have no event of their own. */
export const REFRESH_MS = 60_000

/** How old the face may get before it says so. Three missed refreshes, so one
 *  dropped fetch on household wifi says nothing, while a tablet that lost the
 *  network overnight does not go on showing yesterday as though it were today. */
export const STALE_AFTER_MS = 3 * REFRESH_MS

const MODE_LABELS: Record<DisplayMode, string> = {
  calendar: 'disp.mode.calendar',
  habits: 'disp.mode.habits',
  now: 'disp.mode.now',
}

export function DisplayModeFrame({ mode, onMode, onExit, onExpire, rev = 0 }: {
  mode: DisplayMode
  onMode: (next: DisplayMode) => void
  onExit: () => void
  onExpire: () => void
  /** Bumped by App on every change the server announces. */
  rev?: number
}) {
  const tr = useT()
  const guard = useMemo(() => makeGuard(onExpire), [onExpire])
  const [frame, setFrame] = useState<DisplayFrame | null>(null)
  const [fetchedAt, setFetchedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState(() => isFullscreen())
  const [fullOk] = useState(() => canFullscreen())
  const idle = useRef<ReturnType<typeof setTimeout>>()
  // Which request is the latest, so a slow answer for the face that was just
  // switched away from cannot land on top of the new one.
  const seq = useRef(0)

  const load = useCallback(async () => {
    const mine = ++seq.current
    try {
      const next = await api.displayPreview(mode, 'Smylte')
      if (mine !== seq.current) return
      // The face's own heading, in place of a paired display's name: the day
      // faces are about today, and the month says which month it is already.
      const name = mode === 'calendar' ? '' : tr('tab.today')
      setFrame({ ...next, display: { ...next.display, name } })
      setFetchedAt(Date.now())
    } catch (e) {
      // Not through `guard`: a dropped fetch on household wifi is not worth a
      // toast on a wall, and the next tick tries again. An ended session is.
      if (e instanceof AuthError) onExpire()
    }
  }, [mode, tr, onExpire])

  // The latest `load`, for the writes to refetch with when they settle: the
  // one they closed over may be for the face that has since been switched
  // away from, and its answer would be drawn under the new face's name.
  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => { void load() }, [load, rev])
  useEffect(() => {
    const id = setInterval(() => { void load() }, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), REFRESH_MS)
    return () => clearInterval(id)
  }, [])
  const stale = fetchedAt !== null && now - fetchedAt > STALE_AFTER_MS

  // What is being written, so a second tap on the same row before the first
  // has landed (and the face has caught up) is not a second write.
  const busy = useRef(new Set<string>())
  const once = (key: string, write: () => Promise<unknown>) => {
    if (busy.current.has(key)) return
    busy.current.add(key)
    void (async () => {
      try { await write() } finally {
        busy.current.delete(key)
        void loadRef.current()
      }
    })()
  }

  const day = frame?.day
  const actions = useMemo<DisplayActions>(() => ({
    toggleRow: (ref, done) => {
      if (ref.kind === 'task' && ref.list && ref.uid) {
        once(`task:${ref.list}:${ref.uid}`,
          () => guard(() => api.complete(ref.list!, ref.uid!, done)))
      } else if (ref.entry && day) {
        once(`entry:${ref.entry}`,
          () => guard(() => api.patchDayEntry(day, ref.entry!, { done })))
      }
    },
    moveEvent: (ref, fromDay, toDay) => {
      const delta = daysBetween(fromDay, toDay)
      if (!delta || !ref.start) return
      const body: Record<string, unknown> = { start: shiftIso(ref.start, delta) }
      if (ref.end) body.end = shiftIso(ref.end, delta)
      once(`event:${ref.calendar}:${ref.uid}`,
        () => guard(() => api.patchEvent(ref.calendar, ref.uid, body)))
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [guard, day])

  // Restarted by every tap on the bar, so it folds only once it is left alone.
  const poke = () => {
    clearTimeout(idle.current)
    idle.current = setTimeout(() => setOpen(false), BAR_IDLE_MS)
  }
  useEffect(() => {
    if (open) poke()
    else clearTimeout(idle.current)
    return () => clearTimeout(idle.current)
  }, [open])

  useEffect(() => {
    const sync = () => setFull(isFullscreen())
    document.addEventListener('fullscreenchange', sync)
    document.addEventListener('webkitfullscreenchange', sync)
    return () => {
      document.removeEventListener('fullscreenchange', sync)
      document.removeEventListener('webkitfullscreenchange', sync)
    }
  }, [])

  // Keep the screen on. Same shape as the share page's switch, without the
  // switch: a display that goes dark after two minutes is not a display.
  useEffect(() => {
    if (typeof navigator === 'undefined' || !('wakeLock' in navigator)) return
    let on = true
    let sentinel: WakeLockSentinel | null = null
    const acquire = async () => {
      if (sentinel && !sentinel.released) return
      try {
        const got = await navigator.wakeLock.request('screen')
        if (!on) { void got.release(); return }
        sentinel = got
      } catch {
        // Refused (low battery, a policy). Tried again on the next return to
        // the page; there is nobody to tell in the meantime.
      }
    }
    const again = () => { if (document.visibilityState === 'visible') void acquire() }
    document.addEventListener('visibilitychange', again)
    void acquire()
    return () => {
      on = false
      document.removeEventListener('visibilitychange', again)
      void sentinel?.release()
    }
  }, [])

  return (
    <div className="dmode">
      <div className="display display--color display--touch" data-mode={mode}>
        {frame ? (
          <DisplayActionsProvider value={actions}>
            <DisplayFaces frame={frame} />
          </DisplayActionsProvider>
        ) : (
          <div className="display__booting" aria-hidden="true" />
        )}
        {stale ? <div className="display-label display__stale">{tr('display.stale')}</div> : null}
      </div>
      {open ? (
        <div className="dmode-bar" role="toolbar" aria-label={tr('dmode.controls')}
          onPointerDown={poke}>
          {DISPLAY_MODES.map((m) => (
            <button key={m} className={`btn ghost dmode-bar__tab ${m === mode ? 'active' : ''}`}
              aria-pressed={m === mode}
              onClick={() => { onMode(m); poke() }}>
              {tr(MODE_LABELS[m])}
            </button>
          ))}
          <span className="dmode-bar__gap" />
          {fullOk && (
            <button className="btn ghost" aria-pressed={full}
              onClick={() => { void toggleFullscreen(); poke() }}>
              {full ? tr('dmode.leaveFullscreen') : tr('dmode.fullscreen')}
            </button>
          )}
          <button className="btn ghost" onClick={() => {
            if (isFullscreen()) void toggleFullscreen()
            onExit()
          }}>
            {tr('dmode.exit')}
          </button>
          <button className="icon-btn dmode-bar__close" aria-label={tr('dmode.hideControls')}
            onClick={() => setOpen(false)}>✕</button>
        </div>
      ) : (
        <button className="dmode-handle" aria-label={tr('dmode.controls')}
          aria-expanded={false} onClick={() => setOpen(true)}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
            <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" />
            <circle cx="19" cy="12" r="1.8" />
          </svg>
        </button>
      )}
    </div>
  )
}
