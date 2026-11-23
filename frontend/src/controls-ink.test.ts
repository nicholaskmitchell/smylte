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
