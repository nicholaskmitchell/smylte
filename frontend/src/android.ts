// Talking to the Android client the app may be running inside.
//
// The client adds `window.SmylteAndroid` (PageBridge.kt) before the page loads,
// and answers through one DOM event. The object's presence IS the feature
// detection, as `/desktop/` is for the desktop clients: in a browser and in the
// desktop clients nothing here does anything.
//
// So is each method's presence. The web build updates on every start and the
// APK rarely, so this page runs inside older clients that lack methods, and a
// newer client sends fields and events this page ignores. Every call is
// therefore checked with `typeof` and wrapped, because an exception in the host
// reaches the page as a JS exception. Methods are always called on the bridge
// object, never detached, since the bridge looks the call up by receiver.
//
// The host sends `back` while this page reports an open layer (layers.ts): a
// dialog, sheet or popover Back should close before it leaves the page.
//
// A tap that completes a task or flips a toggle asks the host for a haptic,
// through one capture-phase click listener rather than a call at each control,
// and the app's failure toast asks for a `reject` (App.tsx). The host plays
// them only in answer to a touch, and only if the phone's touch feedback is on.
//
// On Android 12 and later the host holds the platform's splash screen until
// the page says its first view is up (`markReady`), or until its own cap.
//
// The module has no side effects on import: `startAndroidHost` is called from
// main.tsx, and everything else reads the bridge when it is called.

import { backTopLayer, layerDepth, onLayerDepth } from './layers'
import type { TimeFormat } from './time'

export const ANDROID_EVENT = 'smylte-android'

// The host bumps this only when a field of the env changes meaning. A field it
// adds never does, because each is read on its own.
const ENV_VERSION = 1

// What this page announces in `hello`. Only what it actually does: the host
// holds its splash screen for `ready` until the page calls ready()
// (markReady), so announcing a capability the page never fulfils would cost
// the user time. Every route fulfils `ready`: App when its sign-in check
// answers, the others in main.tsx as soon as they render.
const CAPS = 'back,haptics,ready,save'

interface AndroidBridge {
  themeColour?: (hex: string) => void
  hello?: (caps: string) => unknown
  layers?: (depth: number) => unknown
  haptic?: (kind: string) => unknown
  saveFile?: (name: string, mime: string, text: string) => unknown
  ready?: () => unknown
}

/// What the host reports about the device. Every field is optional: the host
/// may be older than the page or newer. `clock24` is the phone's 12/24-hour
/// setting; App shows it while the account has none and saves it once.
export type HostEnv = { clock24?: boolean }

/** The haptics the host can play; HostProtocolTest holds this list to the
 *  host's, reading it from this one line. */
export type HapticKind = 'confirm' | 'reject' | 'toggleOn' | 'toggleOff'
const HAPTIC_KINDS: readonly string[] = ['confirm', 'reject', 'toggleOn', 'toggleOff']
const isHapticKind = (s: string): s is HapticKind => HAPTIC_KINDS.includes(s)
// The controls whose click can play one. The nearest to the click decides, so
// a plain button inside a toggle's row plays nothing.
const HAPTIC_CONTROL = 'button, [role="button"], [role="checkbox"], [role="switch"], input[type="checkbox"]'

/** 'busy' is page-only: a save is already waiting for the picker (a second tap).
 *  The host never sends it. */
export type SaveOutcome = 'saved' | 'cancelled' | 'failed' | 'unsupported' | 'busy'

let started = false
let listening = false
let env: HostEnv | null = null
const envListeners = new Set<(env: HostEnv) => void>()
let pendingSave: ((outcome: SaveOutcome) => void) | null = null
// What the host was last told, and whether a report is already queued.
let reportedDepth = 0
let reportQueued = false

function bridge(): AndroidBridge | null {
  try {
    const b = (window as unknown as { SmylteAndroid?: unknown }).SmylteAndroid
    return typeof b === 'object' && b !== null ? b as AndroidBridge : null
  } catch {
    return null
  }
}

/** Whether this page is inside the Android client. */
export function isAndroidHost(): boolean {
  return bridge() !== null
}

/** The env, from `hello`'s JSON string or an event's object. Each field is read
 *  on its own, so a field of a type this page does not know is simply absent.
 *  Null only when there is no env at all: not JSON, not an object, or another
 *  `v`, which the host bumps only for a change that breaks this reading. */
export function readEnv(raw: unknown): HostEnv | null {
  let value = raw
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value)
    } catch {
      return null
    }
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const o = value as Record<string, unknown>
  if (o.v !== ENV_VERSION) return null
  const out: HostEnv = {}
  if (typeof o.clock24 === 'boolean') out.clock24 = o.clock24
  return out
}

/** Tell the host how many layers are open. Always sends, because repairing a
 *  count the host holds wrongly needs a report even of what was reported before. */
function sendLayers(depth: number) {
  const b = bridge()
  if (!b || typeof b.layers !== 'function') return
  try {
    b.layers(depth)
    reportedDepth = depth
  } catch {
    // The host failed, so Back keeps its route and the next change tries again.
  }
}

/** Report the depth once per burst: a dialog closing as another opens, and
 *  StrictMode's double effects, come as bursts and need one report between them. */
function queueLayers() {
  if (reportQueued) return
  reportQueued = true
  queueMicrotask(() => {
    reportQueued = false
    const d = layerDepth()
    if (d !== reportedDepth) sendLayers(d)
  })
}

function onEvent(e: Event) {
  const d = (e as CustomEvent).detail as unknown
  if (typeof d !== 'object' || d === null) return
  const msg = d as Record<string, unknown>
  if (msg.type === 'env') {
    // A malformed env keeps the previous one rather than forgetting it.
    const next = readEnv(msg.env)
    if (!next) return
    env = next
    for (const fn of [...envListeners]) {
      try {
        fn(next)
      } catch (err) {
        console.error(err)
      }
    }
  } else if (msg.type === 'saved') {
    const done = pendingSave
    if (!done) return
    pendingSave = null
    done(msg.outcome === 'saved' || msg.outcome === 'cancelled' ? msg.outcome : 'failed')
  } else if (msg.type === 'back') {
    // The host sends this only while this page said a layer is open, so none
    // open means its count is stale, for instance a report lost across a
    // document change. Saying 0 lets the next Back walk history or leave.
    let handled = true
    try {
      handled = backTopLayer()
    } catch (err) {
      console.error(err)
    }
    if (!handled) sendLayers(0)
  }
  // Any other type comes from a newer host and is none of this page's business.
}

function listen() {
  if (listening) return
  listening = true
  window.addEventListener(ANDROID_EVENT, onEvent)
}

/** Listen for the host and read its env. Called once from main.tsx, before
 *  anything renders: `hello` is synchronous, so the host's facts are known on
 *  the first render. A no-op outside the Android client. */
export function startAndroidHost(): void {
  if (started) return
  const b = bridge()
  if (!b) return
  started = true
  // Before hello, so an env change sent in between is not lost.
  listen()
  if (typeof b.hello === 'function') {
    try {
      env = readEnv(b.hello(CAPS))
    } catch {
      env = null
    }
  }
  if (typeof b.layers === 'function') onLayerDepth(queueLayers)
  // Capturing on the document runs before React's own listeners, so the
  // control still holds the state the click changes from.
  if (typeof b.haptic === 'function') document.addEventListener('click', onClickHaptic, true)
}

/** What the host said about the device, or null when it said nothing (a
 *  browser, an older client, or an env this page cannot read). */
export function hostEnv(): HostEnv | null {
  return env
}

/** The phone's clock as the app's setting, or null when the host has not
 *  said (a browser, a desktop client, a client older than `hello`, or an env
 *  this page cannot read). */
export function hostClock(): TimeFormat | null {
  const c = env?.clock24
  return c === undefined ? null : c ? '24h' : '12h'
}

/** Call `fn` whenever the host sends a new env. Returns the unsubscribe. */
export function onHostEnv(fn: (env: HostEnv) => void): () => void {
  envListeners.add(fn)
  return () => { envListeners.delete(fn) }
}

/** Whether the host can save a file through Android's own dialog. */
export function canSaveFiles(): boolean {
  return typeof bridge()?.saveFile === 'function'
}

/** Tell the host the page's first view is up, so it stops holding the
 *  platform's splash screen. App says it once, when its sign-in check first
 *  answers; the routes without a sign-in say it from main.tsx as they render.
 *  A no-op in a browser, in a desktop client, and in a client without
 *  `ready`, which ends the splash when the page has loaded instead.
 *
 *  It is called at once, never from a frame callback: while the splash is
 *  held the window does not draw, and frames may not come. */
export function markReady(): void {
  const b = bridge()
  if (!b || typeof b.ready !== 'function') return
  try {
    b.ready()
  } catch {
    // The host ends the splash by itself at its cap.
  }
}

/** Ask the host for a haptic. A no-op outside the client and in a client
 *  without `haptic`. The host decides whether it plays: only after a touch, and
 *  only with the phone's touch feedback on. */
export function haptic(kind: HapticKind): void {
  const b = bridge()
  if (!b || typeof b.haptic !== 'function') return
  try {
    b.haptic(kind)
  } catch {
    // A haptic is never worth an error in the page.
  }
}

/** The haptic a click on `target` plays, or null for none.
 *
 *  It is read in the capture phase, before the app's handlers, so the control
 *  still shows the state the click changes from. The checkbox input is the
 *  exception: the browser has already flipped `checked`.
 *
 *  The rules, in order: `data-haptic` names a completion that is no toggle (the
 *  focus view's Done); a task's `.check` going on is `confirm`; anything that
 *  tells a screen reader it is a toggle plays the state it goes to. A disabled
 *  control plays nothing, and so does any other button. A button that cycles
 *  values (the clock row) is not a toggle to a screen reader either. */
export function hapticFor(target: EventTarget | null): HapticKind | null {
  if (!(target instanceof Element)) return null
  const el = target.closest(HAPTIC_CONTROL)
  if (!el) return null
  if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return null
  const named = el.getAttribute('data-haptic')
  if (named !== null && isHapticKind(named)) return named
  if (el instanceof HTMLInputElement) return el.checked ? 'toggleOn' : 'toggleOff'
  const role = el.getAttribute('role')
  const state = el.getAttribute(role === 'checkbox' || role === 'switch' ? 'aria-checked' : 'aria-pressed')
  if (state === null) return null
  const was = state === 'true'
  if (el.classList.contains('check')) return was ? 'toggleOff' : 'confirm'
  return was ? 'toggleOff' : 'toggleOn'
}

function onClickHaptic(e: Event) {
  const kind = hapticFor(e.target)
  if (kind) haptic(kind)
}

/** Save text through Android's save dialog. Resolves when the user has chosen
 *  and the host has written, or not.
 *
 *  There is no timeout: the dialog can stay open for minutes, the host answers
 *  every accepted request in the same document, and a new document starts with
 *  fresh module state. */
export function saveTextFile(name: string, mime: string, text: string): Promise<SaveOutcome> {
  const b = bridge()
  if (!b || typeof b.saveFile !== 'function') return Promise.resolve('unsupported')
  if (pendingSave) return Promise.resolve('busy')
  // The listener is installed here too, so a save works even where
  // startAndroidHost has not run.
  listen()
  let accepted = false
  try {
    accepted = b.saveFile(name, mime, text) === true
  } catch {
    accepted = false
  }
  if (!accepted) return Promise.resolve('failed')
  return new Promise<SaveOutcome>((resolve) => { pendingSave = resolve })
}
