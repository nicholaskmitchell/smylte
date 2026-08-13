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

The **exe itself** does not self-update — that needs a second process to replace
a running binary, which is deliberately out of scope for now. It should rarely
need to change, since all the app's actual behaviour lives in the web build.

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
