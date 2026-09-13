// Talking to the desktop client the app may be running inside.
//
// The desktop build serves this SPA off local disk and answers a few extra
// routes under /desktop/ that the deployed server does not have. That asymmetry
// IS the feature detection: in a browser these fetches 404, `state()` resolves
// to null, and every desktop-only control simply never renders. Nothing here
// needs a user agent string or a build flag.
//
// Two things live behind it, and they exist because the window is not ours to
// draw. The app icon and the title bar — the strip carrying minimise, maximise
// and close — belong to the host, and the only way the page can influence
// either is to ask it to.
//
// There are two hosts now, and the page is deliberately almost unable to tell
// them apart: the routes, the bodies and the answers are identical, and the
// only differences are the optional keys below. `platform` decides wording —
// "Start menu" is not a thing on Linux — and `canPin` reports a capability one
// of them does not always have. Everything else is the same contract.

export type IconChoice = 'Auto' | 'Paper' | 'Ink' | 'Accent' | 'Mark'

export type DesktopPlatform = 'windows' | 'linux'

export type DesktopState = {
  available: true
  choice: IconChoice
  /// What Auto resolves to right now. Equal to `choice` for the fixed modes.
  resolved: Exclude<IconChoice, 'Auto'>
  systemUsesLightTheme: boolean
  startMenuShortcut: boolean
  /// Windows 11 22000+ can take an arbitrary caption colour; Windows 10 can
  /// only be told light or dark. The section says which, rather than promising
  /// a colour the OS will quietly ignore.
  captionColour: boolean
  /// Whether the user has handed the title bar back to the system.
  ///
  /// OPTIONAL, and the optionality is the feature detection: a client that does
  /// not send it has no such setting, and the row is not rendered at all. Absent
  /// therefore means false, which is also what it means as a value.
  ///
  /// It is not the opposite of `captionColour`. That one is a CAPABILITY — what
  /// this build could do to the caption — and this is a CHOICE. On Linux the
  /// capability is always there and the choice is the whole question: the app
  /// draws the strip, so it can colour it, and a window that draws its own strip
  /// never sees the window manager's decoration theme. The two are exclusive
  /// and nothing on X11 or Wayland makes them otherwise.
  systemTitleBar?: boolean
  /// Which host this is. OPTIONAL, and absent means Windows — the Windows
  /// client has never sent it and never will, so reading its absence as
  /// anything else would change what every installed exe means. Only wording
  /// depends on it.
  platform?: DesktopPlatform
  /// The floating focus window. OPTIONAL, and the optionality is the
  /// compatibility rule: the web build updates itself on every launch and the
  /// exe does not, so a page that knows about floating routinely runs inside a
  /// client that does not. Such a client answers without these keys, and every
  /// float control is gated on `floating !== undefined`.
  floating?: boolean
  pinned?: boolean
  /// Whether the runtime moves the floating window from the page's own drag
  /// regions (`app-region: drag`), or the page has to ask the bridge on every
  /// press. Only meaningful inside the floating window.
  nativeDrag?: boolean
  /// Whether the host can keep the floating window above other windows.
  ///
  /// ABSENT MEANS YES. The Windows client never sends it and neither does a
  /// Linux client on X11; only a Wayland session sends `false`, because no
  /// protocol lets an ordinary client ask to stay on top and GNOME implements
  /// no extension that would. Every reader must therefore test `!== false`
  /// rather than `=== true`, or a new web build would take the pin away from
  /// every exe already installed.
  canPin?: boolean
}

/// Which host, for the strings that differ. Absent is Windows — see the key.
export const platformOf = (state: DesktopState): DesktopPlatform =>
  state.platform ?? 'windows'

async function call(path: string, body?: unknown): Promise<DesktopState | null> {
  try {
    const res = await fetch(path, body === undefined ? {} : {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) return null
    return (await res.json()) as DesktopState
  } catch {
    // Offline, no host, or a server that has never heard of /desktop. All the
    // same answer: this is not the desktop client.
    return null
  }
}

export const readState = () => call('/desktop/state')

export const setIcon = (choice: IconChoice, startMenuShortcut: boolean) =>
  call('/desktop/icon', { choice, startMenuShortcut })

/// Hand the title bar to the system, or take it back.
///
/// Windows applies it at once — the caption was always the OS's and only the
/// tint was the app's. Linux applies it on the next launch, because GTK refuses
/// to change a realized window's titlebar and the only way round that would
/// destroy the surface the page is running on. The hint says so.
export const setTitleBar = (system: boolean) =>
  call('/desktop/titlebar', { system })

// The floating focus window. Four verbs on one route, each answered with the
// fresh host state so the control that asked can reconcile from it.
export const floatWindow = () => call('/desktop/window', { action: 'float' })
export const dockWindow = () => call('/desktop/window', { action: 'dock' })
export const pinWindow = (pinned: boolean) => call('/desktop/window', { action: 'pin', pinned })
export const dragWindow = () => call('/desktop/window', { action: 'drag' })

/// Whether THIS document is the floating window. The host opens it at
/// `/focus?float=1`, and this is the one place in the app that reads the query
/// string: the surface is the same either way, and the flag only decides which
/// way out it offers (Dock rather than Back) and which alerts it owns.
export const isFloatWindow = () =>
  new URLSearchParams(location.search).get('float') === '1'

/// Push the app's current background to the host, so the caption bar matches.
///
/// The value is read off the live CSSOM rather than recomputed, so a custom
/// theme's --bg reaches the frame exactly as the page is painted with it — the
/// same value index.html already resolves before first paint for the mobile
/// browser chrome.
export function syncCaption(): void {
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
  if (bg) void call('/desktop/appearance', { background: toHex(bg) })
}

/// --bg is authored as hex in every shipped theme, but a custom one is only
/// validated against a character blacklist, so it can legitimately be `rgb()`
/// or a named colour. The host parses hex and nothing else, so normalise here —
/// where a Canvas is available — rather than teaching it CSS colour syntax.
function toHex(value: string): string {
  if (/^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(value)) return value
  try {
    const ctx = document.createElement('canvas').getContext('2d')!
    ctx.fillStyle = '#000'
    ctx.fillStyle = value
    return ctx.fillStyle as string
  } catch {
    return value
  }
}

/// Keep the caption in step for as long as the page is open.
///
/// Watching the root element rather than hooking the theme toggle is deliberate:
/// --bg moves for four different reasons — the light/dark toggle, a preset, a
/// custom theme's tokens, and the pre-paint script in index.html — and they do
/// not share a single call site. What they DO share is that all four end in an
/// attribute or inline-style change on <html>, which is exactly what this sees.
export function startCaptionSync(): void {
  // Probe once before watching anything. In a browser this is the only request
  // that ever gets made: /desktop/state 404s, and the observer is never
  // installed — so a theme toggle on the web does not fire a POST that can only
  // fail. In the desktop client it costs one call at startup.
  void readState().then(state => {
    if (!state) return
    let queued = 0
    const schedule = () => {
      clearTimeout(queued)
      // Coalesced: a theme change can touch two dozen custom properties in a
      // loop, and the host only cares about where that lands.
      queued = window.setTimeout(syncCaption, 50)
    }
    new MutationObserver(schedule).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme', 'data-preset', 'style'],
    })
    syncCaption()
  })
}
