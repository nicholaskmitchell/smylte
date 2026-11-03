// "Discard changes?" (DiscardPrompt), in a real browser engine.
//
// What jsdom cannot say about it: that it PAINTS above the editor it asks
// about. `.discard-overlay` wins its z-index in the real cascade or the prompt
// opens behind the form and Back looks dead, and nothing in a suite that
// applies no CSS can tell. Production-shaped mount (`createRoot` + `StrictMode`
// under a `.shell` host, as main.tsx does) at a phone's size, in Chromium AND
// WebKit.
import { StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, expect, it, vi, afterEach } from 'vitest'
import { userEvent } from 'vitest/browser'
import { DiscardPrompt } from './components/DiscardPrompt'
import { Sidebar } from './components/Sidebar'
import { TaskModal } from './components/TaskModal'
import { I18nProvider } from './i18n'
import { backTopLayer, layerDepth } from './layers'
import { viewport } from './test/browser-measure'
import type { List } from './api'

const lists: List[] = [{
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
}]

let root: Root | null = null
let host: HTMLElement | null = null
afterEach(() => { root?.unmount(); host?.remove(); root = null; host = null })

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Poll rather than assume a frame count: the engines differ in how soon a
 *  commit and an animation frame land. */
async function until(what: string, ok: () => boolean) {
  for (let i = 0; i < 200 && !ok(); i++) await sleep(10)
  expect(ok(), what).toBe(true)
}

const prompt = () => document.querySelector('.discard-overlay')
const button = (name: string) =>
  [...document.querySelectorAll('.discard-overlay button')]
    .find((b) => b.textContent === name) as HTMLElement

async function mountEditor() {
  await viewport(390, 844)
  const onClose = vi.fn()
  const onCreate = vi.fn()
  host = document.createElement('div')
  host.className = 'shell'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(
    <StrictMode>
      <I18nProvider value="en">
        {/* BEFORE the editor in the document, so that only the stylesheet's
            z-index, and not source order, can put the prompt on top. */}
        <DiscardPrompt />
        <TaskModal task={null} lists={lists} defaultList="l1" initialTitle="Buy milk"
          onClose={onClose} onCreate={onCreate} onSave={vi.fn()}
          onDelete={vi.fn()} onMultiple={vi.fn()} />
      </I18nProvider>
    </StrictMode>)
  await until('the editor mounts', () => !!document.querySelector('#task-title'))
  // Layers register in an effect, which can land a frame after the markup.
  await until('the editor registers its layer', () => layerDepth() === 1)
  await document.fonts.ready
  return { onClose, onCreate }
}

/** The lists Sidebar in its phone form (a trigger bar and a drawer), with
 *  DiscardPrompt beside it as App mounts it. `update` is the spy. */
async function mountSidebar() {
  await viewport(390, 844)
  const update = vi.fn(async (id: string, body: { name?: string }) => ({ ...lists[0], id, ...body }))
  const api = { create: vi.fn(), update, remove: vi.fn(), reorder: vi.fn() }
  host = document.createElement('div')
  host.className = 'shell'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(
    <StrictMode>
      <I18nProvider value="en">
        <DiscardPrompt />
        <Sidebar kind="list" items={lists} countOf={() => 0} onItems={vi.fn()} api={api} />
      </I18nProvider>
    </StrictMode>)
  await until('the trigger bar mounts', () => !!document.querySelector('.side-mobiletrigger'))
  await document.fonts.ready
  return { update }
}

const centre = (el: Element) => {
  const r = el.getBoundingClientRect()
  return [r.left + r.width / 2, r.top + r.height / 2] as const
}

describe('"Discard changes?" over the editor, at 390x844', () => {
  it('paints above the editor it asks about', async () => {
    await mountEditor()
    backTopLayer()
    await until('the prompt opens', () => !!prompt())
    // Let the modal's entrance animation settle before hit-testing.
    await new Promise(requestAnimationFrame)
    await sleep(300)

    for (const name of ['Keep editing', 'Discard']) {
      const el = button(name)
      expect(el, `no ${name} button`).toBeTruthy()
      const [x, y] = centre(el)
      const hit = document.elementFromPoint(x, y)
      expect(hit === el || el.contains(hit), `${name} is covered by ${hit?.className}`).toBe(true)
    }

    // The editor's own title field sits under the scrim, not over it.
    const [x, y] = centre(document.querySelector('#task-title')!)
    const over = document.elementFromPoint(x, y)
    expect(over?.closest('.discard-overlay'), `the title field is hit through the prompt: ${over?.className}`)
      .not.toBeNull()
  })

  it('answers Escape at the prompt by closing only the prompt', async () => {
    const { onClose } = await mountEditor()
    backTopLayer()
    await until('the prompt opens', () => !!prompt())
    const keep = button('Keep editing')
    keep.focus()
    expect(document.activeElement).toBe(keep)

    keep.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await until('the prompt closes', () => !prompt())
    expect(onClose).not.toHaveBeenCalled()
    expect(document.querySelector('#task-title')).not.toBeNull()
  })

  it('ends at the right depth under StrictMode', async () => {
    await mountEditor()
    expect(layerDepth()).toBe(1)
    backTopLayer()
    await until('the prompt opens', () => !!prompt())
    expect(layerDepth()).toBe(2)
    button('Keep editing').click()
    await until('the prompt closes', () => !prompt())
    expect(layerDepth()).toBe(1)
  })

  // On a phone "Keep editing" is a bottom sheet's button exactly over the
  // editor's own Save or Add, and the question unmounts on the first tap. The
  // second tap of a double tap then landed on the editor's primary button.
  // `.discard-shield` takes taps for SHIELD_MS after the question closes; only
  // real input at one screen point, in the real cascade, can tell.
  it('does not save the list editor when "Keep editing" is double-tapped', async () => {
    const { update } = await mountSidebar()
    ;(document.querySelector('.side-mobiletrigger') as HTMLElement).click()
    await until('the drawer opens', () => !!document.querySelector('.drawer'))
    ;(document.querySelector('[aria-label="Edit Work"]') as HTMLElement).click()
    const dialog = () => document.querySelector('[role="dialog"][aria-label="List"]')
    await until('the editor opens', () => !!dialog())
    const name = dialog()!.querySelector('input.input') as HTMLInputElement
    await userEvent.fill(name, 'Workflow')
    expect(name.value).toBe('Workflow')
    await until('the editor registers its layer', () => layerDepth() === 2)

    backTopLayer()
    await until('the prompt opens', () => !!prompt())
    // Let the modal's entrance animation settle before the pointer lands.
    await new Promise(requestAnimationFrame)
    await sleep(300)

    await userEvent.dblClick(button('Keep editing'))
    await until('the prompt closes', () => !prompt())

    expect(update).not.toHaveBeenCalled()
    expect(dialog(), 'the editor closed').not.toBeNull()
    expect((dialog()!.querySelector('input.input') as HTMLInputElement).value).toBe('Workflow')
    expect(document.activeElement).toBe(dialog()!.querySelector('input.input'))

    // The shield is for a moment, not for good: a deliberate tap still saves.
    await new Promise((r) => setTimeout(r, 500))
    const save = [...dialog()!.querySelectorAll('button')].find((b) => b.textContent === 'Save')!
    await userEvent.click(save)
    await until('the editor saves', () => update.mock.calls.length > 0)
    expect(update).toHaveBeenCalledWith('l1', { name: 'Workflow' })
  })

  it('does not create the task when "Keep editing" is double-tapped', async () => {
    const { onClose, onCreate } = await mountEditor()
    backTopLayer()
    await until('the prompt opens', () => !!prompt())
    await new Promise(requestAnimationFrame)
    await sleep(300)

    await userEvent.dblClick(button('Keep editing'))
    await until('the prompt closes', () => !prompt())

    expect(onCreate).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(document.querySelector('#task-title')).not.toBeNull()
  })
})

/** The lists Sidebar under the Classic frame's `.work`, at the given size. */
async function mountClassicSidebar(width: number, height: number) {
  await viewport(width, height)
  host = document.createElement('div')
  host.className = 'shell'
  host.dataset.layout = 'classic'
  document.body.appendChild(host)
  const work = document.createElement('div')
  work.className = 'work'
  host.appendChild(work)
  root = createRoot(work)
  root.render(
    <StrictMode>
      <I18nProvider value="en">
        <Sidebar kind="list" items={lists} countOf={() => 0} onItems={vi.fn()}
          api={{ create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() }} />
      </I18nProvider>
    </StrictMode>)
  return work
}

const editorModal = () => document.querySelector('.overlay [role="dialog"][aria-label="List"]')
const prop = (el: Element, name: string) => getComputedStyle(el).getPropertyValue(name).trim()

// The editor no longer sits inside `.side`, so that a fold cannot unmount it,
// and it carries what it used to inherit there through `.side-editor`. Without
// that, the Classic desktop editor drew its focus rings 2px outside each
// control instead of inside, and filled a hovered Delete with --paper.
describe('the list editor keeps the look of where it is drawn', () => {
  it('beside the desktop sidebar, the sidebar\'s focus offset and hover fill', async () => {
    await mountClassicSidebar(1200, 800)
    await until('the desktop sidebar mounts', () => !!document.querySelector('.side:not(.drawer)'))
    ;(document.querySelector('[aria-label="Edit Work"]') as HTMLElement).click()
    await until('the editor opens', () => !!editorModal())
    const side = document.querySelector('.side')!
    expect(prop(side, '--focus-offset')).toBe('-2px')
    expect(prop(editorModal()!, '--focus-offset')).toBe('-2px')
    expect(prop(editorModal()!, '--ghost-hover-bg')).toBe(prop(side, '--ghost-hover-bg'))
  })

  it('on a phone, what the page around it has, as before', async () => {
    const work = await mountClassicSidebar(390, 844)
    await until('the trigger bar mounts', () => !!document.querySelector('.side-mobiletrigger'))
    ;(document.querySelector('.side-mobiletrigger') as HTMLElement).click()
    await until('the drawer opens', () => !!document.querySelector('.side.drawer [aria-label="Edit Work"]'))
    ;(document.querySelector('.side.drawer [aria-label="Edit Work"]') as HTMLElement).click()
    await until('the editor opens', () => !!editorModal())
    expect(prop(editorModal()!, '--focus-offset')).toBe(prop(work, '--focus-offset'))
    expect(prop(editorModal()!, '--ghost-hover-bg')).toBe(prop(work, '--ghost-hover-bg'))
  })
})

