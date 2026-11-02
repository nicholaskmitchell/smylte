// Focus into a dialog and back out of it, in a real browser engine.
//
// What jsdom cannot say: that `autoFocus` and the layout effect that moves
// focus in land in the order the layer relies on in the engines a phone runs,
// and that focus really is on the opener after a close that no event caused
// (Back). Production-shaped mount (`createRoot` + `StrictMode` under a `.shell`
// host, as main.tsx does) at a phone's size, in Chromium AND WebKit.
import { StrictMode, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, expect, it, vi, afterEach } from 'vitest'
import { TaskModal } from './components/TaskModal'
import { I18nProvider } from './i18n'
import { backTopLayer } from './layers'
import { viewport } from './test/browser-measure'
import type { List, Task } from './api'

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  original_due: null, original_due_is_date: false, original_due_moved: false,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

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

function Harness({ creating }: { creating: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button id="opener" onClick={() => setOpen(true)}>Open</button>
      {open && (
        <TaskModal task={creating ? null : task()} lists={lists} defaultList="l1"
          onClose={() => setOpen(false)} onCreate={vi.fn()} onSave={vi.fn()}
          onDelete={vi.fn()} onMultiple={vi.fn()} />
      )}
    </>
  )
}

/** Mount the harness, then open the editor the way a user does: focus the
 *  opener and activate it. */
async function openEditor(creating: boolean) {
  await viewport(390, 844)
  host = document.createElement('div')
  host.className = 'shell'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(
    <StrictMode>
      <I18nProvider value="en">
        <Harness creating={creating} />
      </I18nProvider>
    </StrictMode>)
  await until('the opener mounts', () => !!document.querySelector('#opener'))
  await document.fonts.ready
  const opener = document.querySelector<HTMLElement>('#opener')!
  opener.focus()
  // Vacuity guard: a script click moves no focus in either engine, so without
  // this the opener might never have had it to give back.
  expect(document.activeElement).toBe(opener)
  opener.click()
  await until('the editor opens', () => !!document.querySelector('[role=dialog]'))
  return opener
}

const dialog = () => document.querySelector<HTMLElement>('[role=dialog]')

describe('focus into a dialog and back, at 390x844', () => {
  it('focuses the title when creating, and gives focus back on ✕', async () => {
    const opener = await openEditor(true)
    await until('the title has focus', () => document.activeElement?.id === 'task-title')
    dialog()!.querySelector<HTMLElement>('button[aria-label="Close"]')!.click()
    await until('the editor closes', () => !dialog())
    await until('the opener has focus', () => document.activeElement === opener)
  })

  it('focuses the dialog when editing, and gives focus back on Escape', async () => {
    const opener = await openEditor(false)
    await until('the dialog has focus', () => document.activeElement === dialog())
    document.activeElement!.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await until('the editor closes', () => !dialog())
    await until('the opener has focus', () => document.activeElement === opener)
  })

  it('gives focus back after Back, a close that no discrete event caused', async () => {
    const opener = await openEditor(false)
    await until('the dialog has focus', () => document.activeElement === dialog())
    backTopLayer()
    await until('the editor closes', () => !dialog())
    await until('the opener has focus', () => document.activeElement === opener)
  })
})
