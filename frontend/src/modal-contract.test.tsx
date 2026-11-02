// The modal contract, for the three dialogs that never adopted it.
//
// `backlog.aug19.stage4b.test.tsx` already enumerates every dialog that answers
// Escape — and derives that membership by grepping components for `useEscape(`,
// so that a dialog adopting the hook cannot be forgotten. That is a good guard
// pointed the wrong way: it is structurally incapable of catching a dialog that
// never adopted the hook at all. Three had not.
//
// This file is the other direction. It reads the component sources and asserts
// that anything rendering an `.overlay` scrim keeps all four halves of the
// contract — Escape, a dialog role, a scrim that closes on a press AND a
// release rather than on a bare release, and Back closes it (layers.ts) — plus
// behavioural cases for the two dialogs where the loss is a whole filled-in form.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Sidebar } from './components/Sidebar'
import type { List } from './api'
import { setBreakpoint } from './test/setup'
import { pressBack, withPrompt } from './test/back'

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
// `overlay[" ]`, not `overlay"`: a scrim with a modifier class — the mobile
// management drawer's `overlay drawer-overlay`, the settings sheet's `overlay
// set-overlay` — is still a scrim, and matching the bare name exactly is how
// both of those kept a click-to-close over a form while this test stayed green
// (2026-09-03 sweep).
async function overlayComponents(): Promise<[string, string][]> {
  const out: [string, string][] = []
  for (const [path, load] of Object.entries(sources)) {
    // Components only — the tests for them share this directory, and one that
    // quotes a scrim's markup is not a scrim.
    if (/\.test\.tsx$/.test(path)) continue
    const src = code(await load())
    if (/className="overlay[" ]/.test(src)) {
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
      const scrims = count(src, /className="overlay[" ]/g)
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
      const scrims = count(src, /className="overlay[" ]/g)
      const roles = count(src, /role="(alert)?dialog"/g)
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
      for (const m of src.matchAll(/className="overlay[" ]/g)) {
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

// ── Back: every overlay is a layer ──────────────────────────────────────────
//
// The Android client's Back closes the top layer (layers.ts), and a dialog that
// is not one would send Back out of the app with the dialog still open. Like the
// halves above, the sweep is a count: it cannot say WHICH dialog a `useLayer`
// belongs to, only that a dialog was not added without one. The behavioural
// cases beside each component's Escape cases pin the binding.

/** Every component's code, as [name, code], tests excluded. */
async function componentCode(): Promise<[string, string][]> {
  const out: [string, string][] = []
  for (const [path, load] of Object.entries(sources)) {
    if (/\.test\.tsx$/.test(path)) continue
    out.push([path.split('/').pop()!.replace('.tsx', ''), code(await load())])
  }
  return out
}

describe('every overlay is a layer Back can close', () => {
  it('registers a layer once per scrim', async () => {
    const short: string[] = []
    for (const [name, src] of await overlayComponents()) {
      const scrims = count(src, /className="overlay[" ]/g)
      const layers = count(src, /\buseLayer\s*\(/g)
      if (layers < scrims) short.push(`${name} (${scrims} scrim(s), ${layers} useLayer)`)
    }
    expect(short, `${short.join(', ')} render(s) more scrims than it registers layers for — ` +
      'Back would leave the app with the dialog still open').toEqual([])
  })

  it('gives every dialog role a layer', async () => {
    const short: string[] = []
    for (const [name, src] of await componentCode()) {
      if (/role="(alert)?dialog"/.test(src) && !/\buseLayer\s*\(/.test(src)) short.push(name)
    }
    expect(short, `${short.join(', ')} declare(s) a dialog and register no layer`).toEqual([])
  })

  // Two Escapes are not layers. FocusView has a history entry of its own, which
  // is what Back walks (App.tsx), and Sidebar's third `useEscape` is
  // GroupHeader's inline delete confirm, which the drawer's layer closes with
  // the drawer. Anything else that answers Escape must answer Back too.
  const NOT_LAYERS: Record<string, number> = { FocusView: 1, Sidebar: 1 }

  it('gives every Escape a layer, but for the two that are not layers', async () => {
    const all = await componentCode()
    for (const name of Object.keys(NOT_LAYERS)) {
      // Not vacuous: the exemption names files that exist and still answer Escape.
      const found = all.find(([n]) => n === name)
      expect(found, `${name} is not in the sweep`).toBeDefined()
      expect(count(found![1], /\buseEscape\s*\(/g), `${name} no longer answers Escape`)
        .toBeGreaterThanOrEqual(NOT_LAYERS[name]!)
    }
    const short: string[] = []
    for (const [name, src] of all) {
      const escapes = count(src, /\buseEscape\s*\(/g) - (NOT_LAYERS[name] ?? 0)
      const layers = count(src, /\buseLayer\s*\(/g)
      if (layers < escapes) short.push(`${name} (${escapes} useEscape, ${layers} useLayer)`)
    }
    expect(short, `${short.join(', ')} answer(s) Escape without being a layer`).toEqual([])
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

const mountSidebar = () => render(withPrompt(
  <Sidebar kind="list" items={[list('work', 'Work')]}
    countOf={(l) => l.open_count} onItems={() => {}} api={noopApi as never}
    hiddenIds={new Set()} onHiddenChange={() => {}} />,
))

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

describe("<Sidebar>'s edit modal and Back", () => {
  beforeEach(() => vi.clearAllMocks())

  it('closes an untouched modal on Back', async () => {
    const user = userEvent.setup()
    mountSidebar()
    await openEdit(user)
    pressBack()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('asks about a rename, and Discard writes nothing', async () => {
    const user = userEvent.setup()
    mountSidebar()
    await openEdit(user)
    await user.type(screen.getByDisplayValue('Work'), '!')

    pressBack()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Discard' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(noopApi.update).not.toHaveBeenCalled()
  })
})

describe("<Sidebar>'s phone drawer and Back", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setBreakpoint(true)
  })

  const mountDrawer = async (user: ReturnType<typeof userEvent.setup>) => {
    render(withPrompt(
      <Sidebar kind="list" items={[list('work', 'Work')]}
        countOf={(l) => l.open_count} onItems={() => {}} api={noopApi as never}
        hiddenIds={new Set()} onHiddenChange={() => {}}
        groups={[]} onGroupsChange={() => {}}
        collapsedGroups={[]} onCollapsedGroupsChange={() => {}} />,
    ))
    await user.click(screen.getByRole('button', { name: /Lists/ }))
    return screen.getByRole('dialog')
  }

  it('closes an empty drawer', async () => {
    await mountDrawer(userEvent.setup())
    pressBack()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('asks before it drops a name typed in the add field', async () => {
    const user = userEvent.setup()
    const drawer = await mountDrawer(user)
    await user.click(within(drawer).getByRole('button', { name: 'New list' }))
    await user.type(screen.getByPlaceholderText('List'), 'Groceries')

    pressBack()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // Keep editing returns to the field with the text still in it.
    await user.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(screen.getByPlaceholderText('List')).toHaveValue('Groceries')
    expect(screen.getByPlaceholderText('List')).toHaveFocus()
  })

  it('asks before it drops a group name too', async () => {
    const user = userEvent.setup()
    const drawer = await mountDrawer(user)
    await user.click(within(drawer).getByRole('button', { name: 'New group' }))
    await user.type(screen.getByPlaceholderText('Group name'), 'Errands')

    pressBack()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
  })

  it('closes the edit modal over the drawer first', async () => {
    const user = userEvent.setup()
    const drawer = await mountDrawer(user)
    await user.click(within(drawer).getByRole('button', { name: 'Edit Work' }))
    expect(screen.getAllByRole('dialog')).toHaveLength(2)

    pressBack()
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    pressBack()
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
