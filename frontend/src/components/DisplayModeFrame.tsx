// The frame display mode draws instead of the app's own (see displaymode.ts).
//
// Everything the views need is still here, because they are the app's real
// views: a tap checks off a task, a drag moves an event, and the writes go
// through the session like any other. What goes is the chrome around them —
// the top bar or the app sidebar, the tab strip and the settings gear — which
// on a screen across a room is only space taken from the day.
//
// What replaces it is one small button in the corner, faint so it does not
// compete with the content, and big enough for a finger. It opens a bar with
// the views on offer, full screen where the browser has it, and the way out.
// The bar folds itself away again after a while, because a display is usually
// left alone straight after someone has used it.
//
// The screen is kept awake for as long as this frame is up, which is what makes
// a tablet usable as a display at all. A browser releases the lock whenever the
// page is hidden, so it is asked for again on coming back. A browser without
// the API (an older iPad) gets nothing, and the person sets Auto-Lock to Never.

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useT } from '../i18n'
import { TAB_LABELS, type Tab } from '../tabs'
import { DISPLAY_TABS, canFullscreen, isFullscreen, toggleFullscreen } from '../displaymode'

/** How long the open bar waits for another tap before folding away. */
export const BAR_IDLE_MS = 10_000

export function DisplayModeFrame({ tab, onTab, onExit, children }: {
  tab: Tab
  onTab: (next: Tab) => void
  onExit: () => void
  children: ReactNode
}) {
  const tr = useT()
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState(() => isFullscreen())
  const [fullOk] = useState(() => canFullscreen())
  const idle = useRef<ReturnType<typeof setTimeout>>()

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
      <div className="views">{children}</div>
      {open ? (
        <div className="dmode-bar" role="toolbar" aria-label={tr('dmode.controls')}
          onPointerDown={poke}>
          {DISPLAY_TABS.map((t) => (
            <button key={t} className={`btn ghost dmode-bar__tab ${t === tab ? 'active' : ''}`}
              aria-pressed={t === tab}
              onClick={() => { onTab(t); poke() }}>
              {tr(TAB_LABELS[t])}
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
