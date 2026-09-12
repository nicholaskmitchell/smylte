# Smylte for the desktop

A native window around the Smylte web app. It serves the built SPA from local
disk and forwards `/api` to your deployed server, so the interface loads at disk
speed instead of fetching itself over the network on every start.

It is **not** a rewrite and not a browser bundle. The window hosts the engine
the operating system already has — WebView2 on Windows 10 and 11, WebKitGTK on
Linux — so rendering is the browser's. What changes is where the assets come
from and how the app is installed and kept current.

There are two clients and one document. About seventy per cent of what follows
is the same on both — the update story, the bridge, the proxy caveat, the icon
reasoning, the floating window — and a second file would duplicate all of it and
then drift, which is the failure this file keeps warning about elsewhere. Where
they differ, they differ in a column.

| | Windows | Linux |
| --- | --- | --- |
| Engine | WebView2 (ships with the OS) | WebKitGTK 6 (`webkitgtk6.0`) |
| Toolkit | WinForms | GTK 4 |
| Asset | `Smylte.exe` | `Smylte-linux-x86_64` |
| Title bar | painted via `DwmSetWindowAttribute` | drawn by the app, a `GtkHeaderBar` |
| Password at rest | DPAPI | AES-GCM under a 0600 key file |
| Floating window stays on top | yes | on X11, which is the default; see below |

## What it does and does not make faster

| | |
| --- | --- |
| App shell, CSS, JS, fonts | **Local.** No network at all. |
| Tasks, calendars, settings, live updates | **Unchanged.** Still your server. |

If the app feels slow after this, the remaining time is in the network path to
the server and Radicale, which no desktop client can shorten.

## Install

1. Download `Smylte.exe` or `Smylte-linux-x86_64` from the [`desktop-latest`][rel]
   release.
2. Run it. On first launch it asks for the server address, your username and
   password, where to keep its files, and — on Linux — whether to add itself to
   the applications menu.

That is the whole install. There is no toolchain to set up — no Node, no Python,
no .NET, no git. CI builds the binaries and the web assets; the client only
downloads them.

**On Windows**, SmartScreen warns the first time, because the exe is not
code-signed. "More info" → "Run anyway". Signing it properly needs a certificate
(roughly $200–400/year).

**On Linux**, `chmod +x Smylte-linux-x86_64` after downloading — GitHub serves
release assets 0644, and only the client's own self-update sets the bit for you.
There is no signature either; a distribution package would give you one, and
this is not one.

The Linux binary carries the .NET runtime but *not* the engine, exactly as the
exe does not carry WebView2. It needs two libraries from your distribution:

```
sudo dnf install gtk4 webkitgtk6.0          # Fedora
sudo apt install libgtk-4-1 libwebkitgtk-6.0-4   # Debian, Ubuntu
```

Both are already there on a stock Fedora Workstation. If either is missing the
client says which package to install, on stderr, in a log file, and in a dialog
if it can find one — because the alternative is a process that dies inside a
library loader before it can draw anything to explain itself. `--check` answers
the same question and exits, which is what CI runs.

[rel]: https://github.com/nicholaskmitchell/smylte/releases/tag/desktop-latest

## How updating works

On every launch the client asks GitHub whether the `smylte-web.zip` asset on the
rolling release has changed. If it has, it downloads and swaps it in; if the
network is unreachable it just runs the copy it already has. So a push to `main`
reaches the desktop on the next start, with nothing to redeploy by hand. There
is one web build and both clients download it.

The **binary itself** updates from a strip along the top of the window. The same
release check compares the published client against the running one — each asks
only about its own platform's asset — and when they differ the strip offers
**Update**: the client downloads the new binary beside itself, checks it against
the SHA-256 GitHub publishes for the asset, sets the executable bit if it is on
a system with one, renames the running file aside, moves the new one into its
place, starts it, and exits. The new client waits for the old process to leave
before taking the single-instance lock, then deletes the retired file. If any of
that refuses — the binary sits in a folder this user cannot write, the release
states no digest to check against — the strip says why and offers the download
page instead. "Not now" hides it until the next launch.

That dance is one code path for both systems, and the two halves need it for
different reasons. Windows cannot overwrite a running image at all, but it can
rename one. Linux can do either — a rename over a running binary is legal, since
the process holds the inode and only opening the file for *writing* is refused —
but it needs the WAIT more than Windows does: its single-instance slot is a
D-Bus name, and a client that starts while the old one still holds it does not
become a second instance, it raises the old window. An update that appears to do
nothing is worse than one that fails.

That strip means the *window* changed, not the app. CI publishes a new binary
only when the sources it is built from changed since the copy on the release was
built (the release notes record the key for each); a push that touches only the
web app or the server replaces `smylte-web.zip` and leaves both binaries alone,
so the next launch swaps the web build in and shows no strip. It used to
re-upload the exe on every push, and a self-contained bundle is never the same
bytes twice — so every push looked like a new client, and downloading it changed
nothing.

The two keys are not the same key, and cannot be. The exe's is the tree hash of
`desktop/Smylte.Desktop`. The Linux client links those same sources rather than
carrying its own copy, so a change to `LocalServer.cs` changes that binary while
leaving `desktop/Smylte.Desktop.Linux` untouched — its key is therefore both
tree hashes hashed together. One shared key would get the cheap case wrong in
the expensive direction: a GTK file moving would tell every Windows user to
download 69 MB.

That comparison is by content hash, not a version number, because a version
number has to be remembered and a forgotten bump would ship a client nobody is
told about. It costs nothing extra — GitHub publishes a SHA-256 for every release
asset, and the exe's own hash is computed once and cached against its write time
rather than re-read on every launch.

The exe should rarely need to change, since everything the app actually does
lives in the web build.

## Files it writes

One line of code chooses both columns: `SpecialFolder.ApplicationData` and
`LocalApplicationData`, which .NET already maps to `$XDG_CONFIG_HOME` and
`$XDG_DATA_HOME` on Linux. Nothing needed changing to become XDG-correct.

| Windows | Linux | What |
| --- | --- | --- |
| `%APPDATA%\Smylte\settings.json` | `~/.config/Smylte/settings.json` | Server URL, username, encrypted password, optional GitHub token, data folder, port, window size, icon choice, title-bar colour, and the floating focus window's position, size and pin |
| `<data folder>\web\` | `<data folder>/web/` | The downloaded web build |
| `<data folder>\profile\` | `<data folder>/profile/` | Browser profile — cookies, localStorage |
| — | `<data folder>/icons/` | The four icon variants, unpacked so GTK can look one up by name |
| `%APPDATA%\Smylte\icon.ico` | `~/.local/share/icons/hicolor/…` | Only with the launcher toggle on: the chosen icon, since a shortcut or an entry needs an icon *file* |
| `…\Start Menu\Programs\Smylte.lnk` | `~/.local/share/applications/com.nicholaskmitchell.Smylte.desktop` | Only with that toggle on; removed again when it is turned off |
| — | `~/.config/Smylte/secret.key` | 32 random bytes, mode 0600. See below |

The data folder defaults to `%LOCALAPPDATA%\Smylte` / `~/.local/share/Smylte`
and is chosen on first run.

### The password

A copied `settings.json` cannot be used to log in on another account or machine.
If it cannot be decrypted the app simply shows its own login screen — that is an
expected outcome, not an error, and it is why nothing here ever throws.

The two clients hold that property by different means, and the difference is
worth stating rather than glossing:

| | How | What a copied settings.json gives someone |
| --- | --- | --- |
| Windows | DPAPI, `CurrentUser` scope | Nothing. The key is derived from your logon credential and held by the OS |
| Linux | AES-GCM under a key derived from `~/.config/Smylte/secret.key` (32 random bytes, 0600), `/etc/machine-id` and your user name | Nothing, *unless they also took the key file* — which is why it is 0600 and why machine-id is in the derivation: the directory does not travel either |

Neither stops a process running **as you** from asking for the password; DPAPI
does not either. What both give is the narrower property this section claims.

The Linux side is deliberately **not** the login keyring. libsecret would put
the key behind your login credential, which is stronger against someone imaging
the disk, and it is the natural next tier behind the same two methods. It is not
in yet because no test that runs in CI can exercise it — there is no session bus
on a runner — and putting the untestable path on the primary credential route is
the wrong way round. What is here is unit-tested, needs no daemon, and works
over SSH, on KDE, and on a minimal install. A backup that captures your home
directory captures both halves; treat it accordingly.

**The password is the only encrypted field.** Setup also takes an optional
**GitHub token** — worth setting only if the anonymous 60-requests-an-hour API
limit starts biting on update checks — and that is stored in the clear, as are
the server URL, username, data folder and port. So the file is not worthless to
someone who copies it; treat it the way you would any file holding a token.

## Changing settings later

```
Smylte.exe --setup
./Smylte-linux-x86_64 --setup
```

The dialog also opens by itself if the app cannot start — a wrong server address
is the usual reason.

On Windows, running `--setup` while the app is open tells you to close it first:
a second process cannot reach the first. On Linux it just works, because the
flag is delivered to the running instance over the same D-Bus name that makes
the client single-instance. Same asymmetry behind a second plain launch, which
raises the existing window instead of exiting silently.

Cancelling the dialog also differs, and it is worth knowing which you are
looking at. On Windows a cancelled first-run dialog ends the process. On Linux
the window stays, showing either the reason the app could not start or — if it
has never been configured — an empty state, with a **Setup…** button in the
title bar that reopens the dialog. Either way the exception behind a failed
start is written to `<data folder>/errors.log`, which is the thing to read when
the message on screen is not enough.

The Linux client takes two more flags, both of which write the applications-menu
entry the Appearance toggle writes — they exist because a launcher is a
reasonable thing to want without opening the app, and because they work over SSH
where the settings UI does not:

```
./Smylte-linux-x86_64 --install     # write the entry and its icons
./Smylte-linux-x86_64 --uninstall   # remove them again
./Smylte-linux-x86_64 --check       # do GTK and WebKitGTK resolve? exits 0 or 1
```

## Building it yourself

You do not need to; CI publishes both. But:

```powershell
dotnet publish desktop/Smylte.Desktop/Smylte.Desktop.csproj -c Release -o publish
```
```bash
dotnet publish desktop/Smylte.Desktop.Linux/Smylte.Desktop.Linux.csproj -c Release -o publish
```

The .NET 8 SDK and nothing else — in particular, **no GTK development
packages**. GirCore binds by `dlopen` at runtime rather than linking, so the
Linux client cross-builds from anywhere the SDK runs and CI produces it on an
ordinary runner with no desktop stack installed.

Both outputs are self-contained — about 69 MB and 38 MB — because they carry the
runtime, which is what lets either run on a machine with no .NET installed. A
framework-dependent build is a tenth the size and needs the runtime installed
separately, which neither system ships.

## The icon

The icons are generated, not drawn. Rebuild them after any change to
`frontend/public/favicon.svg` — which is the only place the "S." monogram is
authored — with:

```bash
cd backend && python -m dev.build_app_icon   # needs Pillow
```

That writes four `.ico` files for Windows, the same four variants as loose PNGs
and SVGs for Linux, and `frontend/public/apple-touch-icon.png`, and carries the
reasoning for everything below. One recipe, three containers: the Linux emitter
reuses the same renderer, the same stroke offsets and the same four legibility
floors, so the art cannot drift between them. CI never runs it; the binaries are
committed, and what CI does instead is assert they are correct
(`AppIconTests.cs` and `LinuxIconTests.cs`).

Linux takes seven sizes where Windows takes fifteen, and the eight that do not
come along are all workarounds for Win32 lookup rules — a byte-wide width field
that cannot encode 256, three request bands to satisfy at once — that an icon
theme does not have. It takes the nearest size at or above what it wants and
scales down, which is what those extra frames were faking.

Two things about it are worth knowing before changing it.

**The Windows icon is deliberately not the favicon.** iOS takes a full-bleed
opaque square and masks, rounds and insets it itself; Windows does none of that
and composites whatever the file holds, literally. So the cream plate that the
web and iOS assets keep is drawn in full on a taskbar, where it fails on both
themes at once — 1.05:1 against the light one, 13.98:1 against the dark. A
Win32 `.ico` holds exactly one image per size and has no light/dark variant
mechanism, and burnt orange is the only brand colour that clears 3:1 on both —
so the icon compiled into the exe is an accent plate, and it is rounded, which
the editorial system's `border-radius: 0` otherwise forbids. Both are deliberate
departures: that file is what Explorer, a pinned entry and a desktop shortcut
get, and none of them can follow the theme.

**You can change it, within limits.** Settings → Appearance in the app, or the
`--setup` dialog, offers five choices: follow the Windows theme (the default),
or a cream, ink, accent or unplated mark. Following the theme is possible only
at runtime — a `.ico` holds one image per size and has no light/dark variant
mechanism outside MSIX — which is why the plated options exist at all.

The limits are worth stating, because the surface most people mean is the one
that does not follow:

| Surface | Follows the setting |
| --- | --- |
| Title bar, Alt-Tab, Task Manager | Yes, immediately |
| Taskbar button | Only with "Combine taskbar buttons: Never", or the shortcut below |
| Explorer, desktop, pinned entry, Start | No — those read the compiled icon |

On the Windows 11 default the taskbar shows a *grouped* button, and [its icon
comes from a Start-menu shortcut, then a desktop shortcut, then the exe][chen]
— never the window's own. So Appearance has a **Start menu shortcut** toggle,
off by default, which writes one carrying the chosen icon and this app's
AppUserModelID. It is the only thing that reaches that button, and it is opt-in
because the client otherwise installs nothing anywhere.

[chen]: https://devblogs.microsoft.com/oldnewthing/20150812-00/?p=91831

**Linux gets more of this for free, and the toggle buys something else.** GTK 4
sets a window's icon by NAME, looked up in the icon theme, so the client unpacks
all four variants into its own data folder, adds that to the search path, and
switches with a string:

| Surface | Follows the setting |
| --- | --- |
| Window, Alt-Tab, the window switcher | Yes, immediately, with nothing installed |
| Dash or dock, for a *running* window | Yes, with the entry below |
| Applications grid, search, a *launcher* | Only with the entry |
| Notifications carrying the app's name | Only with the entry |

So the same wire field means a different thing on each platform, and the setting
says so rather than reusing the Windows sentence. The entry is still opt-in for
the same reason — the client otherwise installs nothing anywhere — but the
first-run dialog asks outright, because on Linux the alternative is an app with
no launcher and a generic icon, and quietly installing one would contradict the
promise.

Three strings have to agree or GNOME shows a running window under a generic
icon: the entry's basename, its `StartupWMClass`, and the program name the
process sets. All three are `com.nicholaskmitchell.Smylte`, written once in
`Program.cs`. Wayland matches on the app id alone; the other two are the X11
belt.

**The title bar follows the app's theme too.** On Windows the strip with the
minimise, maximise and close buttons belongs to the desktop window manager, not
to the app, and `DwmSetWindowAttribute` is the only supported way in. On Windows
11 (22000+) it takes an arbitrary colour, so the caption is painted the app's
own `--bg` — a custom theme carries through to the frame. On Windows 10 the OS
offers only light or dark, and the app picks whichever the theme is nearer.

X11 and Wayland have nothing equivalent: no property names a frame's colour, and
no protocol does either. So the Linux client stops asking for a frame and draws
one — a `GtkHeaderBar` set as the window's titlebar, styled from the same `--bg`
— which is client-side decoration and what every GNOME app already does. The
rejected alternative, stated because a reader will wonder: keep the system frame
and drop the feature, leaving a grey bar above a themed page on the one platform
that can do it properly. It is also why that client reports the arbitrary-colour
capability as always available, where the Windows one reports a version test.

Either way the colour is remembered between launches, so the frame does not
flash the system default while the web app boots.

**Fifteen sizes, and three of them are drawn differently.** Windows asks for 14
distinct sizes across its three request bands, and Fraunces' hairlines go
sub-pixel below about 34px — so 16, 20 and 24 are not downscales of the 256, and
below 24 the period becomes a whole-pixel square. The generator prints the four
floors (stroke, aperture, period, the gap between letter and period) at every
size and refuses to write a file that misses one. The Linux rasters are held to
the same floors by the same call, at the seven sizes hicolor names.

## Tests

```
dotnet test desktop/Smylte.Desktop.Tests/Smylte.Desktop.Tests.csproj
```

Runs on any OS, not just Windows: the project targets plain `net8.0` and
*links* the sources it covers rather than referencing the app, which would drag
in a Windows Desktop runtime pack that has no Linux build. CI runs it alongside
the build.

It covers the two places where a mistake here is a security bug — the static
file resolver's path-traversal guard and the cookie rewriting — the two ways a
failed update used to cost someone a working client, the whole `/desktop/*`
bridge contract, the floating window's resize ring, the password at rest, and
every icon file byte by byte. If a covered file ever takes a Windows-only
dependency this project stops compiling, which is the intended failure: they are
meant to be portable logic, and two clients now depend on that being true.

CI runs it on **both** runners, and the second run is not waste. The suite is no
longer platform-blind: the Windows leg takes the DPAPI arm of the password
protector, the Linux leg takes the derived-key arm, and only the Linux leg is on
a case-sensitive filesystem — which is the only place the traversal guard can
actually be wrong.

It also asserts `app.ico` itself, by parsing the bytes rather than the image
(`System.Drawing` throws off Windows, and this project runs everywhere). That is
worth a test because the failure is silent from both ends: a bad regeneration is
swallowed by the deliberate `catch` around the icon load in `MainForm` and
`SetupForm`, so the window quietly falls back to the stock WinForms icon while
Explorer still shows the stamped one.

## How it fits together

Shared, in `Smylte.Desktop/`. Both clients LINK these rather than referencing
them, the way the test project does, and they stay in that directory on purpose:
`desktop-release.yml` computes `git rev-parse HEAD:desktop/Smylte.Desktop` to
decide whether the exe needs republishing, and `backend/tests/test_csp.py` reads
`LocalServer.cs` by that path to diff its policy against `csp.py`'s. Moving them
would break both, and the second silently.

```
LocalServer.cs    static files from disk + /api reverse proxy + /desktop/*
IDesktopBridge.cs what the page may ask of the window — served at /desktop/*
Updater.cs        reads the rolling release, swaps in a new web build or client
Session.cs        probes a server, and trades credentials for a cookie
Settings.cs       XDG / %APPDATA% JSON
PasswordProtector.cs  DPAPI on Windows, a derived key elsewhere
Theme.cs          parse the page's --bg, and decide what is legible on it
IconChoice.cs     the five icon names, and what Auto resolves to
FloatRing.cs      which edge of the six-pixel ring a point is on
```

The Windows half, in `Smylte.Desktop/`:

```
Program.cs        single instance, first-run setup, then the window
SetupForm.cs      server address, credentials, data folder
MainForm.cs       the WebView2 window; owns the server's lifetime, and the
                  floating one's
FloatForm.cs      the floating focus window: a second WebView2, frameless,
                  moved by its page and resized from its own six-pixel ring
WindowChrome.cs   the caption bar and frame colour, via DwmSetWindowAttribute
IconLibrary.cs    loads the .ico variants, and reads the system theme
ShellShortcut.cs  the opt-in Start-menu shortcut
```

The GTK half, in `Smylte.Desktop.Linux/`:

```
Program.cs        the backend and the renderer, chosen before GTK loads; the
                  native pre-flight; single instance over D-Bus
NativeCheck.cs    are GTK and WebKitGTK installed, and what to say if not
SetupWindow.cs    server address, credentials, data folder, launcher
MainWindow.cs     the window, the header bar, the update strip — and the bridge
FloatWindow.cs    the floating focus window: undecorated, on top, its own ring
WebHost.cs        one WebKit session shared by both windows, and the cookie seed
HeaderChrome.cs   the header bar's colour, as a stylesheet
IconAssets.cs     unpacks the four variants into a private hicolor tree, so a
                  window icon can be chosen by name
ColourScheme.cs   is the desktop light or dark, over the XDG settings portal —
                  and a signal when that changes
DesktopEntry.cs   the opt-in applications-menu entry
X11Window.cs      on top, out of the taskbar, and where — via libX11
Notifications.cs  WebKit's notifications, re-raised as the desktop's
UpdateBanner.cs   the strip that replaces the binary
```

Every window class HOLDS its `Gtk.Window` rather than subclassing it. GirCore
marks the regular constructors on its native classes obsolete and says they will
be removed, so subclassing is a dead end on a binding this project pins exactly.

## The floating window

The focus surface — the clock and the row you are on — can float: the
**Float** control on it opens a small frameless window above everything else
and sends the main window to the taskbar, so the clock stays in view while you
work in whatever you are actually working in. It is the same page at a small
size, in the same browser profile with the same session, so the two windows
agree to the second and either can be closed without the other losing anything.
Drag it by its body, resize it from its edges, pin it or let it fall behind
(the **pin** in its corner; remembered), and **Dock** it — or press Escape, or
Alt+F4 — to bring the main window back. It has no taskbar button of its own;
Alt-Tab lists it, and the main window's own button is always there.

Two things about it are worth knowing. **The drag is not the window's own.** On
Windows, WebView2 123 and later move the window from regions the page marks as
draggable, and a runtime older than that is asked to move it through the same
local bridge the icon setting uses — `FloatNativeDrag: false` in `settings.json`
forces the second path if the first ever misbehaves. WebKitGTK implements no
such thing at all, so on Linux the page's drag regions are inert and the host
moves the window itself from a gesture. The known cost, stated rather than
hidden: a press that starts on a button and then travels moves the window
instead of pressing it. Asking the page where its controls are would mean adding
a verb to a bridge that is deliberately not a general "call the host" channel.

**And the client has to be new enough to have the window at all.** The web build
updates itself on every launch and the binary does not, so a web build that
knows about floating against a client that does not simply shows no Float
control. Every key the page reads about this window is optional for that reason,
and every reader treats absence as the old behaviour.

### Under Wayland, three of its four properties are gone

Staying above other windows, opening where it was left, and keeping out of the
task list are all EWMH — twenty years old, honoured by every window manager, and
absent from Wayland with no extension GNOME implements. So the Linux client asks
for X11 before GDK looks, and does those three through `libX11` by hand.

```jsonc
// ~/.config/Smylte/settings.json
"Backend": "x11"        // the default
"Backend": "wayland"    // crisper at a fractional scale; see the table
```

| | X11 (default) | Wayland |
| --- | --- | --- |
| Stays on top | yes | **no** — the pin control is absent, and Appearance says why |
| Reopens where it was | yes | no; the compositor places it, and the saved position is left alone so switching back restores it |
| Out of the task list | yes | no; it gets its own entry |
| Drag and resize | yes | yes |
| Crisp at a fractional scale | XWayland can look soft | yes |

Asking for X11 where there is no X server would be worse than not asking — GDK
does not fall back when the variable is set, it fails to open the display — so a
session with no `DISPLAY` quietly clears it and runs Wayland-native instead.

One more escape hatch, for a machine where WebKitGTK's DMA-BUF renderer paints
nothing at all — a window frame around a white rectangle, with no error
anywhere, which is what the NVIDIA proprietary driver does to it. The client
sets the variable itself when it finds `/proc/driver/nvidia/version`; this is
for the machines that need it and do not look like that.

```jsonc
"DisableDmabufRenderer": true
```

The piece to be careful with is the proxy in `LocalServer.cs`. `/api/events` is
a Server-Sent Events stream and every live update in the app rides on it, so the
proxy sends chunked and flushes after every read. A buffering proxy does not
error — it leaves the stream connected and permanently silent, and the only
symptom is that the UI stops updating on its own.
