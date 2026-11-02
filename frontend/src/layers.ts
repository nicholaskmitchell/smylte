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
// Only android.ts calls backTopLayer, on the host's `back` event. Back never
// arrives in a browser or in the desktop clients, so Escape is exactly what it
// was there.
//
// Layers also carry focus, in every client, because that is plain dialog
// behaviour and not Android's: a dialog takes focus when it opens and gives it
// back to what opened it when it closes.

import { useEffect, useLayoutEffect, useRef, useSyncExternalStore, type RefObject } from 'react'
import { flushSync } from 'react-dom'

type Handlers = { onBack: () => void; unsaved: boolean }
/** What had focus when a layer opened, and the layer that was on top then. */
type Origin = { from: HTMLElement | null; under: Entry | null }
type Entry = Origin & {
  id: number
  handlers: { current: Handlers }
  /** The layer's own element as its last commit left it; null when it has none. */
  box: { current: HTMLElement | null }
}
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

/** What has focus, or null when only the page itself does. */
function focusedElement(): HTMLElement | null {
  const el = document.activeElement
  return el instanceof HTMLElement && el !== document.body ? el : null
}

function isOpen(entry: Entry): boolean {
  return stack.some((e) => e.id === entry.id)
}

/** Focus `el` if it can take focus without opening a keyboard; say whether it did. */
function tryFocus(el: HTMLElement | null): boolean {
  // `isField` is a type guard, and narrowing through it would leave `el` as
  // `never` below; only the answer matters here.
  const field: boolean = el !== null && isField(el as Element)
  if (!el || !el.isConnected || field) return false
  el.focus({ preventScroll: true })
  return document.activeElement === el
}

/**
 * Give focus back after `closed` has gone. This runs after the DOM is removed,
 * which is why focus being on `body` means that it went with the layer; focus
 * anywhere else was put there on purpose by whatever closed the layer, and
 * stays.
 *
 * A text field is never refocused, because on a phone that opens the keyboard.
 * When the opener has gone too, the chain goes through `under`, the layer that
 * was on top when this one opened: Settings hands over to Appearance, and
 * DayPopover hands over to EventModal, both in a single commit. When the opener
 * is gone and the layer below is still open, focus stays inside that layer
 * rather than falling to the page.
 */
function giveBack(closed: Entry): void {
  const now = document.activeElement
  if (now && now !== document.body) return
  // StrictMode's rehearsal unmount, not a close: the element is still there.
  if (closed.box.current?.isConnected) return
  for (let e: Entry | null = closed; e; e = e.under) {
    if (tryFocus(e.from)) return
    const below = e.under
    if (below && isOpen(below)) {
      tryFocus(below.box.current)
      return
    }
  }
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
 *
 * `dialog` is the overlay's own element, the one with the dialog role and
 * `tabIndex={-1}`. Focus moves to it when nothing inside took focus as the
 * layer opened, and it must leave the document when the layer closes. A
 * disclosure popover passes none and keeps focus on its button.
 */
export function useLayer(
  onBack: () => void,
  options: { open?: boolean; unsaved?: boolean; dialog?: RefObject<HTMLElement> } = {},
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
  // What had focus is captured here too, in the render that opens the layer.
  // React focuses an `autoFocus` field during the commit (`commitMount`),
  // before any effect runs, so an effect would only ever find the dialog's own
  // field; and `useMemo` would be a side effect that React may recompute.
  const origin = useRef<Origin>({ from: null, under: null })
  if (open && order.current === 0) {
    order.current = ++seq
    origin.current = { from: focusedElement(), under: stack[stack.length - 1] ?? null }
  }
  if (!open) order.current = 0
  const id = order.current
  const box = useRef<HTMLElement | null>(null)
  // On every commit, so that a flag-opened layer's element is gone once the
  // layer closes.
  useLayoutEffect(() => { box.current = options.dialog?.current ?? null })
  // A layout effect runs after its descendants' `autoFocus`, so focus already
  // inside means that a field took it. Moving focus in otherwise lets a screen
  // reader start reading inside the dialog, and is required alongside
  // `aria-modal`.
  useLayoutEffect(() => {
    const el = box.current
    if (id === 0 || !el || el.contains(document.activeElement)) return
    el.focus({ preventScroll: true })
  }, [id])
  useEffect(() => {
    if (id === 0) return
    const entry: Entry = { id, handlers, box, ...origin.current }
    add(entry)
    return () => {
      remove(id)
      giveBack(entry)
    }
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
