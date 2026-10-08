# Smylte for the desktop

A native window around the Smylte web app. It loads the app from local disk and
forwards `/api` to your server, so the interface starts at disk speed. It hosts
the engine the OS already has, so rendering is the browser's. API calls, and so
tasks, calendars and live updates, still go to your server.

| | Windows | Linux |
| --- | --- | --- |
| Engine | WebView2 (ships with Windows 10 and 11) | WebKitGTK 6 (`webkitgtk6.0`) |
| Toolkit | WinForms | GTK 4 |
| Asset | `Smylte.exe` | `Smylte-linux-x86_64` |
| Title bar | coloured via `DwmSetWindowAttribute` | drawn by the app, or by the window manager |
| Password at rest | DPAPI | AES-GCM under a 0600 key file |
| Floating window stays on top | yes | X11 only; Wayland is the default |

Design reasoning is in [`docs/DESIGN.md`](../docs/DESIGN.md#desktop-client).

## Install

1. Download `Smylte.exe` or `Smylte-linux-x86_64` from the
   [`desktop-latest`][rel] release.
2. Run it. On first launch it asks for the server address, your username and
   password, where to keep its files, and on Linux whether to add itself to the
   applications menu.

No toolchain is needed; CI builds the binaries and the web assets.

**Windows:** SmartScreen warns the first time because the exe isn't code-signed.
Choose "More info" → "Run anyway".

**Linux:** run `chmod +x Smylte-linux-x86_64` after downloading (GitHub serves
release assets without the executable bit; self-updates set it). The binary
carries the .NET runtime but not the engine. Install these from your
distribution if they're missing:

```
sudo dnf install gtk4 webkitgtk6.0               # Fedora
sudo apt install libgtk-4-1 libwebkitgtk-6.0-4   # Debian, Ubuntu
```

If a library is missing the client says which package to install, on stderr, in
a log file and in a dialog if it can open one. `--check` tests this and exits.

[rel]: https://github.com/nicholaskmitchell/smylte/releases/tag/desktop-latest

## Updates

- **The web app** updates on every launch. The client checks whether
  `smylte-web.zip` on the release has changed, downloads it if so, and runs the
  copy it has when offline. A push to `main` reaches the desktop on the next
  start.
- **The client binary** updates from a strip at the top of the window. **Update**
  downloads the new binary, checks it against the SHA-256 GitHub publishes,
  swaps it in and restarts. If that isn't possible (the folder isn't writable,
  or the release has no digest), the strip explains why and links to the
  download. "Not now" hides it until the next launch.

The strip appears only when the window's own code changed. Changes to the web
app or the server don't trigger it.

## Files it writes

| Windows | Linux | What |
| --- | --- | --- |
| `%APPDATA%\Smylte\settings.json` | `~/.config/Smylte/settings.json` | Server URL, username, encrypted password, optional GitHub token, data folder, port, window size, icon, title bar and floating window settings |
| `<data folder>\web\` | `<data folder>/web/` | The downloaded web build |
| `<data folder>\profile\` | `<data folder>/profile/` | Browser profile (cookies, localStorage) |
| — | `<data folder>/icons/` | The icon variants, unpacked for GTK |
| `%APPDATA%\Smylte\icon.ico` | `~/.local/share/icons/hicolor/…` | Only with the launcher toggle on |
| `…\Start Menu\Programs\Smylte.lnk` | `~/.local/share/applications/com.nicholaskmitchell.Smylte.desktop` | Only with the launcher toggle on; removed when it's turned off |
| — | `~/.config/Smylte/secret.key` | 32 random bytes, mode 0600, for the password |

The data folder defaults to `%LOCALAPPDATA%\Smylte` or `~/.local/share/Smylte`
and is chosen on first run. Failed starts are logged to
`<data folder>/errors.log`.

### The password

Only the password is encrypted. A copied `settings.json` can't be used to sign
in elsewhere: on Windows the key is tied to your Windows account, and on Linux
it's derived from `secret.key`, `/etc/machine-id` and your user name. If the
password can't be decrypted, the app shows its login screen. Neither method stops
a process running as you from reading it.

The optional **GitHub token** (only useful if update checks hit the 60
requests/hour anonymous limit), the server URL, username, data folder and port
are stored in plain text. Treat the file like any file holding a token.

## Changing settings

```
Smylte.exe --setup
./Smylte-linux-x86_64 --setup
```

The setup dialog also opens if the app can't start, usually because of a wrong
server address.

- **Windows:** close the app before running `--setup`. Cancelling the first-run
  dialog exits.
- **Linux:** `--setup` works while the app is open; a second launch raises the
  existing window. If setup is cancelled, the window stays open with a
  **Setup…** button in the title bar.

Linux-only flags:

```
./Smylte-linux-x86_64 --install     # add the applications-menu entry and icons
./Smylte-linux-x86_64 --uninstall   # remove them
./Smylte-linux-x86_64 --check       # do GTK and WebKitGTK load? exits 0 or 1
```

### settings.json options (Linux)

```jsonc
"Backend": "auto"            // default: Wayland where available
"Backend": "x11"             // floating window can stay on top; blurry on scaled displays
"Backend": "wayland"         // never XWayland
"DisableDmabufRenderer": true // if the window paints blank (set automatically on NVIDIA)
```

On Windows, `"FloatNativeDrag": false` makes the floating window use the
fallback drag path if native dragging misbehaves.

## App icon and title bar

Settings → Appearance offers five icons: follow the system theme (the default),
or a cream, ink, accent or unplated mark.

| Windows surface | Follows the setting |
| --- | --- |
| Title bar, Alt-Tab, Task Manager | Yes, immediately |
| Taskbar button | With the **Start menu shortcut** toggle, or "Combine taskbar buttons: Never" |
| Explorer, desktop, pinned entry, Start | No, these use the compiled icon |

| Linux surface | Follows the setting |
| --- | --- |
| Window, Alt-Tab, window switcher | Yes, immediately |
| Dock for a running window, applications grid, search, notifications | With the **Applications menu entry** toggle |

**System title bar** hands the title bar back to the OS. On Windows the caption
stops matching the app background. On Linux the window manager draws it, with
your decoration theme and buttons, and the change takes effect after a restart.

To regenerate the icons after changing `frontend/public/favicon.svg`:

```bash
cd backend && python -m dev.build_app_icon   # needs Pillow
```

## The floating window

The **Float** control on the focus screen opens a small frameless window with
the clock and the current row, and minimises the main window. It shares the
main window's session. Drag it by its body, resize it from its edges, pin it on
top, and **Dock** it (or press Escape or Alt+F4) to bring the main window back.
It has no taskbar button; Alt-Tab lists it.

On Linux, a press that starts on a button and then moves drags the window. A
client older than the web build shows no Float control.

| | X11 | Wayland (default) |
| --- | --- | --- |
| Stays on top | yes | no; there's no pin |
| Reopens where it was | yes | no; the compositor places it |
| Out of the task list | yes | no |
| Drag and resize | yes | yes |
| Monitors at different scales | one scale for all | each at its own |
| Sharp at fractional scaling | no | yes |

## Building

CI publishes both, but to build yourself you need only the .NET 8 SDK (no GTK
development packages; GirCore binds at runtime):

```powershell
dotnet publish desktop/Smylte.Desktop/Smylte.Desktop.csproj -c Release -o publish
```
```bash
dotnet publish desktop/Smylte.Desktop.Linux/Smylte.Desktop.Linux.csproj -c Release -o publish
```

Both are self-contained (about 69 MB and 38 MB) so they run without .NET
installed.

## Tests

```
dotnet test desktop/Smylte.Desktop.Tests/Smylte.Desktop.Tests.csproj
```

Targets plain `net8.0` and links the shared sources, so it runs on any OS. CI
runs it on Windows and Linux. It covers the static file server's path-traversal
guard, cookie rewriting, updates, the `/desktop/*` bridge, the floating window's
resize ring, password storage and every icon file.

## Source layout

Shared (`Smylte.Desktop/`, linked by both clients and the tests):

```
LocalServer.cs        static files from disk, /api reverse proxy, /desktop/*
IDesktopBridge.cs     what the page may ask of the window
Updater.cs            web build and client updates from the release
Session.cs            server probe and sign-in
Settings.cs           settings.json
PasswordProtector.cs  DPAPI on Windows, a derived key elsewhere
Theme.cs              parses the page's --bg
IconChoice.cs         the icon options
FloatRing.cs          floating window resize edges
```

Windows (`Smylte.Desktop/`):

```
Program.cs        single instance, first-run setup, then the window
SetupForm.cs      setup dialog
MainForm.cs       the WebView2 window
FloatForm.cs      the floating focus window
WindowChrome.cs   caption colour via DwmSetWindowAttribute
IconLibrary.cs    icon loading and system theme
ShellShortcut.cs  the Start menu shortcut
```

Linux (`Smylte.Desktop.Linux/`):

```
Program.cs        backend and renderer selection, native check, single instance over D-Bus
NativeCheck.cs    GTK and WebKitGTK detection
SetupWindow.cs    setup dialog
MainWindow.cs     the window, header bar, update strip and bridge
FloatWindow.cs    the floating focus window
WebHost.cs        the shared WebKit session
HeaderChrome.cs   header bar colour
IconAssets.cs     icon theme for the window
ColourScheme.cs   light or dark, via the XDG settings portal
DesktopEntry.cs   the applications-menu entry
X11Window.cs      on top, out of the taskbar, position (X11)
Notifications.cs  WebKit notifications as desktop notifications
UpdateBanner.cs   the client update strip
```
