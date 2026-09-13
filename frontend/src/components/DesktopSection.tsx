import { useEffect, useState } from 'react'
import { useT } from '../i18n'
import { readState, setIcon, setTitleBar, platformOf, type DesktopState, type IconChoice } from '../desktop'

// The desktop-only half of Appearance.
//
// Renders nothing at all unless the app is running inside a desktop client:
// `readState` resolves to null anywhere /desktop/state does not exist, which in
// a browser is everywhere. So this is not "hidden in a browser" — it is absent.
//
// The hint is not decoration, and it says a DIFFERENT thing on each platform
// because the two shells behave differently:
//
//   Windows   `Form.Icon` reaches the title bar, Alt-Tab and Task Manager, and
//             it reaches the taskbar button only for someone who has set
//             "Combine taskbar buttons: Never". On the Windows 11 default the
//             taskbar shows a GROUP whose icon comes from a Start-menu
//             shortcut, then a desktop shortcut, then the exe — never the
//             window's own. Without saying so, choosing an icon and watching
//             the taskbar not change reads as a broken setting.
//   Linux     `gtk_window_set_icon_name` already reaches the window, Alt-Tab
//             and the switcher with nothing installed. The desktop entry buys
//             something else — the app grid, search, and a name and icon on
//             notifications — so the same toggle is worth having for different
//             reasons, and saying the Windows ones would be wrong.
//
// Hence `k()`: one suffix, applied at the call site, with every twin present in
// both en.ts and de.ts or `i18n.test.ts`'s two parity guards go red.
//
// The title-bar row says a different thing again, and it is a TRADE rather than
// a preference. On Windows the caption has always been the OS's and the client
// only tints it, so turning this on costs the tint. On Linux the client draws
// the strip itself — that is the only way to colour one at all — and a window
// that draws its own strip never sees the window manager's decoration theme,
// its buttons, its metrics or the window icon in the caption. So the row buys
// those back at the price of the colour, and the hint has to say so rather than
// leaving someone to discover which half they lost.

const CHOICES: { id: IconChoice; key: string }[] = [
  { id: 'Auto', key: 'settings.icon.auto' },
  { id: 'Paper', key: 'settings.icon.paper' },
  { id: 'Ink', key: 'settings.icon.ink' },
  { id: 'Accent', key: 'settings.icon.accent' },
  { id: 'Mark', key: 'settings.icon.mark' },
]

export function DesktopSection() {
  const tr = useT()
  const [state, setState] = useState<DesktopState | null>(null)

  useEffect(() => { void readState().then(setState) }, [])

  if (!state) return null

  const linux = platformOf(state) === 'linux'
  const k = (base: string) => linux ? `${base}.linux` : base

  const apply = (next: Partial<{ choice: IconChoice; shortcut: boolean }>) => {
    const choice = next.choice ?? state.choice
    const shortcut = next.shortcut ?? state.startMenuShortcut
    // Optimistic, then reconciled with what the host actually did — `resolved`
    // is the host's answer and cannot be computed here.
    setState({ ...state, choice, startMenuShortcut: shortcut })
    void setIcon(choice, shortcut).then(fresh => fresh && setState(fresh))
  }

  const applyTitleBar = (system: boolean) => {
    setState({ ...state, systemTitleBar: system })
    void setTitleBar(system).then(fresh => fresh && setState(fresh))
  }

  return (
    <>
      <div className="menu-row">
        <label htmlFor="desktop-icon">{tr('settings.icon')}</label>
        <select id="desktop-icon" className="menu-toggle" value={state.choice}
          onChange={e => apply({ choice: e.target.value as IconChoice })}>
          {/* Only `Auto` names an operating system; the other four name
              colours and read the same everywhere. */}
          {CHOICES.map(c => <option key={c.id} value={c.id}>
            {tr(c.id === 'Auto' ? k(c.key) : c.key)}</option>)}
        </select>
      </div>

      <div className="menu-row">
        <label htmlFor="desktop-shortcut">{tr(k('settings.icon.shortcut'))}</label>
        <input id="desktop-shortcut" type="checkbox" checked={state.startMenuShortcut}
          onChange={e => apply({ shortcut: e.target.checked })} />
      </div>

      {/* Absent from an older client's answer, and that absence is the feature
          detection: the web build updates itself on every launch and the client
          does not, so a page that knows about this routinely runs inside one
          that does not. Same rule as the float controls. */}
      {state.systemTitleBar !== undefined && (
        <div className="menu-row">
          <label htmlFor="desktop-titlebar">{tr('settings.titlebar')}</label>
          <input id="desktop-titlebar" type="checkbox" checked={state.systemTitleBar}
            onChange={e => applyTitleBar(e.target.checked)} />
        </div>
      )}

      <div className="hintline">
        {tr(k('settings.icon.hint'))}
        {state.choice === 'Auto' && ' ' + tr(k(
          state.systemUsesLightTheme ? 'settings.icon.autoLight' : 'settings.icon.autoDark'))}
        {state.systemTitleBar !== undefined && ' ' + tr(k('settings.titlebar.hint'))}
        {/* Windows 10 only: it can be told light or dark and nothing else. The
            Linux client draws the strip itself, so it always reports true and
            this never renders there — no platform test needed. Silenced once
            the caption has been handed back: what the OS could have been told
            is not worth a sentence when it is not being told anything. */}
        {!state.captionColour && !state.systemTitleBar && ' ' + tr('settings.icon.win10')}
        {/* Said here rather than on the floating window, which has no room for
            a sentence: the pin control is simply absent under Wayland, and a
            control that vanished with no explanation reads as a bug. */}
        {state.canPin === false && ' ' + tr('settings.float.noPin')}
      </div>
    </>
  )
}
