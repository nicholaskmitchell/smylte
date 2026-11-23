// Every icon button draws its icon under Field notes.
//
// An icon button that carries only its typographic glyph (‹ ✕ + …) shows that
// glyph at no size under Field notes the moment its icon is missing — or, if
// it carries no IconInk at all, shows the old sliver. So this holds the JSX:
// every <button> whose class names `icon-btn`, `today-menu-btn` or `chip-x`
// carries an <IconInk>, or is one of the line-art icons drawn with its own
// <svg> (the gear, the new-group folder). Read as text, as
// date-time-input.test.tsx holds DateTimeInput, because a rule applied by
// remembering it is a rule with a half-life.
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = resolve(process.cwd(), 'src')
const files = [
  'App.tsx',
  ...readdirSync(resolve(SRC, 'components'))
    .filter((f) => f.endsWith('.tsx') && !f.endsWith('.test.tsx'))
    .map((f) => `components/${f}`),
]

/** Each <button …>…</button> in a file whose className names one of `classes`. */
function buttons(src: string, classes: string[]): string[] {
  const out: string[] = []
  for (const m of src.matchAll(/<button\b[\s\S]*?<\/button>/g)) {
    const cls = /className=(?:"([^"]*)"|\{`([^`]*)`\}|\{([^}]*)\})/.exec(m[0])
    const names = (cls?.[1] ?? cls?.[2] ?? cls?.[3] ?? '')
    if (classes.some((c) => new RegExp(`(^|[\\s'"\`])${c}([\\s'"\`$]|$)`).test(names))) out.push(m[0])
  }
  return out
}

describe('icon buttons', () => {
  const all = files.flatMap((f) => buttons(readFileSync(resolve(SRC, f), 'utf8'), ['icon-btn', 'today-menu-btn', 'chip-x'])
    .map((b) => ({ f, b })))

  it('finds them', () => {
    // 33 icon buttons, the ⋯ and the chip's × when this was written.
    expect(all.length).toBeGreaterThanOrEqual(35)
  })

  it('each draw the pen\'s icon, or are line art of their own', () => {
    const bare = all.filter(({ b }) => !/<IconInk\b|<svg\b|<GearIcon\b/.test(b))
      .map(({ f, b }) => `${f}: ${b.slice(0, 90).replace(/\s+/g, ' ')}…`)
    expect(bare, 'these show their glyph at no size under Field notes').toEqual([])
  })
})

describe('on and off', () => {
  const src = Object.fromEntries(files.map((f) => [f, readFileSync(resolve(SRC, f), 'utf8')]))

  it('every toggle with aria-pressed draws its check', () => {
    // A toggle whose words name the value (Shown/Hidden, Roll straight on/Wait
    // for me, Stop at the estimate/Work until done) keeps its face and carries
    // `data-value`: a check beside a value word reads as its negation (an
    // unticked box beside "Hidden" reads "not hidden").
    const toggles = files.flatMap((f) => buttons(src[f], ['menu-toggle'])
      .filter((b) => /aria-pressed=/.test(b) && !/\sdata-value=/.test(b)).map((b) => ({ f, b })))
    // 16 when this was written: 19 less the three value toggles.
    expect(toggles.length).toBeGreaterThanOrEqual(16)
    const bare = toggles.filter(({ b }) => !/<CheckInk\b/.test(b))
      .map(({ f, b }) => `${f}: ${b.slice(0, 90).replace(/\s+/g, ' ')}…`)
    expect(bare).toEqual([])
  })

  it('exactly three toggles name their value and carry data-value, with no check', () => {
    const value = files.flatMap((f) => buttons(src[f], ['menu-toggle'])
      .filter((b) => /\sdata-value=/.test(b)).map((b) => ({ f, b })))
    // By the first word key in each: the face's "on" side.
    const keys = value.map(({ b }) => /'([\w.]+)'/.exec(b)?.[1]).sort()
    expect(keys).toEqual([
      'settings.completedTasks.shown',
      'settings.focus.cap.capped',
      'settings.focus.end.roll',
    ])
    expect(value.filter(({ b }) => /<CheckInk\b/.test(b))).toEqual([])
    expect(value.filter(({ b }) => !/aria-pressed=/.test(b))).toEqual([])
  })

  it('every native checkbox sits in a .box-ink with its drawn check', () => {
    const boxes = files.flatMap((f) => [...src[f].matchAll(/<input\b(?:(?!\/>)[\s\S])*?type="checkbox"(?:(?!\/>)[\s\S])*?\/>/g)]
      .map((m) => ({ f, at: m.index!, tag: m[0], s: src[f] })))
    expect(boxes.length).toBeGreaterThanOrEqual(7)
    const bare = boxes.filter(({ s, at, tag }) =>
      !/<span className="box-ink">\s*$/.test(s.slice(Math.max(0, at - 60), at))
      || !/^\s*<CheckInk\b/.test(s.slice(at + tag.length)))
      .map(({ f, tag }) => `${f}: ${tag.slice(0, 80).replace(/\s+/g, ' ')}`)
    expect(bare).toEqual([])
  })
})

describe('the segmented switch', () => {
  it('every segment carries the drawn underline; the lone view tab does not', () => {
    const tabs = files.flatMap((f) => buttons(readFileSync(resolve(SRC, f), 'utf8'), ['view-tab'])
      .map((b) => ({ f, b })))
    // CalendarViewTabs, TaskModal (two), DisplayModeFrame, AppearancePanel,
    // TasksView, and Home's lone Arrange when this was written.
    expect(tabs.length).toBeGreaterThanOrEqual(7)
    const lone = tabs.filter(({ f }) => f === 'components/HomeView.tsx')
    expect(lone).toHaveLength(1)
    expect(lone[0].b).not.toMatch(/<TabInk\b/)
    const bare = tabs.filter(({ f, b }) => f !== 'components/HomeView.tsx' && !/<TabInk\b/.test(b))
      .map(({ f, b }) => `${f}: ${b.slice(0, 90).replace(/\s+/g, ' ')}…`)
    expect(bare).toEqual([])
  })
})

describe('selects', () => {
  it('every select in the components is an InkSelect, which draws its caret', () => {
    const raw = files.filter((f) => f !== 'components/InkSelect.tsx')
      .filter((f) => /<select\b/.test(readFileSync(resolve(SRC, f), 'utf8')))
    expect(raw, 'a bare <select> shows no caret under Field notes').toEqual([])
    const ink = files.flatMap((f) => [...readFileSync(resolve(SRC, f), 'utf8').matchAll(/<InkSelect\b/g)])
    // 25 when this was written.
    expect(ink.length).toBeGreaterThanOrEqual(25)
  })
})

describe('date and time fields', () => {
  it('draw their page or clock, except the two dense date fields', () => {
    const plain = files.flatMap((f) => [...readFileSync(resolve(SRC, f), 'utf8').matchAll(/<DateTimeInput\s+plain\b/g)].map(() => f))
    expect(plain.sort()).toEqual(['components/ShutdownRitual.tsx', 'components/TodayView.tsx'])
  })
})

// A control whose only visible text is one symbol (✕, +, ›, ↺, ◉ …) shows that
// symbol at no size under Field notes, or as the old sliver, unless it draws
// the pen's icon or the check. So this holds every <button> in the components
// whose text is one character that is not a letter or a digit, written as a
// literal or a ternary of literals: it carries an <IconInk> or a <CheckInk>.
// The text is the button's own, or, where it has none, its elements' (the
// carets' glyph sits in a span); an expression that is not a literal is a
// word, and one that renders an element (a badge) shows nothing of its own.
describe('glyph controls', () => {
  /** Buttons that show a symbol as text because the symbol is their value,
   *  not a control's glyph. Each says why. */
  const VALUES: { file: string; className: string; why: string }[] = [
    // "No colour": the ✕ is the colour row's value for none, beside the
    // swatches that show theirs; it is not the glyph of an action.
    { file: 'components/Sidebar.tsx', className: 'color-dot none', why: 'the colour row\'s value for no colour' },
  ]

  /** Index just past the `>` closing the tag that opens at `i`. Braces and the
   *  strings in them are skipped, so an arrow's `=>` does not close it. */
  const tagEnd = (s: string, i: number) => {
    let depth = 0
    let q: string | null = null
    for (; i < s.length; i++) {
      const ch = s[i]
      if (q) { if (ch === q && s[i - 1] !== '\\') q = null; continue }
      if (ch === '"' || (depth > 0 && (ch === "'" || ch === '`'))) { q = ch; continue }
      if (ch === '{') depth++
      else if (ch === '}') depth--
      else if (ch === '>' && depth === 0) return i + 1
    }
    throw new Error(`unclosed tag: ${s.slice(i, i + 60)}`)
  }
  /** Index just past the `}` matching the `{` at `i`. */
  const braceEnd = (s: string, i: number) => {
    let depth = 0
    let q: string | null = null
    for (; i < s.length; i++) {
      const ch = s[i]
      if (q) { if (ch === q && s[i - 1] !== '\\') q = null; continue }
      if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue }
      if (ch === '{') depth++
      else if (ch === '}' && --depth === 0) return i + 1
    }
    throw new Error(`unclosed brace: ${s.slice(i, i + 60)}`)
  }
  const WORD = '\u0000word'
  /** What an expression child shows: its literals when it is a literal or a
   *  ternary of literals, a word when it is anything else, and nothing when
   *  it renders an element or is a comment. */
  const shows = (expr: string): string[] => {
    const e = expr.trim()
    if (!e || /^\/\*[\s\S]*\*\/$/.test(e) || /</.test(e)) return []
    const alts = /^[^?]+\?([\s\S]+):([\s\S]+)$/.exec(e)
    const out: string[] = []
    for (const p of alts ? [alts[1], alts[2]] : [e]) {
      const lit = /^(?:'([^']*)'|"([^"]*)"|`([^`$]*)`)$/.exec(p.trim())
      if (!lit) return [WORD]
      out.push(lit[1] ?? lit[2] ?? lit[3])
    }
    return out
  }
  /** The visible text of a button's children: its own, or its elements'. */
  const text = (inner: string): string[] => {
    const own: string[] = []
    const nested: string[] = []
    let depth = 0
    let run = ''
    const flush = () => { if (run.trim()) (depth ? nested : own).push(...run.trim().split(/\s+/)); run = '' }
    for (let i = 0; i < inner.length;) {
      if (inner[i] === '<') {
        flush()
        const e = tagEnd(inner, i)
        const tag = inner.slice(i, e)
        if (tag.startsWith('</')) depth--
        else if (!tag.endsWith('/>')) depth++
        i = e
      } else if (inner[i] === '{') {
        flush()
        const e = braceEnd(inner, i);
        (depth ? nested : own).push(...shows(inner.slice(i + 1, e - 1)))
        i = e
      } else run += inner[i++]
    }
    flush()
    return own.length ? own : nested
  }
  const SYMBOL = /^[^\p{L}\p{N}\s]$/u
  // Comments blanked, keeping the lines: one names a `<button>` in backticks.
  const blank = (c: string) => c.replace(/[^\n]/g, ' ')
  const found = files.filter((f) => f.startsWith('components/')).flatMap((f) => {
    const src = readFileSync(resolve(SRC, f), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, blank).replace(/^\s*\/\/.*$/gm, blank)
    return [...src.matchAll(/<button\b/g)].flatMap((m) => {
      const end = tagEnd(src, m.index)
      if (src[end - 2] === '/') return []
      const inner = src.slice(end, src.indexOf('</button>', end))
      const shown = text(inner)
      if (!shown.length || !shown.every((t) => SYMBOL.test(t))) return []
      const open = src.slice(m.index, end)
      const className = /className=(?:"([^"]*)"|\{`([^`]*)`\})/.exec(open)
      return [{
        f, line: src.slice(0, m.index).split('\n').length, shown,
        className: (className?.[1] ?? className?.[2] ?? '').replace(/\$\{[^}]*\}/g, '').trim(),
        drawn: /<IconInk\b|<CheckInk\b/.test(inner),
      }]
    })
  })

  it('finds them', () => {
    // 55 when this was written, the colour row's ✕ among them.
    expect(found.length).toBeGreaterThanOrEqual(55)
  })

  it('each draw the pen\'s icon or the check, or show a value', () => {
    const value = (b: (typeof found)[number]) => VALUES.some((v) => v.file === b.f && v.className === b.className)
    const bare = found.filter((b) => !b.drawn && !value(b))
      .map((b) => `${b.f}:${b.line} .${b.className.split(/\s+/).join('.')} ${b.shown.join('/')}`)
    expect(bare, 'these show their glyph at no size under Field notes').toEqual([])
  })

  it('the allowlist names only buttons that are there and show a symbol', () => {
    for (const v of VALUES) {
      expect(found.filter((b) => b.f === v.file && b.className === v.className && !b.drawn), v.why).toHaveLength(1)
    }
  })
})
