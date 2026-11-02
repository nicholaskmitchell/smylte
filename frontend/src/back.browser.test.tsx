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
import { DiscardPrompt } from './components/DiscardPrompt'
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
          onClose={onClose} onCreate={vi.fn()} onSave={vi.fn()}
          onDelete={vi.fn()} onMultiple={vi.fn()} />
      </I18nProvider>
    </StrictMode>)
  await until('the editor mounts', () => !!document.querySelector('#task-title'))
  // Layers register in an effect, which can land a frame after the markup.
  await until('the editor registers its layer', () => layerDepth() === 1)
  await document.fonts.ready
  return { onClose }
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
})
