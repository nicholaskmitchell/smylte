import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, type DisplayFrame, type DisplayItem, type DisplaySource } from '../api'
import { deviceLanguage, isLanguage } from '../lang'
import { translate } from '../i18n/index'

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
//
// The three strings this page authors ITSELF — the stale strip and the two
// lines of the gone card — are states the frame cannot describe, and they take
// the frame's language too: `translate` and `deviceLanguage` are the same
// React-free leaves BookingPage borrows, not the authed shell's provider. A
// German household's hallway panel used to say "Heute", "Gewohnheiten" and then
// "Not updated recently" across the bottom.

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
//
// A FLOOR, not the whole rule — see `staleAfter` below. Settings offers "Every
// hour", and against a flat twenty minutes a display on that cadence was
// reporting itself stale for forty minutes out of every healthy hour, which
// teaches the one person who reads it to stop believing the strip.
const STALE_AFTER_MS = 20 * 60_000

// How many missed polls count as silence. Two and a half rather than two, so a
// single late fetch does not trip it on the poll boundary.
const STALE_POLLS = 2.5

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
  // Scaled to the cadence this display actually polls at, floored at the
  // absolute bound: "several polls" means something different at 60s and at an
  // hour, and only the display knows which it is.
  const staleAfter = Math.max(STALE_AFTER_MS, seconds * STALE_POLLS * 1_000)
  const stale = fetchedAt !== null && now - fetchedAt > staleAfter

  // The owner's language, from the last frame this screen drew. `gone` does
  // not clear the frame, so a display that was paired once still knows it; a
  // 404 on the very first fetch has nothing better than the device's own.
  const lang = frame && isLanguage(frame.language) ? frame.language : deviceLanguage()
  const tr = (key: string) => translate(lang, key)

  return (
    <div className={`display display--${palette}`} data-mode={frame?.display.mode ?? 'calendar'}>
      {gone ? (
        // The one message this page will ever show instead of content, and it
        // is addressed to whoever walks up to the screen — not to a developer.
        <div className="display__gone">
          <p className="display-title display__gone-title">{tr('display.gone')}</p>
          <p className="display__gone-hint">{tr('display.goneHint')}</p>
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
          {frame.now ? <NowFace frame={frame} /> : null}
          {stale ? <div className="display-label display__stale">{tr('display.stale')}</div> : null}
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

/** How many chips fit in one cell of `grid`, or null if it cannot be measured.
 *
 * `overflow: hidden` alone is not enough here: it cuts the last chip through
 * the middle of its letters, which on a wall reads as a rendering fault rather
 * than as "there is more". The server-side renderer computes this exactly (see
 * render.py's `room`), and the browser has to do the same arithmetic or the two
 * surfaces disagree about the same month.
 *
 * Measured rather than derived from constants, because every size in display.css
 * is a `clamp()` against the viewport and a number written here would be wrong
 * on the next panel.
 *
 * Exported for `display.browser.test.tsx`, which renders the count this returns
 * and then measures whether it actually fits. That test is the only place the
 * arithmetic can be checked — under jsdom every box is 0×0 — and it has to call
 * THIS function rather than restate it, or the copy is what stays correct.
 */
export function measureRoom(grid: HTMLElement): number | null {
  // The PROBE, not whichever chip happens to be on screen. Measuring a real
  // chip made the measurement depend on its own result: at `room === 0` no chip
  // exists anywhere in the grid, so every later measure bailed out and `room`
  // could never leave 0 — a wall showing day numbers and "+N" and no event text
  // for the life of the page load. A month that simply began with no events had
  // the mirror of it: nothing to measure, `room` stayed null, every cell
  // rendered all twenty items and `overflow: hidden` cut the surplus mid-glyph
  // until the month rolled over.
  const probe = grid.querySelector('.display-cal__probe') as HTMLElement | null
  const boxes = grid.querySelectorAll('.display-cal__items')
  if (!probe || !boxes.length) return null
  const chipH = probe.getBoundingClientRect().height
  if (chipH <= 0) return null
  // `.display-cal__items` is `flex: 1`, so its own height IS the space a cell
  // gives its chips — no arithmetic over the cell's padding and the column gap,
  // which is what the previous `- 4` was standing in for and got wrong by 4px.
  // Measured in Chromium at 800×480 before this: the last chip `room` promised
  // overflowed its box by 2.1px and was cut through the letters, which is the
  // exact failure this function exists to prevent.
  //
  // The SMALLEST box across the grid, because they are not all equal: the today
  // cell's knocked-out number is taller than a plain one, so a count taken from
  // the first cell alone overflows on that one.
  let free = Infinity
  boxes.forEach(box => { free = Math.min(free, (box as HTMLElement).clientHeight) })
  // n chips need n·chipH + (n−1)·gap, so n ≤ (free + gap) / (chipH + gap). The
  // row gap was ignored entirely before, which over-counted again.
  const gap = parseFloat(getComputedStyle(boxes[0]).rowGap) || 0
  return Math.max(0, Math.floor((free + gap) / (chipH + gap)))
}

/** `measureRoom` against the live grid, re-run when the panel resizes.
 *
 * `null` means "not measured yet", which renders everything for one frame and
 * is corrected on the layout effect before paint.
 */
function useCellRoom(grid: React.RefObject<HTMLDivElement | null>, deps: unknown) {
  const [room, setRoom] = useState<number | null>(null)
  useLayoutEffect(() => {
    const measure = () => {
      const el = grid.current
      if (!el) return
      const next = measureRoom(el)
      if (next !== null) setRoom(next)
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
      {/* Rendered always, shown only by the one media query in display.css
          that matches a screen too small for seven columns. A panel that small
          does not run a browser at all — which is why the image endpoint
          refuses the same sizes — but a kiosk pointed at one would otherwise
          show six empty slivers and no day numbers, which reads as broken
          rather than as misconfigured. */}
      <div className="display-cal__toosmall">
        <p className="display-title display-cal__toosmall-title">{cal.too_small_text}</p>
        <p className="display-cal__toosmall-hint">{cal.too_small_hint}</p>
      </div>
      <header className="display-cal__head">
        <h1 className="display-title display-cal__title">{cal.title}</h1>
        <span className="display-label display-cal__name">{frame.display.name}</span>
      </header>
      <div className="display-cal__weekdays">
        {cal.weekday_names.map(name => (
          <span key={name} className="display-label display-cal__weekday">{name}</span>
        ))}
      </div>
      <div className="display-cal__grid" ref={gridRef}>
        {/* The chip `useCellRoom` measures. Out of flow and invisible, so it
            costs no row and is never read aloud, but it is ALWAYS here — which
            is the point: measuring a real chip made the measurement depend on
            whether there were any chips, and the answer latched at zero. Its
            content is representative rather than empty, since a chip's height
            is its line box. */}
        <div className="display-chip display-cal__probe" aria-hidden="true">
          <span className="display-chip__mark" />
          <span className="display-chip__time">00:00</span>
          <span className="display-chip__text">Probe</span>
        </div>
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
                    <span className="display-title display-cal__num">{cell.label}</span>
                    {/* The count rides on the date's line rather than taking an
                        item row of its own. On a small panel a cell holds about
                        two events, and spending one of them to say "+4" costs
                        the reader more than the count is worth. */}
                    {spare > 0 ? (
                      <span className="display-label display-cal__more">+{spare}</span>
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

/** How many rows of each section fit, and what that leaves uncounted.
 *
 * The habits face's twin of `measureRoom`, and it exists for the same reason:
 * `overflow: hidden` stops rows painting over the next heading, but a section
 * that quietly shows the first four of eleven is the lie this whole feature
 * refuses elsewhere — "the first eight of forty", as the frame module puts it.
 *
 * The ALLOCATION mirrors `render.py::section`, deliberately: habits first,
 * today with what is left, one combined "+N", and no heading over an empty
 * block. The two surfaces must agree about the same day. What is NOT shared is
 * the geometry — every size in display.css is a `clamp()` against the viewport,
 * so the browser measures its own boxes rather than carrying the renderer's
 * numbers, exactly as the month grid does.
 */
export function measureRows(
  body: HTMLElement, habits: number, tasks: number, hidden: number,
): { habits: number; tasks: number; missed: number } | null {
  const probe = body.querySelector('.display-day__probe') as HTMLElement | null
  const probeRow = probe?.querySelector('.display-row') as HTMLElement | null
  if (!probe || !probeRow) return null
  const rowH = probeRow.getBoundingClientRect().height
  // The heading and the gap under it: whatever a section costs before its
  // first row.
  const head = probe.getBoundingClientRect().height - rowH
  const free = body.clientHeight
  const gap = parseFloat(getComputedStyle(body).rowGap) || 0
  if (rowH <= 0 || free <= 0) return null

  let cursor = 0
  const plan = (rows: number, rest: number) => {
    if (!rows) return 0
    const fits = Math.max(0, Math.floor((free - (cursor + head)) / rowH))
    let shown = Math.min(rows, fits)
    // Spend the last row on the count rather than on one more line the reader
    // cannot know is the last — but never the ONLY row, which would leave a
    // heading standing over nothing.
    if ((rows > shown || rest) && shown > 1 && shown === fits) shown -= 1
    if (shown <= 0) return 0
    cursor += head + shown * rowH + gap
    return shown
  }
  const h = plan(habits, tasks + hidden)
  const t = plan(tasks, 0)
  return { habits: h, tasks: t, missed: (habits - h) + (tasks - t) + hidden }
}

/** `measureRows` against the live body, re-run when the panel resizes. */
function useRowRoom(
  body: React.RefObject<HTMLDivElement | null>,
  habits: number, tasks: number, hidden: number,
) {
  const [room, setRoom] = useState<ReturnType<typeof measureRows>>(null)
  useLayoutEffect(() => {
    const measure = () => {
      const el = body.current
      if (!el) return
      const next = measureRows(el, habits, tasks, hidden)
      if (next) setRoom(next)
    }
    measure()
    // Feature-detected for the same reason `useCellRoom` is: on a kiosk webview
    // without one, `new ResizeObserver` throws inside the layout effect and
    // takes the whole page with it.
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    if (body.current) ro.observe(body.current)
    return () => ro.disconnect()
  }, [body, habits, tasks, hidden])
  return room
}

function HabitsFace({ frame }: { frame: DisplayFrame }) {
  const block = frame.habits!
  const { counts } = block
  const nothing = block.habits.length === 0 && block.tasks.length === 0
  const finished = counts.habits_done > 0 || counts.tasks_done > 0
  const bodyRef = useRef<HTMLDivElement>(null)
  const capped = block.habits_hidden + block.tasks_hidden
  const room = useRowRoom(bodyRef, block.habits.length, block.tasks.length, capped)
  // `null` is "not measured yet" — everything renders for one frame and is
  // corrected on the layout effect before paint, as on the month grid.
  const habitRows = room ? block.habits.slice(0, room.habits) : block.habits
  const taskRows = room ? block.tasks.slice(0, room.tasks) : block.tasks
  const missed = room ? room.missed : capped
  return (
    <div className="display-day">
      <header className="display-day__head">
        <h1 className="display-title display-day__title">{frame.display.name}</h1>
        {counts.habits_total > 0 ? (
          // The score. It is the whole reason the counts are taken before the
          // done rows are hidden: with hiding on, the list empties as the day
          // goes and this is the only thing left that remembers there was
          // anything on it.
          <span className="display-title display-day__tally">
            {counts.habits_done}/{counts.habits_total}
          </span>
        ) : null}
      </header>

      {block.planned ? null : (
        <div className="display-day__preview">
          <p className="display-label display-day__preview-title">{block.preview_text}</p>
          <p className="display-day__preview-hint">{block.preview_hint}</p>
        </div>
      )}

      <div className="display-day__body" ref={bodyRef}>
        {/* The section `measureRows` measures: one heading and one row, out of
            flow and invisible, but always present. Measuring a real row made
            the measurement depend on its own answer — the same trap the month
            grid's probe exists to avoid. */}
        <div className="display-day__section display-day__probe" aria-hidden="true">
          <h2 className="display-label display-day__label">{block.heading}</h2>
          <ul className="display-day__rows">
            <li className="display-row">
              <span className="display-row__ring" />
              <span className="display-row__text">Probe</span>
            </li>
          </ul>
        </div>

        {habitRows.length > 0 ? (
          <section className="display-day__section">
            <h2 className="display-label display-day__label">{block.heading}</h2>
            <ul className="display-day__rows">
              {habitRows.map((row, i) => (
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

        {taskRows.length > 0 ? (
          <section className="display-day__section">
            <h2 className="display-label display-day__label">{block.day_heading}</h2>
            <ul className="display-day__rows">
              {taskRows.map((row, i) => (
                <li key={`t-${i}`} className={`display-row${row.done ? ' is-done' : ''}`}>
                  <span className="display-row__box" aria-hidden="true" />
                  <span className="display-row__text">{row.text}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>

      {/* ONE count for the whole face, not one per section — what the panel had
          no room for plus what the frame had already capped away. The reader
          wants a number, not the provenance of two, and `render.py` draws the
          same single "+N" for the same reason. */}
      {missed > 0 ? (
        <p className="display-label display-day__more">+{missed}</p>
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

// ── the rolling face ─────────────────────────────────────────────────────────

/** The most lines the headline gets. Mirrors `render.NOW_MAX_LINES`; the two
 *  surfaces have to break the same title the same way. */
const NOW_MAX_LINES = 4

/** The type size for a rolling face's headline, and whether the next block fits.
 *
 * This is the one face whose type is FITTED rather than clamped against the
 * viewport, and the reason is that its content is fixed. Every other face here
 * sizes with `clamp()` because it draws an unbounded number of rows and a
 * bigger panel should show MORE of them; this one draws exactly two items
 * whatever the panel is, so there is no "more" to spend the pixels on. A title
 * set at a viewport-derived size left the bottom half of an 800×480 empty.
 *
 * `render.py::_render_now` searches the same way — largest size at which the
 * WHOLE title still fits, stepping down from a ceiling proportional to the
 * panel — so a browser panel and a bitmap panel put the same words at the same
 * size. That is why this measures rather than reading a number out of the
 * stylesheet: the number would be a second opinion.
 *
 * The `next` answer is not cosmetic. `remaining` counts what the FRAME left
 * behind the next item; a panel that then cannot draw that item is hiding one
 * more, and a screen saying "+5" while eight things wait is the first-eight-of-
 * forty lie this mode exists to refuse. So the caller adds it back.
 *
 * Exported for `display.browser.test.tsx`, which renders what this returns and
 * then measures whether it actually fits. Under jsdom every box is 0×0, so that
 * test is the only place the arithmetic can be checked — and it has to call
 * THIS function rather than restate it, or the copy is what stays correct.
 */
export function fitNow(
  root: HTMLElement,
): { size: number; head: boolean; est: boolean; next: boolean } | null {
  const main = root.querySelector('.display-now__main') as HTMLElement | null
  const title = root.querySelector('.display-now__title') as HTMLElement | null
  if (!main || !title) return null
  if (root.clientHeight <= 0) return null
  const floor = 14
  const needed = floor * 1.24

  const eyebrow = root.querySelector('.display-now__eyebrow') as HTMLElement | null
  const est = root.querySelector('.display-now__est') as HTMLElement | null

  // The optional parts, in the order they are conceded — and the order is the
  // argument. A display's name is the least of what this screen is for; the
  // estimate qualifies the current item; the next item is the second half of
  // the feature. `render.py::_render_now` concedes the same three in the same
  // order, so a browser panel and a bitmap panel of the same size drop the same
  // things. The headline never goes: it is the mode.
  const parts = ([
    ['head', root.querySelector('.display-now__head')],
    ['est', est],
    ['next', root.querySelector('.display-now__next')],
  ] as Array<['head' | 'est' | 'next', HTMLElement | null]>)

  /** The height the title actually has to live in.
   *
   *  Computed rather than read off the title's own box, because the title is
   *  NOT a flex item: it sits inside `.display-now__titlebox` so that
   *  `-webkit-line-clamp` survives. A `-webkit-box` used directly as a flex
   *  item is blockified and the clamp silently stops working — measured in
   *  Chromium, a title that should have been cut at four lines rendered
   *  twelve — and the clamp is the ellipsis this face falls back on when even
   *  the floor size will not fit. */
  const roomFor = () => {
    const gap = parseFloat(getComputedStyle(main).rowGap) || 0
    const others = [eyebrow, est].filter(
      (el): el is HTMLElement => !!el && el.style.display !== 'none')
    return main.clientHeight
      - others.reduce((n, el) => n + el.offsetHeight, 0)
      - gap * others.length
  }

  // This function OWNS their `display`, and it starts every pass by putting
  // them all back. React renders all three whenever the data has them, which
  // keeps this idempotent: measuring a DOM that a previous pass had already
  // stripped would find nothing left to concede, report everything as fitting,
  // and flip back and forth on every resize.
  const shown = { head: true, est: true, next: true }
  for (const [, el] of parts) if (el) el.style.display = ''
  for (const [key, el] of parts) {
    // Read first: hiding one grows the box, and reading it here forces the
    // reflow that makes the next question meaningful.
    if (roomFor() >= needed) break
    if (!el) continue
    el.style.display = 'none'
    shown[key] = false
  }
  const room = roomFor()

  // The same ceiling `_render_now` takes, and it reads the WIDTH as well as the
  // height: a portrait panel has height to spare and a narrow column, which is
  // the mistake `_grid_scale` was written to fix on the month face.
  const ceiling = Math.max(18, Math.min(root.clientHeight * 0.30,
                                        root.clientWidth * 0.20))
  // Measured with the clamp OFF, or the search would settle on a size whose
  // first four lines fit and whose fifth was quietly cut — which is the
  // truncation this face exists not to hide.
  const clamp = title.style.webkitLineClamp
  title.style.webkitLineClamp = 'unset'
  let size = floor
  for (let s = Math.floor(ceiling); s >= floor; s -= 2) {
    title.style.fontSize = `${s}px`
    if (title.scrollHeight <= Math.min(room, NOW_MAX_LINES * s * 1.24) + 1) {
      size = s
      break
    }
  }
  // LEFT ON THE NODE at the size chosen, not cleared for React to rewrite.
  // Clearing it worked only while the fit VALUE changed: the ResizeObserver's
  // initial notification re-runs this in the same frame as the first pass,
  // and when it returns the same number React diffs `{fontSize:'80px'}`
  // against `{fontSize:'80px'}`, writes nothing, and the node is left with no
  // inline size — the headline painted at the stylesheet's 7vh fallback,
  // 33.6px at 800x480 where the fit said 80, the bottom half of the panel
  // empty. Measured in Chromium; `backlog.sep03.display.browser.test.tsx`
  // pins it. `NowFace` still writes the same value through its style prop, so
  // the two agree by construction and a frame never shows a probe size.
  title.style.fontSize = `${size}px`
  title.style.webkitLineClamp = clamp
  return { size, ...shown }
}

/** `fitNow` against the live face, re-run when the panel resizes. */
function useNowFit(root: React.RefObject<HTMLDivElement | null>, deps: unknown) {
  const [fit, setFit] = useState<ReturnType<typeof fitNow>>(null)
  useLayoutEffect(() => {
    const measure = () => {
      const el = root.current
      if (!el) return
      const got = fitNow(el)
      if (got) setFit(got)
    }
    measure()
    // Once more when the webfont lands. The first pass usually runs on
    // fallback metrics — Fraunces loads lazily, when a rule first matches —
    // and a size fitted for Georgia is a few px wrong for the face that then
    // paints. Nothing else refires on a font swap: the box does not resize.
    // `document.fonts` is absent under jsdom, hence the guard.
    let alive = true
    if (typeof document !== 'undefined' && document.fonts?.ready) {
      void document.fonts.ready.then(() => { if (alive) measure() })
    }
    // Feature-detected for the same reason the other two hooks are: on a kiosk
    // webview without one, `new ResizeObserver` throws inside the layout effect
    // and takes the whole page with it.
    if (typeof ResizeObserver === 'undefined') return () => { alive = false }
    const ro = new ResizeObserver(measure)
    if (root.current) ro.observe(root.current)
    return () => { alive = false; ro.disconnect() }
  }, [root, deps])
  return fit
}

function NowFace({ frame }: { frame: DisplayFrame }) {
  const block = frame.now!
  const { counts, current, next } = block
  const rootRef = useRef<HTMLDivElement>(null)
  // `null` is "not measured yet" — the face renders at the floor for one frame
  // and is corrected on the layout effect before paint, as on the other two.
  const fit = useNowFit(rootRef, block)
  // What the frame left behind `next`, plus the `next` this panel could not
  // draw. `render.py::_render_now` does the same sum against its own budget,
  // and it is not cosmetic: `remaining` is what the FRAME hid, and a screen
  // saying "+5" while six things wait is the first-eight-of-forty lie this mode
  // exists to refuse.
  //
  // All three optional parts stay in the DOM whatever `fit` says — `fitNow`
  // hides them itself, and needs them there to measure against on the next
  // pass. Only the count reads its answer.
  const spare = block.remaining + (next !== null && fit && !fit.next ? 1 : 0)

  return (
    <div className="display-now" ref={rootRef}>
      {frame.display.name || counts.total > 0 ? (
        <header className="display-now__head">
          <h1 className="display-title display-now__name">{frame.display.name}</h1>
          {counts.total > 0 ? (
            // The score, and on this face it is the only thing that remembers
            // the finished items: they never appear on it at all.
            <span className="display-title display-now__tally">
              {counts.done}/{counts.total}
            </span>
          ) : null}
        </header>
      ) : null}

      {block.planned ? null : (
        // Nobody has opened today, so none of this is a plan — it is what
        // opening one would derive. The label matters more here than on any
        // other face: "Now: fix the boiler" reads as a commitment, and the
        // owner has not made one.
        <div className="display-now__preview">
          <p className="display-label display-now__preview-title">{block.preview_text}</p>
          <p className="display-now__preview-hint">{block.preview_hint}</p>
        </div>
      )}

      <div className="display-now__main">
        {current ? (
          <p className="display-label display-now__eyebrow">
            {/* The kind mark rides on the eyebrow rather than beside the
                headline. Beside a headline it has to be headline-sized to look
                deliberate, and an empty box that large on a screen with nothing
                to tap reads as a control — the one thing a display must never
                appear to offer. At label size it is a bullet, in the vocabulary
                the habits face already uses: a ring is a habit, a box is a row.
                Never filled, because by construction the current item is the
                first one that is NOT done. */}
            <span
              className={current.kind === 'habit'
                ? 'display-row__ring display-now__mark'
                : 'display-row__box display-now__mark'}
              aria-hidden="true" />
            {block.heading}
          </p>
        ) : null}
        {/* The box, and the title inside it. Two elements rather than one
            because `-webkit-line-clamp` does not survive being a flex item —
            Chromium blockifies it and the clamp stops working, silently. The
            box is the flex item; the title is a plain block child of it. */}
        <div className="display-now__titlebox">
          <p className="display-title display-now__title"
            style={fit ? { fontSize: `${fit.size}px` } : undefined}>
            {/* Two different silences, worth telling apart: a day that had
                things on it and has none left is a finished day, and a day that
                never had any is an empty one. Set in the same slot at the same
                size as a task, because a day you finished should read from the
                doorway too. */}
            {current ? current.text
              : counts.done ? block.all_done_text : block.empty_text}
          </p>
        </div>
        {current && current.estimate ? (
          <p className="display-label display-now__est">{current.estimate}</p>
        ) : null}
      </div>

      {next ? (
        <div className="display-now__next">
          <p className="display-label display-now__next-label">{block.next_heading}</p>
          <p className="display-now__next-text">{next.text}</p>
        </div>
      ) : null}

      {/* Mono and untracked, like every other count the app draws. The tally
          rides here only when the header that would normally carry it was the
          part this panel conceded — on a badge it is then the only thing left
          that says how much of the day is done. `_render_now` writes the same
          line, in the same order, for the same reason. */}
      {spare > 0 || (fit && !fit.head && counts.total > 0) ? (
        <p className="display-label display-now__more">
          {[
            ...(fit && !fit.head && counts.total > 0
              ? [`${counts.done}/${counts.total}`] : []),
            ...(spare > 0 ? [`+${spare}`] : []),
          ].join('  ')}
        </p>
      ) : null}
    </div>
  )
}
