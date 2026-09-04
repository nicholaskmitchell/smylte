// WCAG 2.x contrast, for the token tests.
//
// Test-only on purpose: nothing at runtime needs a contrast ratio, and the
// value of this file is that `appearance.test.ts` can assert a NUMBER about
// tokens.css rather than a string. Two closed findings raised `--fg-faint`
// from 2.3:1 to just over 3:1 (see the comments beside it in tokens.css), and
// until this existed the only thing pinning that was the mirror test — which a
// lockstep edit of both files walks straight through.
//
// Three syntaxes, because those are the three tokens.css uses: `#RRGGBB`,
// `rgba(r, g, b, a)` and `oklch(L C h)`. A translucent colour is composited
// over the background in sRGB space, which is what the browser does when it
// paints `--fg-faint` over `--bg`.

type RGB = [number, number, number]           // 0..255, sRGB
type RGBA = [number, number, number, number]  // alpha 0..1

function hex(s: string): RGBA | null {
  const m = s.match(/^#([0-9a-f]{6})$/i)
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1]
}

function rgba(s: string): RGBA | null {
  const m = s.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i)
  if (!m) return null
  return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]]
}

/** `oklch(L C h)` to sRGB, by way of OKLab and LMS — Björn Ottosson's
 *  published matrices, the same ones the CSS Color 4 spec reproduces. */
function oklch(s: string): RGBA | null {
  const m = s.match(/^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)$/i)
  if (!m) return null
  const L = +m[1], C = +m[2], h = (+m[3]) * Math.PI / 180
  const a = C * Math.cos(h), b = C * Math.sin(h)
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b
  const s_ = L - 0.0894841775 * a - 1.2914855480 * b
  const l = l_ ** 3, mm = m_ ** 3, ss = s_ ** 3
  const lin: RGB = [
    +4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * ss,
    -1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * ss,
    -0.0041960863 * l - 0.7034186147 * mm + 1.7076147010 * ss,
  ]
  const gamma = (c: number) => {
    const v = Math.min(1, Math.max(0, c))
    return v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055
  }
  return [gamma(lin[0]) * 255, gamma(lin[1]) * 255, gamma(lin[2]) * 255, 1]
}

/** A CSS colour in one of the three syntaxes tokens.css uses, or a throw —
 *  a token this cannot read must fail the test loudly, not pass as 0:1. */
export function parseColor(css: string): RGBA {
  const v = css.trim()
  const out = hex(v) ?? rgba(v) ?? oklch(v)
  if (!out) throw new Error(`contrast.ts cannot parse the colour ${JSON.stringify(css)}`)
  return out
}

/** `fg` painted over an opaque `bg`, as the browser composites it. */
export function composite(fg: RGBA, bg: RGB): RGB {
  const a = fg[3]
  return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)) as RGB
}

/** WCAG 2.x relative luminance of an sRGB colour. */
export function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/** The WCAG contrast ratio of `fg` over `bg`, both as CSS strings. `bg` is
 *  treated as opaque (every background token in tokens.css is), and a
 *  translucent `fg` is composited over it first. */
export function contrast(fg: string, bg: string): number {
  const back = parseColor(bg)
  const over = composite(parseColor(fg), [back[0], back[1], back[2]])
  const l1 = luminance(over), l2 = luminance([back[0], back[1], back[2]])
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1]
  return (hi + 0.05) / (lo + 0.05)
}
