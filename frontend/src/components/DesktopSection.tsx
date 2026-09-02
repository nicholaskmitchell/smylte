import { useEffect, useState } from 'react'
import { useT } from '../i18n'
import { readState, setIcon, type DesktopState, type IconChoice } from '../desktop'

// The desktop-only half of Appearance.
//
// Renders nothing at all unless the app is running inside the Windows client:
// `readState` resolves to null anywhere /desktop/state does not exist, which in
// a browser is everywhere. So this is not "hidden in a browser" — it is absent.
//
// The hint is not decoration. `Form.Icon` reaches the title bar, Alt-Tab and
// Task Manager, and it reaches the taskbar button only for someone who has set
// "Combine taskbar buttons: Never". On the Windows 11 default the taskbar shows
// a GROUP whose icon comes from a Start-menu shortcut, then a desktop shortcut,
// then the exe — never the window's own. Without saying so, choosing an icon
// and watching the taskbar not change reads as a broken setting rather than as
// the documented behaviour of the shell.

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

  const apply = (next: Partial<{ choice: IconChoice; shortcut: boolean }>) => {
    const choice = next.choice ?? state.choice
    const shortcut = next.shortcut ?? state.startMenuShortcut
    // Optimistic, then reconciled with what the host actually did — `resolved`
    // is the host's answer and cannot be computed here.
    setState({ ...state, choice, startMenuShortcut: shortcut })
    void setIcon(choice, shortcut).then(fresh => fresh && setState(fresh))
  }

  return (
    <>
      <div className="menu-row">
        <label htmlFor="desktop-icon">{tr('settings.icon')}</label>
        <select id="desktop-icon" className="menu-toggle" value={state.choice}
          onChange={e => apply({ choice: e.target.value as IconChoice })}>
          {CHOICES.map(c => <option key={c.id} value={c.id}>{tr(c.key)}</option>)}
        </select>
      </div>

      <div className="menu-row">
        <label htmlFor="desktop-shortcut">{tr('settings.icon.shortcut')}</label>
        <input id="desktop-shortcut" type="checkbox" checked={state.startMenuShortcut}
          onChange={e => apply({ shortcut: e.target.checked })} />
      </div>

      <div className="hintline">
        {tr('settings.icon.hint')}
        {state.choice === 'Auto' && ' ' + tr(
          state.systemUsesLightTheme ? 'settings.icon.autoLight' : 'settings.icon.autoDark')}
        {!state.captionColour && ' ' + tr('settings.icon.win10')}
      </div>
    </>
  )
}
