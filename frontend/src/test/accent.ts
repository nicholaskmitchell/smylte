// A phone's accent palette and the shipped backgrounds, for the wallpaper
// accent's tests. The palette is Material's baseline blue, one `#rrggbb` per
// tone of ACCENT_TONES, as the host formats it.
import { DEFAULTS } from '../appearance'

export const RAMP: readonly string[] = [
  '#ffffff', '#fefbff', '#edf0ff', '#d8e2ff', '#adc6ff', '#7eabff', '#4d8eff',
  '#2173e8', '#005ac1', '#004494', '#002e69', '#001a41', '#000000',
]

/** Another wallpaper: the two tones the shipped backgrounds pick differ. */
export const RAMP2: readonly string[] =
  RAMP.map((c, i) => (i === 8 ? '#006e1c' : i === 4 ? '#78dc77' : c))

const surfaces = (m: 'light' | 'dark') =>
  (['--bg', '--bg-elev', '--paper'] as const).map((k) => `${k}: ${DEFAULTS[m][k]};`).join(' ')

/** jsdom loads no stylesheet (css: false) but cascades a `<style>` element's
 *  custom properties. */
export const SURFACES_CSS =
  `:root { ${surfaces('light')} }\n:root[data-theme="dark"] { ${surfaces('dark')} }\n`
