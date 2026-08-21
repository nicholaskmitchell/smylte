import { afterEach } from 'vitest'
import '@testing-library/jest-dom/vitest'

// jsdom has no matchMedia, and `useIsMobile` — which decides which layout the
// entire app renders — is built on it. This stub is what every suite gets.
//
// It used to answer `matches: false` for every query with a NO-OP
// `addEventListener`, which made the breakpoint permanently desktop and
// permanently frozen: a suite could not cross it without replacing the stub
// wholesale, and four separate copies of that replacement grew around the tree,
// three of them inert in the same way. Worse, the no-op listener meant the
// change path — a rotation or a resize crossing the breakpoint WITHOUT
// remounting anything, which is the only reason `useIsMobile` has an effect at
// all — could not be driven against a real component by anyone.
//
// So the shared stub keeps a real listener registry and the breakpoint is
// settable. Default is still desktop, so every existing suite sees exactly what
// it saw before.

type Listener = (e: MediaQueryListEvent) => void

const listeners = new Set<Listener>()
let matches = false

/** Cross the mobile breakpoint, notifying everything currently subscribed.
 *
 *  Iterates a COPY: a listener that unsubscribes when it fires (React's cleanup
 *  does, on the re-render this very call provokes) would otherwise mutate the
 *  set mid-iteration. Callers wrap this in `act()` when a component is
 *  listening. */
export function setBreakpoint(next: boolean): void {
  matches = next
  for (const fn of [...listeners]) fn({ matches: next } as MediaQueryListEvent)
}

/** How many listeners are subscribed — lets a suite assert that unmounting
 *  actually unsubscribes, rather than trusting it. */
export function breakpointListeners(): number {
  return listeners.size
}

/** Back to desktop, nothing subscribed, and the SHARED stub reinstalled.
 *
 *  Reinstalling is the part that matters. Four suites replace
 *  `window.matchMedia` wholesale with a local inert stub and put back a
 *  different local one afterwards, so without this a test that merely reset the
 *  state would still be handing components whichever stub ran last — they would
 *  subscribe to a no-op `addEventListener` and `setBreakpoint` would reach
 *  nobody. Measured: the rotation case passes alone and fails whole-file,
 *  `breakpointListeners()` stuck at 0. */
export function resetBreakpoint(): void {
  matches = false
  listeners.clear()
  installStub()
}

function installStub(): void {
  // A getter, not a captured boolean: `useIsMobile` calls `matchMedia` once on
  // mount and once in its effect, and both must see the CURRENT breakpoint.
  window.matchMedia = ((query: string) => ({
    get matches() { return matches },
    media: query,
    onchange: null,
    addEventListener: (_type: string, fn: Listener) => { listeners.add(fn) },
    removeEventListener: (_type: string, fn: Listener) => { listeners.delete(fn) },
    addListener: (fn: Listener) => { listeners.add(fn) },
    removeListener: (fn: Listener) => { listeners.delete(fn) },
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

installStub()

// Reset the breakpoint state only — deliberately NOT `window.matchMedia`
// itself. Several suites install their own stub in `beforeEach` and restore it
// in `afterEach`; reassigning the global here would race their teardown.
afterEach(resetBreakpoint)
