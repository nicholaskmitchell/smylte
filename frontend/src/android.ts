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
// The module has no side effects on import: `startAndroidHost` is called from
// main.tsx, and everything else reads the bridge when it is called.

import type { TimeFormat } from './time'

export const ANDROID_EVENT = 'smylte-android'

// The host bumps this only when a field of the env changes meaning. A field it
// adds never does, because each is read on its own.
const ENV_VERSION = 1

// What this page announces in `hello`. Only what it actually does: a host may
// act on a capability, for instance by holding the splash screen for one, so
// announcing one the page never fulfils would cost the user time.
const CAPS = 'save'

interface AndroidBridge {
  themeColour?: (hex: string) => void
  hello?: (caps: string) => unknown
  saveFile?: (name: string, mime: string, text: string) => unknown
}

/// What the host reports about the device. Every field is optional: the host
/// may be older than the page or newer. `clock24` is the phone's 12/24-hour
/// setting; App shows it while the account has none and saves it once.
export type HostEnv = { clock24?: boolean }

/** 'busy' is page-only: a save is already waiting for the picker (a second tap).
 *  The host never sends it. */
export type SaveOutcome = 'saved' | 'cancelled' | 'failed' | 'unsupported' | 'busy'

let started = false
let listening = false
let env: HostEnv | null = null
const envListeners = new Set<(env: HostEnv) => void>()
let pendingSave: ((outcome: SaveOutcome) => void) | null = null

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
