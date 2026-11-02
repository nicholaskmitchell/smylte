// Layers: the dialogs, sheets and popovers open over the app, in the order
// they opened, so the Android client's Back can close the top one.
//
// Not a synthetic Escape: `useEscape` binds the window, so one Escape there
// fires every mounted listener and closes every open layer at once, and it never
// reaches an inline field's own Escape, which stops the key at the field.
//
// Back asks before it throws input away. An edge swipe is far more often an
// accident than Escape, and the usual sequence is one Back that closes the
// keyboard and a second that would close the form. A layer that says it holds
// unsaved input gets "Discard changes?" (DiscardPrompt) instead.
//
// Only android.ts calls backTopLayer, on the host's `back` event. In a browser
// and in the desktop clients the stack is kept and never read, and Escape is
// exactly what it was.

import { useEffect, useRef, useSyncExternalStore } from 'react'
import { flushSync } from 'react-dom'

type Handlers = { onBack: () => void; unsaved: boolean }
type Entry = { id: number; handlers: { current: Handlers } }
export type DiscardAsk = { discard: () => void; keep: () => void }

let seq = 0
// Ascending id, so the top layer is the last.
const stack: Entry[] = []
const depthListeners = new Set<(depth: number) => void>()
let ask: (DiscardAsk & { layer: number }) | null = null
const askListeners = new Set<() => void>()

function emitDepth() {
  for (const fn of [...depthListeners]) {
    try {
      fn(stack.length)
    } catch (err) {
      console.error(err)
    }
  }
}

function setAsk(next: (DiscardAsk & { layer: number }) | null) {
  ask = next
  for (const fn of [...askListeners]) fn()
}

function add(entry: Entry) {
  // A new layer is almost always the newest, so scan from the end.
  let at = stack.length
  while (at > 0 && stack[at - 1]!.id > entry.id) at--
  stack.splice(at, 0, entry)
  emitDepth()
}

function remove(id: number) {
  const at = stack.findIndex((e) => e.id === id)
  if (at >= 0) stack.splice(at, 1)
  // The layer the question was about has gone, so the question has too.
  if (ask?.layer === id) setAsk(null)
  emitDepth()
}

function isField(el: Element | null): el is HTMLElement {
  return el instanceof HTMLInputElement
    || el instanceof HTMLTextAreaElement
    || el instanceof HTMLSelectElement
    || (el instanceof HTMLElement && el.isContentEditable)
}

/**
 * Register an overlay as a layer. `onBack` is what Back calls: pass the same
 * function the overlay gives `useEscape`, so Back keeps all of Escape's gating
 * (a scope prompt closes before its editor, Settings steps back one level, a
 * busy modal ignores it).
 *
 * `open` is for an overlay whose owner stays mounted and shows it with a flag;
 * one that mounts only while open leaves it out. `unsaved` says that closing
 * would throw away input, so Back asks first.
 */
export function useLayer(
  onBack: () => void,
  options: { open?: boolean; unsaved?: boolean } = {},
): void {
  const open = options.open ?? true
  // The latest handlers, read when Back arrives rather than when this layer
  // registered, so a layer never closes over a stale render.
  const handlers = useRef<Handlers>({ onBack, unsaved: false })
  handlers.current = { onBack, unsaved: options.unsaved ?? false }
  // The order is taken during render, never in an effect: a parent renders
  // before its child, so a nested layer mounted in the same commit sorts above
  // its parent, whereas effects run child-first and would get this backwards.
  // StrictMode's second mount render only skips a number.
  const order = useRef(0)
  if (open && order.current === 0) order.current = ++seq
  if (!open) order.current = 0
  const id = order.current
  useEffect(() => {
    if (id === 0) return
    add({ id, handlers })
    return () => remove(id)
  }, [id])
}

/** How many layers are open. */
export function layerDepth(): number {
  return stack.length
}

/** Call `fn` with the new depth whenever it changes. Returns the unsubscribe. */
export function onLayerDepth(fn: (depth: number) => void): () => void {
  depthListeners.add(fn)
  return () => { depthListeners.delete(fn) }
}

function askFor(entry: Entry, focused: Element | null): DiscardAsk & { layer: number } {
  return {
    layer: entry.id,
    discard: () => {
      setAsk(null)
      entry.handlers.current.onBack()
    },
    keep: () => {
      setAsk(null)
      // "Keep editing" returns to the field the question interrupted, and the
      // keyboard opening again is the point.
      if (focused instanceof HTMLElement && focused !== document.body && focused.isConnected) {
        focused.focus({ preventScroll: true })
      }
    },
  }
}

/**
 * Back: close the top layer, or ask first when it holds unsaved input. False
 * when no layer is open, so the host can correct a count that has gone stale.
 */
export function backTopLayer(): boolean {
  if (stack.length === 0) return false
  const focused = document.activeElement
  // Leave the field as a tap elsewhere would, and let what that commits render,
  // so a blur-committed setting is kept and `unsaved` is read after the commit.
  // A removed element is never blurred, so without this a half-typed value vanished.
  if (isField(focused)) flushSync(() => focused.blur())
  const top = stack[stack.length - 1]
  // The blur closed the last layer itself.
  if (!top) return true
  if (top.handlers.current.unsaved) {
    if (!ask) setAsk(askFor(top, focused))
    return true
  }
  top.handlers.current.onBack()
  return true
}

function subscribeAsk(fn: () => void): () => void {
  askListeners.add(fn)
  return () => { askListeners.delete(fn) }
}

function readAsk(): DiscardAsk | null {
  return ask
}

/** The question Back is asking, or null. For DiscardPrompt. */
export function useDiscardAsk(): DiscardAsk | null {
  return useSyncExternalStore(subscribeAsk, readAsk, readAsk)
}
