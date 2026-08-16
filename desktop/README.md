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
| `%APPDATA%\Smylte\settings.json` | Server URL, username, encrypted password, window size |
| `<data folder>\web\` | The downloaded web build |
| `<data folder>\profile\` | WebView2 profile — cookies, localStorage |

The data folder defaults to `%LOCALAPPDATA%\Smylte` and is chosen on first run.

Your password is encrypted with DPAPI against your Windows account, so a copied
`settings.json` is useless on another account or machine. If it cannot be
decrypted the app simply shows its own login screen.

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

## How it fits together

```
Program.cs      single instance, first-run setup, then the window
SetupForm.cs    server address, credentials, data folder
MainForm.cs     the WebView2 window; owns the server's lifetime
LocalServer.cs  static files from disk + /api reverse proxy
Updater.cs      reads the rolling release, swaps in a new web build
Session.cs      probes a server, and trades credentials for a cookie
Settings.cs     %APPDATA% JSON, with DPAPI over the password
```

The piece to be careful with is the proxy in `LocalServer.cs`. `/api/events` is
a Server-Sent Events stream and every live update in the app rides on it, so the
proxy sends chunked and flushes after every read. A buffering proxy does not
error — it leaves the stream connected and permanently silent, and the only
symptom is that the UI stops updating on its own.
