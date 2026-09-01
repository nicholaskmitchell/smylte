// Settings → Developer: every display mode, at the sizes real panels come in.
//
// The problem this solves is that a display is drawn for hardware the person
// designing it does not have. A 2.9" badge is a 39px column and a 13.3" panel
// is 1600 wide, the type is `clamp()`d against the viewport in the browser and
// scaled off the panel's height in the rasterizer, and the only honest way to
// know whether a month is legible at 400×300 is to look at one. Before this the
// way to look at one was to make a display, copy its token into a URL and edit
// the query string — which mints a live credential that reaches this calendar
// with no session, for every size you want to try, and leaves you to remember
// to revoke them.
//
// So: `/api/displays/preview.png` is behind the session, writes nothing, and
// renders through the same frame builder and rasterizer the token routes use.
// What is previewed is what would ship.

import { useMemo, useState } from 'react'
import { useI18n } from '../i18n'

type Mode = 'calendar' | 'habits'
type Palette = 'color' | 'eink'

/** Panels that exist, with the sizes they actually are.
 *
 * Written out rather than generated, because the interesting ones are not on a
 * grid: 296×128 is the badge-sized e-paper that cannot hold a month at all,
 * 800×480 is the 7.5" Waveshare the `firmware/` example drives, and 1872×1404
 * is where the type stops being the constraint and the data starts being it.
 * Portrait entries are separate rows rather than a rotate toggle because a
 * portrait panel is a different design problem, not the same one turned.
 */
const PANELS: Array<{ label: string; w: number; h: number }> = [
  { label: '2.9" e-paper', w: 296, h: 128 },
  { label: '4.2" e-paper', w: 400, h: 300 },
  { label: '5.83" e-paper', w: 648, h: 480 },
  { label: '7.5" e-paper', w: 800, h: 480 },
  { label: '7.5" portrait', w: 480, h: 800 },
  { label: 'Kindle / 6"', w: 600, h: 800 },
  { label: '10.3" e-paper', w: 1872, h: 1404 },
  { label: '13.3" e-paper', w: 1600, h: 1200 },
  { label: 'Old tablet', w: 1280, h: 800 },
  { label: 'iPad (portrait)', w: 1536, h: 2048 },
]

const ROTATIONS = [0, 90, 180, 270] as const

/** The packed framebuffer a 1-bit panel of this size would receive — the number
 *  a microcontroller has to allocate before it can ask for a frame. */
const rawBytes = (w: number, h: number) => Math.ceil(w / 8) * h

const fmtBytes = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB`
    : n >= 1_000 ? `${Math.round(n / 1_000)} KB` : `${n} B`

export function DeveloperSection() {
  const { t: tr } = useI18n()
  const [mode, setMode] = useState<Mode>('calendar')
  const [palette, setPalette] = useState<Palette>('eink')
  const [rotation, setRotation] = useState<number>(0)
  const [hideDone, setHideDone] = useState(true)
  // Bumped to re-request every image at once. `<img>` will happily serve the
  // same URL from memory cache, and a preview that did not move when the
  // controls did would be worse than no preview.
  const [nonce, setNonce] = useState(0)

  const src = useMemo(() => (w: number, h: number) => {
    const q = new URLSearchParams({
      mode, palette, w: String(w), h: String(h), rotate: String(rotation),
      hide_done_habits: String(hideDone), hide_done_tasks: String(hideDone),
      n: String(nonce),
    })
    return `/api/displays/preview.png?${q}`
  }, [mode, palette, rotation, hideDone, nonce])

  return (
    <div className="dev">
      <div className="hintline">{tr('dev.intro')}</div>

      <div className="menu-row">
        <label>{tr('disp.mode')}</label>
        <button className="menu-toggle"
          onClick={() => setMode((m) => (m === 'calendar' ? 'habits' : 'calendar'))}>
          {tr(`disp.mode.${mode}`)}
        </button>
      </div>
      <div className="menu-row">
        <label>{tr('disp.palette')}</label>
        <button className="menu-toggle"
          onClick={() => setPalette((p) => (p === 'color' ? 'eink' : 'color'))}>
          {tr(`disp.palette.${palette}`)}
        </button>
      </div>
      <div className="menu-row">
        <label>{tr('disp.rotation')}</label>
        <button className="menu-toggle"
          onClick={() => setRotation((r) =>
            ROTATIONS[(ROTATIONS.indexOf(r as 0) + 1) % ROTATIONS.length])}>
          {rotation}°
        </button>
      </div>
      {mode === 'habits' ? (
        <div className="menu-row">
          <label>{tr('dev.hideDone')}</label>
          <button className="menu-toggle" onClick={() => setHideDone((v) => !v)}>
            {tr(hideDone ? 'disp.on' : 'disp.off')}
          </button>
        </div>
      ) : null}
      <div className="menu-actions">
        <button className="btn ghost" onClick={() => setNonce((n) => n + 1)}>
          {tr('dev.refresh')}
        </button>
      </div>

      <div className="menu-head">{tr('dev.panels')}</div>
      <div className="dev-grid">
        {PANELS.map((p) => {
          // What the panel is handed is its own framebuffer; rotation turns the
          // canvas the layout happens on, not the buffer. So the label keeps
          // the panel's pixels and the CANVAS is what a quarter turn swaps.
          const turned = rotation === 90 || rotation === 270
          const cw = turned ? p.h : p.w
          const ch = turned ? p.w : p.h
          return (
            <figure key={`${p.label}-${p.w}x${p.h}`} className="dev-panel">
              <img className="dev-panel__shot" src={src(p.w, p.h)}
                width={p.w} height={p.h} loading="lazy"
                alt={tr('dev.alt', { panel: p.label, w: String(p.w), h: String(p.h) })} />
              <figcaption className="dev-panel__cap">
                <span className="dev-panel__name">{p.label}</span>
                <span className="mono dev-panel__size">{p.w}×{p.h}</span>
                {/* The number a microcontroller allocates before it asks for a
                    frame. It is the whole reason `.bin` exists, and it is not
                    obvious from the pixels: 1872×1404 is 329 KB, which is most
                    of a Pico 2's RAM. */}
                {palette === 'eink' ? (
                  <span className="mono dev-panel__bytes">
                    {fmtBytes(rawBytes(cw, ch))}
                  </span>
                ) : null}
              </figcaption>
            </figure>
          )
        })}
      </div>
      <div className="hintline">{tr('dev.hint')}</div>
    </div>
  )
}
