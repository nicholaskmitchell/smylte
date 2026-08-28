// The modal contract, for the three dialogs that never adopted it.
//
// `backlog.aug19.stage4b.test.tsx` already enumerates every dialog that answers
// Escape — and derives that membership by grepping components for `useEscape(`,
// so that a dialog adopting the hook cannot be forgotten. That is a good guard
// pointed the wrong way: it is structurally incapable of catching a dialog that
// never adopted the hook at all. Three had not.
//
// This file is the other direction. It reads the component sources and asserts
// that anything rendering an `.overlay` scrim keeps all three halves of the
// contract — Escape, a dialog role, and a scrim that closes on a press AND a
// release rather than on a bare release — plus behavioural cases for the two
// dialogs where the loss is a whole filled-in form.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Sidebar } from './components/Sidebar'
import type { List } from './api'

const sources = (import.meta as unknown as {
  glob: (p: string, o: object) => Record<string, () => Promise<string>>
}).glob('./components/*.tsx', { query: '?raw', import: 'default' })

/** Source with comments removed, so prose ABOUT the contract is not read as it.
 *
 *  The rules below are quoted verbatim in the comments of the components that
 *  took the advice, and a comment quoting a rule would otherwise satisfy it. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').filter((l) => !/^\s*(\/\/|\*)/.test(l)).join('\n')
}

const count = (src: string, re: RegExp) => (src.match(re) ?? []).length

/** Component sources that render a scrim, as [name, code]. */
async function overlayComponents(): Promise<[string, string][]> {
  const out: [string, string][] = []
  for (const [path, load] of Object.entries(sources)) {
    // Components only — the tests for them share this directory, and one that
    // quotes a scrim's markup is not a scrim.
    if (/\.test\.tsx$/.test(path)) continue
    const src = code(await load())
    if (/className="overlay"/.test(src)) {
      out.push([path.split('/').pop()!.replace('.tsx', ''), src])
    }
  }
  return out
}

describe('every dialog keeps the whole modal contract', () => {
  it('there are scrims to check', async () => {
    // A vacuous pass here would be worse than no test: if the class is renamed
    // the sweep finds nothing and every assertion below is a false negative.
    expect((await overlayComponents()).length).toBeGreaterThan(3)
  })

  // Counted PER SCRIM, not asked once per file. A file with two dialogs in it —
  // CalendarView has the event editor and, 200 lines up, the drag-scope prompt —
  // satisfied a `/useEscape\(/.test(src)` on the strength of the first one, so
  // the second could declare `aria-modal="true"` and answer no key at all while
  // this file reported the contract kept. That is the same shape of blind spot
  // the header criticises in the test this one complements, and it was live: the
  // scope prompt had no Escape until the count went in.
  //
  // The count is a proxy — it cannot tell WHICH dialog a given `useEscape` binds
  // to — so it is deliberately the cheap direction of the trade: satisfiable by a
  // hook bound to the wrong dialog, not satisfiable by a dialog never given one.
  // The behavioural cases below are what pin the binding, for the dialogs where
  // the loss is a whole filled-in form.
  it('answers Escape — once per scrim, not once per file', async () => {
    const short: string[] = []
    for (const [name, src] of await overlayComponents()) {
      const scrims = count(src, /className="overlay"/g)
      const escapes = count(src, /\buseEscape\s*\(/g)
      if (escapes < scrims) short.push(`${name} (${scrims} scrim(s), ${escapes} useEscape)`)
    }
    expect(short, `${short.join(', ')} render(s) more scrims than it answers Escape for — ` +
      'with aria-modal="true" and no focus trap, a keyboard user has no way out but the mouse')
      .toEqual([])
  })

  it('declares a dialog role for every scrim', async () => {
    const short: string[] = []
    for (const [name, src] of await overlayComponents()) {
      const scrims = count(src, /className="overlay"/g)
      const roles = count(src, /role="dialog"/g)
      if (roles < scrims) short.push(`${name} (${scrims} scrim(s), ${roles} role="dialog")`)
    }
    expect(short, `${short.join(', ')} render(s) a scrim with no role="dialog"`).toEqual([])
  })

  it('closes on a press AND a release on the scrim, never on a bare release', async () => {
    // A `click` whose mousedown was inside the modal is dispatched at the
    // nearest common ancestor — which IS the overlay — so the inner
    // `stopPropagation` never sees it. A bare `onClick={onClose}` therefore
    // discards the whole form when a text drag-select began in a field and
    // finished outside it. TaskModal's comment spells this out.
    //
    // Every scrim in the file is checked, not just the first one to match.
    const bare: string[] = []
    for (const [name, src] of await overlayComponents()) {
      for (const m of src.matchAll(/className="overlay"/g)) {
        const after = src.slice(m.index!, m.index! + 240)
        const down = after.indexOf('onMouseDown=')
        const up = after.indexOf('onClick=')
        if (up >= 0 && (down < 0 || down > up)) bare.push(name)
      }
    }
    expect(bare, `${bare.join(', ')} close(s) on a bare scrim onClick — use the ` +
      'onMouseDown/onClick pair TaskModal documents').toEqual([])
  })
})

// ── and the behaviour, for the one that is the only route on a phone ────────

const list = (id: string, name: string): List => ({
  id, href: `/dav/${id}/`, name, is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
}) as unknown as List

const noopApi = {
  create: vi.fn(async () => undefined),
  update: vi.fn(async () => undefined),
  remove: vi.fn(async () => undefined),
  reorder: vi.fn(async () => undefined),
}

beforeEach(() => { cleanup() })

const mountSidebar = () => render(
  <Sidebar kind="list" items={[list('work', 'Work')]}
    countOf={(l) => l.open_count} onItems={() => {}} api={noopApi as never}
    hiddenIds={new Set()} onHiddenChange={() => {}} />,
)

/** The row's ⋯ button, which is how Sidebar.test.tsx reaches this modal too. */
async function openEdit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Edit Work' }))
  return screen.queryByRole('dialog')
}

describe("<Sidebar>'s edit modal", () => {
  it('closes on Escape', async () => {
    const user = userEvent.setup()
    mountSidebar()
    const dialog = await openEdit(user)
    expect(dialog, 'could not reach the edit modal').not.toBeNull()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('does not close when a drag that began inside is released on the scrim', async () => {
    const user = userEvent.setup()
    mountSidebar()
    const dialog = await openEdit(user)
    expect(dialog).not.toBeNull()
    const scrim = dialog!.parentElement!
    // Press inside the form, release on the backdrop: ONE `click`, dispatched at
    // the overlay because that is the nearest common ancestor — which is why the
    // inner stopPropagation never saw it and the form was thrown away.
    fireEvent.mouseDown(dialog!)
    fireEvent.click(scrim)
    expect(screen.queryByRole('dialog')).toBeInTheDocument()
    // A genuine backdrop click still closes it.
    fireEvent.mouseDown(scrim)
    fireEvent.click(scrim)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
