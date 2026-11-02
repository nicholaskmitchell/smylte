// What a screen reader is told by controls that are drawn as a symbol.
//
// TalkBack reads a button's accessible name, and the accessible-name algorithm
// takes a button's CONTENT before its `title`: `<button title="Toggle
// complete">✓</button>` is named "✓", and the title is only its description.
// So a symbol button without an `aria-label` is unlabelled, and a `title` does
// not fix that. (Checked with dom-accessibility-api, the library the testing
// library's `name` queries use.)
//
// Like modal-contract.test.tsx, this reads the component sources, so that a
// button added later cannot be forgotten.

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const sources = (import.meta as unknown as {
  glob: (p: string[], o: object) => Record<string, () => Promise<string>>
}).glob(['./components/*.tsx', './*.tsx'], { query: '?raw', import: 'default' })

// Copied from modal-contract.test.tsx: source with comments removed, so prose
// about a rule is not read as the rule.
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').filter((l) => !/^\s*(\/\/|\*)/.test(l)).join('\n')
}

type Button = { file: string; line: number; attrs: string; body: string }

/** Every `<button …>…</button>` in `src` that has children, with its attributes
 *  and its text. The tag ends at the first `>` outside braces: an arrow's `=>`
 *  always sits inside `{…}`. */
function buttons(file: string, raw: string): Button[] {
  const src = code(raw)
  const out: Button[] = []
  for (const m of src.matchAll(/<button\b/g)) {
    let depth = 0
    let at = m.index! + m[0].length
    for (; at < src.length; at++) {
      const ch = src[at]
      if (ch === '{') depth++
      else if (ch === '}') depth--
      else if (ch === '>' && depth === 0) break
    }
    if (src[at - 1] === '/') continue
    const tag = src.slice(m.index!, at + 1)
    const end = src.indexOf('</button>', at)
    if (end < 0) continue
    // The comment-free source has its own line numbers, so find the tag in the
    // original to say where it is.
    const line = raw.slice(0, Math.max(raw.indexOf(tag), 0)).split('\n').length
    out.push({
      file, line, attrs: tag.slice(m[0].length, -1), body: src.slice(at + 1, end),
    })
  }
  return out
}

/** The text a button shows, as far as a source can tell. An expression of string
 *  literals, such as `{open ? '◉' : '◌'}`, stands for its literals. A condition
 *  such as `{count && <span>…</span>}` is an optional extra and is dropped. Any
 *  other `{…}` is a value that is shown, so it stands for a letter: a button
 *  that has one is named by it. Then the tags go, so `<span>▸</span>` is `▸`. A
 *  body is read this way because a glyph is often wrapped in a span or a
 *  ternary, and a test that gave up on every `{` or `<` could not see those
 *  buttons. */
function shown(body: string): string {
  let out = ''
  for (let at = 0; at < body.length; at++) {
    if (body[at] !== '{') {
      out += body[at]
      continue
    }
    let depth = 0
    const from = at
    for (; at < body.length; at++) {
      if (body[at] === '{') depth++
      else if (body[at] === '}' && --depth === 0) break
    }
    const expr = body.slice(from + 1, at)
    const literals = [...expr.matchAll(/'([^']*)'|"([^"]*)"/g)].map((m) => m[1] ?? m[2])
    if (/&&|\|\||<|=>/.test(expr)) continue
    out += /\?[^:]*:/.test(expr) && literals.length ? literals.join('') : 'x'
  }
  return out.replace(/<[^>]*>/g, '').trim()
}

async function allButtons(): Promise<Button[]> {
  const out: Button[] = []
  for (const [path, load] of Object.entries(sources)) {
    if (/\.test\.tsx?$/.test(path)) continue
    out.push(...buttons(path.replace('./', 'src/'), await load()))
  }
  return out
}

describe('buttons drawn as a symbol', () => {
  it('names every button whose only content is a symbol', async () => {
    const symbols = (await allButtons()).filter((b) => {
      const body = shown(b.body)
      return body.length >= 1 && body.length <= 4 && !/[\p{L}\p{N}{}<]/u.test(body)
    })
    // Not vacuous: if the parser stops finding buttons every case passes.
    expect(symbols.length).toBeGreaterThan(30)
    const unnamed = symbols.filter((b) => !/\baria-label(ledby)?=/.test(b.attrs))
      .map((b) => `${b.file}:${b.line} (${shown(b.body)})`)
    expect(unnamed, `${unnamed.join(', ')} -- a title does not name a button ` +
      'that has content, so TalkBack reads the symbol; add an aria-label').toEqual([])
  })

  it('gives every task check its pressed state', async () => {
    const checks = (await allButtons())
      .filter((b) => /className=\{?[`"']check[\s`"']/.test(b.attrs))
    expect(checks.length).toBeGreaterThanOrEqual(4)
    const bare = checks.filter((b) => !/\baria-pressed=/.test(b.attrs))
      .map((b) => `${b.file}:${b.line}`)
    expect(bare, `${bare.join(', ')} -- a check without aria-pressed does not say ` +
      'whether the task is done').toEqual([])
  })
})

describe('focus on a dialog', () => {
  it('draws no ring round a dialog that took focus itself', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')
    expect(css).toContain(
      ':is([role="dialog"], [role="alertdialog"])[tabindex="-1"]:focus-visible { outline: none; }')
  })
})
