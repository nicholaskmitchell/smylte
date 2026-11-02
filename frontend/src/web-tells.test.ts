// What gives the page away inside the Android WebView, checked as text here and
// measured in `web-tells.browser.test.tsx`.
//
// The unit project runs with `css: false`, so a rule in a stylesheet is only
// visible to a test that reads the file. What is asserted is the shape of the
// fix rather than its effect: the controls opt out of selection and the
// content does not, a field always selects, pinch zoom is left to the browser,
// and no source opens a native dialog, which each client draws on its own and
// which blocks the page.

import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8')
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')

const rulesOf = (css: string) =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }))

// Split a selector list on the commas outside parentheses, so
// `:where(a, b)` stays one item.
const topLevelSplit = (sel: string) => {
  const items: string[] = []
  let depth = 0
  let from = 0
  for (let i = 0; i < sel.length; i++) {
    const c = sel[i]
    if (c === '(') depth++
    else if (c === ')') depth--
    else if (c === ',' && depth === 0) { items.push(sel.slice(from, i)); from = i + 1 }
  }
  items.push(sel.slice(from))
  return items.map((s) => s.trim())
}

// Every selector a rule really lists, with `:where(…)` and `:is(…)` unwrapped,
// so an item added inside one is checked like any other. Splitting on the top
// level alone saw the whole `:where(…)` as one opaque item.
const flatten = (sel: string): string[] =>
  topLevelSplit(sel).flatMap((item) => {
    const m = /^:(?:where|is)\(([\s\S]*)\)$/.exec(item)
    return m ? flatten(m[1]) : [item]
  })

// What the declaration lands on: the last compound of a selector, without its
// `:not(…)` exceptions, as simple selectors (`.a.b` gives `.a` and `.b`). The
// subject rather than every compound, because `.modal button` is about buttons.
const subjectOf = (sel: string): string[] => {
  const noNot = sel.replace(/:not\((?:[^()]|\([^()]*\))*\)/g, '')
  const last = noNot.trim().split(/\s*[\s>+~]\s*/).pop() ?? ''
  return last.match(/:root|\*|[.#]?[A-Za-z_][\w-]*|\[[^\]]*\]/g) ?? []
}

const UNSELECTABLE = /(^|[\s;])user-select:\s*none/
const SELECTABLE = /(^|[\s;])user-select:\s*text/

describe('a long press selects content, never a control\'s label', () => {
  const tokens = rulesOf(strip(read('src/styles/tokens.css')))

  it('tokens.css makes the controls unselectable', () => {
    const rules = tokens.filter((r) => UNSELECTABLE.test(r.body))
    expect(rules).toHaveLength(1)
    expect(rules[0].body).toMatch(/-webkit-user-select:\s*none/)
    for (const control of ['button', '[role="tab"]', '[role="checkbox"]', '[role="switch"]',
      '[role="menuitem"]', 'label']) {
      expect(rules[0].sel).toContain(control)
    }
  })

  it('and leaves the pressable rows that hold a title selectable', () => {
    const sel = tokens.find((r) => UNSELECTABLE.test(r.body))!.sel
    expect(sel).not.toContain('[role="button"]')
    expect(sel).toContain(':not(.task-main)')
    expect(sel).toContain(':not(.agenda-ev)')
    expect(sel).toContain(':not(.focus-pick)')
    // The exceptions are by class name, so a rename would silently kill them.
    expect(read('src/components/TasksView.tsx')).toMatch(/<button className="task-main"/)
    expect(read('src/components/DayPopover.tsx')).toMatch(/<button className="agenda-ev"/)
    expect(read('src/components/FocusView.tsx')).toMatch(/<button type="button" className="focus-pick"/)
  })

  it('keeps every field selectable', () => {
    const rule = tokens.find((r) => SELECTABLE.test(r.body) && /-webkit-user-select:\s*text/.test(r.body))
    expect(rule).toBeDefined()
    expect(topLevelSplit(rule!.sel).sort()).toEqual(['input', 'textarea'])
  })

  it('never makes a whole surface or a content row unselectable', () => {
    const never = ['html', 'body', '*', ':root', '#root', '.shell', '.modal', '.overlay',
      'input', 'textarea', '.task-body', '.day-card-body', '.cal-ev', '.cal-task',
      '.task-main', '.agenda-ev']
    let seen = 0
    for (const file of ['tokens', 'app', 'classic', 'layout', 'display', 'fonts']) {
      for (const r of rulesOf(strip(read(`src/styles/${file}.css`)))) {
        if (!/user-select:\s*none/.test(r.body)) continue
        seen++
        for (const sel of flatten(r.sel)) {
          for (const simple of subjectOf(sel)) expect(never, `${file}.css: ${sel}`).not.toContain(simple)
        }
      }
    }
    // The new rule, `.brand`, `.focus[data-float]` and `.display`.
    expect(seen).toBeGreaterThanOrEqual(4)
  })
})

describe('page zoom stays the browser\'s to give', () => {
  it('index.html leaves pinch zoom on', () => {
    const m = /<meta\s+name="viewport"\s+content="([^"]*)"/.exec(read('index.html'))
    expect(m).not.toBeNull()
    expect(m![1]).not.toMatch(/user-scalable/)
    expect(m![1]).not.toMatch(/maximum-scale/)
  })
})

describe('no native dialogs', () => {
  it('no source calls alert, confirm or prompt', () => {
    const files = readdirSync('src', { recursive: true, encoding: 'utf8' })
      .map((f) => f.replace(/\\/g, '/'))
      .filter((f) => /\.tsx?$/.test(f)
        && !/\.test\.tsx?$/.test(f) && !/\.browser\.test\.tsx$/.test(f)
        && !/\.d\.ts$/.test(f) && !f.startsWith('test/'))
    const call = /(?:\b(?:window|globalThis|self)\.|(?<![.\w$]))(?:alert|confirm|prompt)\s*\(/
    const offenders = files.filter((f) => {
      const code = read(`src/${f}`).replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1')
      return call.test(code)
    })
    expect(offenders, `native dialogs in: ${offenders.join(', ')}`).toEqual([])
    // Vacuity: the walk found the tree, and the file that used to alert.
    expect(files.length).toBeGreaterThan(50)
    expect(files).toContain('components/AppearancePanel.tsx')
  })
})
