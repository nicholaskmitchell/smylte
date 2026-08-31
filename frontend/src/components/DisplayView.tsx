import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, type DisplayFrame, type DisplayItem, type DisplaySource } from '../api'

// The page at /display/<token>: a screen on a wall.
//
// Standalone by design, exactly as BookingPage is: no session, no SSE, no
// imports from the authed shell. It also takes NO INPUT — there is nothing to
// click, nothing focusable and no keyboard handler anywhere below. That is not
// an oversight to be filled in later; it is the specification. A passive display
// that could be tapped would be a bad app, and the thing it would most likely be
// tapped by is a cleaning cloth.
//
// Nothing here formats a date, a month or a clock. The frame arrives with every
// string already rendered in the owner's language and clock setting, because the
// same frame is rasterized server-side for panels with no browser, and two
// formatters would drift. See backend tasksd/display/frame.py.

// How long a fetch may hang before the timer gives up on it. A wall panel is
// usually on wifi at the edge of its range, and a half-open socket that never
// settles would stop the polling loop forever — the screen would sit there
// showing Tuesday until somebody power-cycled it.
const FETCH_TIMEOUT_MS = 20_000

// How long a frame may be stale before the screen says so. Deliberately several
// polls rather than one: a single missed fetch is normal on household wifi and
// nobody needs to be told about it, while twenty minutes of silence means the
// screen is lying about the day. Real, but quiet — a hairline strip, not a
// modal, because there is nobody standing there to dismiss one.
const STALE_AFTER_MS = 20 * 60_000

// How fast to try again before anything has ever been drawn. See the polling
// loop for why this is not the configured interval.
const BOOT_RETRY_S = 15

/** The frame minus its timestamp, for deciding whether anything actually
 *  changed. `generated_at` differs on every response by construction, so
 *  comparing whole bodies would repaint every poll — which on an eink browser
 *  (a Boox, a jailbroken Kindle) is a visible full-screen flash every five
 *  minutes for no new information. Same argument as the server's ETag. */
const stableOf = (frame: DisplayFrame) => {
  const { generated_at: _ignored, ...rest } = frame
  return JSON.stringify(rest)
}

export function DisplayView({ token }: { token: string }) {
  const [frame, setFrame] = useState<DisplayFrame | null>(null)
  // 'gone' is terminal — the token was revoked or the display deleted, and no
  // amount of retrying will bring it back. Anything else is transient and keeps
  // whatever is on screen: a 500, a rate limit or a dropped connection says
  // nothing about the display, and a panel that blanked itself over one lost
  // packet would be worse than one showing a slightly old month.
  const [gone, setGone] = useState(false)
  const [fetchedAt, setFetchedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const stable = useRef<string | null>(null)

  const load = useCallback(async () => {
    const abort = new AbortController()
    const timer = setTimeout(() => abort.abort(), FETCH_TIMEOUT_MS)
    try {
      const next = await api.publicDisplayFrame(token, abort.signal)
      const key = stableOf(next)
      // The state is only replaced when something is actually different. React
      // would reconcile an identical tree to no DOM writes anyway, but an eink
      // browser repaints on its own schedule and this keeps the tree itself
      // stable rather than trusting that.
      if (key !== stable.current) {
        stable.current = key
        setFrame(next)
      }
      setFetchedAt(Date.now())
      setGone(false)
    } catch (e) {
      const status = (e as { status?: number })?.status
      if (status === 404) setGone(true)
      // Everything else: keep the screen as it is and try again next tick.
    } finally {
      clearTimeout(timer)
    }
  }, [token])

  useEffect(() => { void load() }, [load])

  // The polling loop, at whatever cadence this display was configured for. The
  // interval comes from the frame rather than from a constant here, so changing
  // it in Settings reaches the panel on its next fetch without anyone touching
  // the device.
  //
  // Until there IS a frame, it retries fast. A wall panel is powered by a
  // switch on the wall and boots when the room does — often before the wifi has
  // an address — so the first fetch is the one most likely to fail, and waiting
  // out a five-minute interval to try again means five minutes of blank screen
  // for a network that came up two seconds later. Once a frame is on screen
  // there is nothing urgent left, and the configured cadence takes over.
  const seconds = frame ? frame.display.refresh_seconds : BOOT_RETRY_S
  useEffect(() => {
    const id = setInterval(() => { void load() }, seconds * 1000)
    return () => clearInterval(id)
  }, [load, seconds])

  // A separate, slower clock, whose only job is to let the staleness strip
  // appear without a fetch having to succeed first. Reading `Date.now()` during
  // render instead would never re-run: nothing else on this page changes.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(id)
  }, [])

  // The day rolls over at midnight and the frame is what says which day it is.
  // A calendar display polling every five minutes crosses into the new day
  // within one poll of it; nothing here has to compute that, which is the point
  // — the browser's own idea of "today" is the third clock this app is careful
  // never to introduce.
  useEffect(() => {
    document.title = frame ? `${frame.display.name} · Smylte` : 'Smylte'
  }, [frame])

  const palette = frame?.display.palette ?? 'color'
  const stale = fetchedAt !== null && now - fetchedAt > STALE_AFTER_MS

  return (
    <div className={`display display--${palette}`} data-mode={frame?.display.mode ?? 'calendar'}>
      {gone ? (
        // The one message this page will ever show instead of content, and it
        // is addressed to whoever walks up to the screen — not to a developer.
        <div className="display__gone">
          <p className="display__gone-title">This display is no longer connected.</p>
          <p className="display__gone-hint">Pair it again from Settings → Displays.</p>
        </div>
      ) : !frame ? (
        // Deliberately blank rather than a spinner. A spinner on a wall panel
        // animates forever in the corner of a room; a blank screen for two
        // seconds is what a wall calendar looks like while it is being hung.
        <div className="display__booting" aria-hidden="true" />
      ) : (
        <>
          {frame.calendar ? <CalendarFace frame={frame} /> : null}
          {frame.habits ? <HabitsFace frame={frame} /> : null}
          {stale ? <div className="display__stale">Not updated recently</div> : null}
        </>
      )}
    </div>
  )
}

/** The lookup a chip needs to draw itself: colour on a colour screen, a shape
 *  on eink, and a letter when there are more calendars than shapes. */
const sourceOf = (frame: DisplayFrame, id: string | null): DisplaySource | undefined =>
  id ? frame.sources.find(s => s.id === id) : undefined

function Chip({ frame, item }: { frame: DisplayFrame; item: DisplayItem }) {
  const src = sourceOf(frame, item.source)
  const eink = frame.display.palette === 'eink'
  return (
    <div className={`display-chip display-chip--${src?.treatment ?? 'solid'}`}>
      <span
        className="display-chip__mark"
        // The colour is an inline style because it is DATA — the calendar's own
        // colour, which no stylesheet can know. On eink it is omitted entirely
        // and the treatment class draws the mark, since a colour on a one-bit
        // panel is either black or invisible depending on how it thresholds.
        style={eink || !src?.color ? undefined : { background: src.color }}
      />
      {src?.initial ? <span className="display-chip__initial">{src.initial}</span> : null}
      {item.time ? <span className="display-chip__time">{item.time}</span> : null}
      <span className="display-chip__text">{item.text}</span>
    </div>
  )
}

/** How many chips fit in one cell, measured rather than guessed.
 *
 * `overflow: hidden` alone is not enough here: it cuts the last chip through
 * the middle of its letters, which on a wall reads as a rendering fault rather
 * than as "there is more". The server-side renderer computes this exactly (see
 * render.py's `room`), and the browser has to do the same arithmetic or the two
 * surfaces disagree about the same month.
 *
 * Measured from what is actually on screen — a rendered chip and a rendered day
 * number — because every size in display.css is a `clamp()` against the
 * viewport and a constant here would be wrong on the next panel. `null` means
 * "not measured yet", which renders everything for one frame and is corrected
 * on the layout effect before paint.
 */
function useCellRoom(grid: React.RefObject<HTMLDivElement | null>, deps: unknown) {
  const [room, setRoom] = useState<number | null>(null)
  useLayoutEffect(() => {
    const measure = () => {
      const el = grid.current
      if (!el) return
      const chip = el.querySelector('.display-chip') as HTMLElement | null
      const head = el.querySelector('.display-cal__daynum') as HTMLElement | null
      const cell = el.querySelector('.display-cal__cell') as HTMLElement | null
      if (!chip || !head || !cell) return
      const chipH = chip.getBoundingClientRect().height
      if (chipH <= 0) return
      const free = cell.clientHeight - head.getBoundingClientRect().height - 4
      setRoom(Math.max(0, Math.floor(free / chipH)))
    }
    measure()
    // A wall panel does not resize, but a browser being set up in front of one
    // does, and so does an orientation flip on a tablet — so the size is
    // watched where that is possible.
    //
    // FEATURE-DETECTED, and not merely to satisfy a test runner. The hardware
    // this page is aimed at includes old tablets and cheap kiosk webviews, and
    // `new ResizeObserver` on a browser without one throws during the layout
    // effect — which unmounts the whole tree and leaves the panel BLANK. A
    // display that degrades to "measured once, at mount" is a display that
    // still works.
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    if (grid.current) ro.observe(grid.current)
    return () => ro.disconnect()
  }, [grid, deps])
  return room
}

function CalendarFace({ frame }: { frame: DisplayFrame }) {
  const cal = frame.calendar!
  const gridRef = useRef<HTMLDivElement>(null)
  const room = useCellRoom(gridRef, cal.month)
  return (
    <div className="display-cal">
      <header className="display-cal__head">
        <h1 className="display-cal__title">{cal.title}</h1>
        <span className="display-cal__name">{frame.display.name}</span>
      </header>
      <div className="display-cal__weekdays">
        {cal.weekday_names.map(name => (
          <span key={name} className="display-cal__weekday">{name}</span>
        ))}
      </div>
      <div className="display-cal__grid" ref={gridRef}>
        {cal.weeks.map((week, w) => (
          <div className="display-cal__week" key={w}>
            {week.map(cell => {
              const shown = room === null ? cell.items : cell.items.slice(0, room)
              // What the cell could not draw plus what the frame already capped
              // away, counted together: the reader wants one number, not the
              // provenance of two.
              const spare = cell.items.length - shown.length + cell.hidden
              return (
                <div
                  key={cell.day}
                  className={
                    `display-cal__cell${cell.in_month ? '' : ' is-outside'}` +
                    `${cell.today ? ' is-today' : ''}`
                  }
                >
                  <div className="display-cal__daynum">
                    <span className="display-cal__num">{cell.label}</span>
                    {/* The count rides on the date's line rather than taking an
                        item row of its own. On a small panel a cell holds about
                        two events, and spending one of them to say "+4" costs
                        the reader more than the count is worth. */}
                    {spare > 0 ? (
                      <span className="display-cal__more">+{spare}</span>
                    ) : null}
                  </div>
                  <div className="display-cal__items">
                    {shown.map((item, i) => (
                      <Chip key={`${cell.day}-${i}`} frame={frame} item={item} />
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

function HabitsFace({ frame }: { frame: DisplayFrame }) {
  const block = frame.habits!
  const { counts } = block
  const nothing = block.habits.length === 0 && block.tasks.length === 0
  const finished = counts.habits_done > 0 || counts.tasks_done > 0
  return (
    <div className="display-day">
      <header className="display-day__head">
        <h1 className="display-day__title">{frame.display.name}</h1>
        {counts.habits_total > 0 ? (
          // The score. It is the whole reason the counts are taken before the
          // done rows are hidden: with hiding on, the list empties as the day
          // goes and this is the only thing left that remembers there was
          // anything on it.
          <span className="display-day__tally">
            {counts.habits_done}/{counts.habits_total}
          </span>
        ) : null}
      </header>

      {block.planned ? null : (
        <div className="display-day__preview">
          <p className="display-day__preview-title">{block.preview_text}</p>
          <p className="display-day__preview-hint">{block.preview_hint}</p>
        </div>
      )}

      {block.habits.length > 0 ? (
        <section className="display-day__section">
          <h2 className="display-day__label">{block.heading}</h2>
          <ul className="display-day__rows">
            {block.habits.map((row, i) => (
              <li key={`h-${i}`} className={`display-row${row.done ? ' is-done' : ''}`}>
                {/* A ring, filled once it is done — never a tick inside the
                    ring. A diagonal through a circle is the sign for "not
                    allowed", and the first version of this read as though every
                    kept habit were forbidden. */}
                <span className="display-row__ring" aria-hidden="true" />
                <span className="display-row__text">{row.text}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {block.tasks.length > 0 ? (
        <section className="display-day__section">
          <h2 className="display-day__label">{block.day_heading}</h2>
          <ul className="display-day__rows">
            {block.tasks.map((row, i) => (
              <li key={`t-${i}`} className={`display-row${row.done ? ' is-done' : ''}`}>
                <span className="display-row__box" aria-hidden="true" />
                <span className="display-row__text">{row.text}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {nothing ? (
        // Two different silences, worth telling apart: a day that had rows and
        // has none left is a finished day; a day that never had any is an empty
        // one. Only the first has earned anything.
        <p className="display-day__empty">
          {finished ? block.all_done_text : block.empty_text}
        </p>
      ) : null}
    </div>
  )
}
