# Smylte for Windows

A native window around the Smylte web app. It serves the built SPA from local
disk and forwards `/api` to your deployed server, so the interface loads at disk
speed instead of fetching itself over the network on every start.

It is **not** a rewrite and not a browser bundle. The window hosts WebView2 —
the Edge engine already present on Windows 10 and 11 — so rendering is identical
to the browser. What changes is where the assets come from and how the app is
installed and kept current.

## What it does and does not make faster

| | |
| --- | --- |
| App shell, CSS, JS, fonts | **Local.** No network at all. |
| Tasks, calendars, settings, live updates | **Unchanged.** Still your server. |

If the app feels slow after this, the remaining time is in the network path to
the server and Radicale, which no desktop client can shorten.

## Install

1. Download `Smylte.exe` from the [`desktop-latest`][rel] release.
2. Run it. On first launch it asks for the server address, your username and
   password, and where to keep its files.

That is the whole install. There is no toolchain to set up — no Node, no Python,
no .NET, no git. CI builds both the exe and the web assets; the client only
downloads them.

Windows will show a SmartScreen warning the first time, because the exe is not
code-signed. "More info" → "Run anyway". Signing it properly needs a certificate
(roughly $200–400/year).

[rel]: https://github.com/nicholaskmitchell/smylte/releases/tag/desktop-latest

## How updating works

On every launch the client asks GitHub whether the `smylte-web.zip` asset on the
rolling release has changed. If it has, it downloads and swaps it in; if the
network is unreachable it just runs the copy it already has. So a push to `main`
reaches the desktop on the next start, with nothing to redeploy by hand.

The **exe itself** does not replace itself — that needs a second process to
overwrite a running binary, which is deliberately out of scope. It does notice,
though: the same release check compares the published `Smylte.exe` against the
running one and shows a strip along the top of the window with a download link
when they differ. "Not now" hides it until the next launch.

That strip means the *window* changed, not the app. CI publishes a new
`Smylte.exe` only when `desktop/Smylte.Desktop` changed since the one on the
release was built (the release notes record which tree that was); a push that
touches only the web app or the server replaces `smylte-web.zip` and leaves the
exe alone, so the next launch swaps the web build in and shows no strip. It used
to re-upload the exe on every push, and a self-contained bundle is never the same
bytes twice — so every push looked like a new client, and downloading it changed
nothing.

That comparison is by content hash, not a version number, because a version
number has to be remembered and a forgotten bump would ship a client nobody is
told about. It costs nothing extra — GitHub publishes a SHA-256 for every release
asset, and the exe's own hash is computed once and cached against its write time
rather than re-read on every launch.

The exe should rarely need to change, since everything the app actually does
lives in the web build.

## Files it writes

| Path | What |
| --- | --- |
| `%APPDATA%\Smylte\settings.json` | Server URL, username, encrypted password, optional GitHub token, data folder, port, window size, icon choice, title-bar colour, and the floating focus window's position, size and pin |
| `<data folder>\web\` | The downloaded web build |
| `<data folder>\profile\` | WebView2 profile — cookies, localStorage |
| `%APPDATA%\Smylte\icon.ico` | Only with the Start-menu shortcut on: the chosen icon, since a shortcut needs an icon *file* |
| `…\Start Menu\Programs\Smylte.lnk` | Only with that toggle on; removed again when it is turned off |

The data folder defaults to `%LOCALAPPDATA%\Smylte` and is chosen on first run.

Your password is encrypted with DPAPI against your Windows account, so a copied
`settings.json` cannot be used to log in on another account or machine. If it
cannot be decrypted the app simply shows its own login screen.

**The password is the only encrypted field.** Setup also takes an optional
**GitHub token** — worth setting only if the anonymous 60-requests-an-hour API
limit starts biting on update checks — and that is stored in the clear, as are
the server URL, username, data folder and port. So the file is not worthless to
someone who copies it; treat it the way you would any file holding a token.

## Changing settings later

```
Smylte.exe --setup
```

The dialog also opens by itself if the app cannot start — a wrong server address
is the usual reason.

## Building it yourself

You do not need to; CI publishes the exe. But:

```powershell
dotnet publish desktop/Smylte.Desktop/Smylte.Desktop.csproj -c Release -o publish
```

Requires the .NET 8 SDK. The output is self-contained and about 69 MB, because
it carries the runtime — that is what lets the exe run on a machine with no .NET
installed. A framework-dependent build is 1.4 MB but needs the .NET Desktop
Runtime installed separately, which Windows does not ship.

## The icon

`app.ico` is generated, not drawn. Rebuild it after any change to
`frontend/public/favicon.svg` — which is the only place the "S." monogram is
authored — with:

```bash
cd backend && python -m dev.build_app_icon   # needs Pillow
```

That script also re-emits `frontend/public/apple-touch-icon.png`, and carries
the reasoning for everything below. CI never runs it; the binaries are
committed, and what CI does instead is assert they are correct
(`Smylte.Desktop.Tests/AppIconTests.cs`).

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

**The title bar follows the app's theme too.** The strip with the minimise,
maximise and close buttons belongs to the desktop window manager, not to the
app, and `DwmSetWindowAttribute` is the only supported way in. On Windows 11
(22000+) it takes an arbitrary colour, so the caption is painted the app's own
`--bg` — a custom theme carries through to the frame. On Windows 10 the OS
offers only light or dark, and the app picks whichever the theme is nearer. The
colour is remembered between launches so the frame does not flash the system
default while the web app boots.

**Fifteen sizes, and three of them are drawn differently.** Windows asks for 14
distinct sizes across its three request bands, and Fraunces' hairlines go
sub-pixel below about 34px — so 16, 20 and 24 are not downscales of the 256, and
below 24 the period becomes a whole-pixel square. The generator prints the four
floors (stroke, aperture, period, the gap between letter and period) at every
size and refuses to write a file that misses one.

## Tests

```
dotnet test desktop/Smylte.Desktop.Tests/Smylte.Desktop.Tests.csproj
```

Runs on any OS, not just Windows: the project targets plain `net8.0` and
*links* the sources it covers rather than referencing the app, which would drag
in a Windows Desktop runtime pack that has no Linux build. CI runs it alongside
the build.

It covers the two places where a mistake here is a security bug — the static
file resolver's path-traversal guard and the cookie rewriting — and the two ways
a failed update used to cost someone a working client. If either covered file
ever takes a Windows-only dependency this project stops compiling, which is the
intended failure: they are meant to be portable logic.

It also asserts `app.ico` itself, by parsing the bytes rather than the image
(`System.Drawing` throws off Windows, and this project runs everywhere). That is
worth a test because the failure is silent from both ends: a bad regeneration is
swallowed by the deliberate `catch` around the icon load in `MainForm` and
`SetupForm`, so the window quietly falls back to the stock WinForms icon while
Explorer still shows the stamped one.

## How it fits together

```
Program.cs        single instance, first-run setup, then the window
SetupForm.cs      server address, credentials, data folder
MainForm.cs       the WebView2 window; owns the server's lifetime, and the
                  floating one's
FloatForm.cs      the floating focus window: a second WebView2, frameless,
                  moved by its page and resized from its own six-pixel ring
LocalServer.cs    static files from disk + /api reverse proxy + /desktop/*
IDesktopBridge.cs what the page may ask of the window — served at /desktop/*
WindowChrome.cs   the caption bar and frame colour, via DwmSetWindowAttribute
IconLibrary.cs    the five icon choices, and what Auto resolves to
ShellShortcut.cs  the opt-in Start-menu shortcut
Updater.cs        reads the rolling release, swaps in a new web build
Session.cs        probes a server, and trades credentials for a cookie
Settings.cs       %APPDATA% JSON, with DPAPI over the password
```

## The floating window

The focus surface — the clock and the row you are on — can float: the
**Float** control on it opens a small frameless window above everything else
and sends the main window to the taskbar, so the clock stays in view while you
work in whatever you are actually working in. It is the same page at a small
size, in the same WebView2 profile with the same session, so the two windows
agree to the second and either can be closed without the other losing anything.
Drag it by its body, resize it from its edges, pin it or let it fall behind
(the **pin** in its corner; remembered), and **Dock** it — or press Escape, or
Alt+F4 — to bring the main window back. It has no taskbar button of its own;
Alt-Tab lists it, and the main window's own button is always there.

Two things about it are worth knowing. The drag is the page's, not the
window's: WebView2 123 and later move the window from regions the page marks
as draggable, and a runtime older than that is asked to move it through the
same local bridge the icon setting uses — `FloatNativeDrag: false` in
`settings.json` forces the second path if the first ever misbehaves. And the
exe has to be new enough to have the window at all: the web build updates
itself on every launch, the exe does not, and a web build that knows about
floating against an exe that does not simply shows no Float control.

The piece to be careful with is the proxy in `LocalServer.cs`. `/api/events` is
a Server-Sent Events stream and every live update in the app rides on it, so the
proxy sends chunked and flushes after every read. A buffering proxy does not
error — it leaves the stream connected and permanently silent, and the only
symptom is that the UI stops updating on its own.
