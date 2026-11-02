# Smylte for Android

A native window around the Smylte web app, like the
[desktop clients](../desktop/README.md). It shows the app in the Android System
WebView (the Chromium engine that Android keeps up to date), with the app's own
files loaded from the phone. API calls, and so tasks, calendars and live
updates, still go to your server.

It isn't in the Play Store or any other store. You install the APK from the
[`desktop-latest`][rel] release once, and after that it updates itself.

Design reasoning is in [`docs/DESIGN.md`](../docs/DESIGN.md#android-client).

## Install

1. On the phone, open the [`desktop-latest`][rel] release and download
   `Smylte-android.apk`.
2. Open the download. Android asks you to allow your browser (or file manager)
   to install apps. Allow it, go back, and install.
3. Open Smylte. On first launch it asks for the server address and, optionally,
   your username and password.

You need Android 11 or later and an `https://` server address: the address you
open Smylte at in a browser, with no path. The server's sign-in cookie is
`Secure`, so plain `http://` can't work.

[rel]: https://github.com/nicholaskmitchell/smylte/releases/tag/desktop-latest

### Google's developer verification

Google has announced that from 2027 certified Android phones will refuse apps
from developers it hasn't verified, sideloaded ones included. It began in
Brazil, Indonesia, Singapore and Thailand in September 2026. There are three
ways to keep installing an app like this one:

- Turn on the one-time "advanced flow" in the phone's settings.
- Register as a developer with Google and register the signing key with it.
- Install over `adb`, which is exempt.

Nothing in this client depends on which of these you use.

## Updates

- **The web app** updates when Smylte starts. It checks whether
  `smylte-web.zip` on the release has changed, downloads it if so, and starts
  the copy it already has when it's offline or the check is slow. Android can
  keep an app in memory for days, so Smylte also checks when you come back to
  it after six hours or more. A newer build found then is unpacked and offered
  with **Reload**. It's never swapped in under the page you're using.
- **The app itself** updates from a strip at the top of the window. **Update**
  downloads the new APK and checks it against the SHA-256 that GitHub publishes.
  It also checks that the new APK is Smylte, signed with the same key and no
  older than the installed copy. Then it hands the APK to Android's installer.
  The first time, Android asks you to let Smylte install apps. The installer
  asks you to confirm, closes Smylte while it installs, and offers **Open** when
  it's done. If any step fails, the strip says why and links to the release.

As on the desktop, the strip appears only when the app's own code changed, not
for changes to the web app or the server. Smylte compares the published APK's
digest with the installed APK, which Android keeps byte for byte.

GitHub allows 60 anonymous API requests an hour per address, and a phone on
mobile data often shares its address with many others. Smylte sends each check
as a conditional request, which doesn't count against the limit when nothing
changed. If checks still fail, a GitHub token in **Server settings** raises the
limit. A token with no scopes is enough.

## Settings

Long-press the Smylte icon and choose **Server settings**. The same screen opens
on first run and from the error screen if the app can't start.

- **Server address**: checked against `/api/me` before it's saved.
- **Username and password**: optional. With a password saved, Smylte signs in
  by itself when the session runs out (the server's sessions last seven days).
  It checks the existing session first, so it doesn't sign in again on every
  start. Leave the password empty to sign in on the app's own screen, where
  password managers can fill it.
- **GitHub token**: optional; see above.

The password and the token are encrypted with AES-GCM under a key that the
Android keystore generates and never releases, so a copy of the app's files is
useless without the phone. As on the desktop, this doesn't stop code running as
the app from reading them.

## What it stores

Everything is in the app's private storage and is removed when you uninstall
it. Nothing is backed up or moved to a new phone, because the encrypted values
can't be read there anyway.

| Where | What |
| --- | --- |
| `shared_prefs/smylte.xml` | Server address, username, encrypted password and token, the last release ETag and check time, the last page colour |
| `files/web/` | The downloaded web build, with a record of the release asset it came from |
| `files/web.next/` | A newer build waiting for a reload, when there is one |
| `files/release.json` | The last release description, for conditional checks |
| `cache/updates/` | An app update between download and install |
| `app_webview/` | The WebView's cookies and local storage |

## Differences from the desktop clients

- **No local server.** The desktop clients serve the app from
  `http://localhost:<port>` and proxy `/api`. This client loads the app at your
  server's own address and answers the requests for its files from the phone,
  so the WebView handles API calls, cookies and the live-update stream itself
  and no port is opened. (Any other app on a phone could connect to a local
  port.)
- **No desktop settings.** The icon choice, title bar and floating focus window
  don't exist here, so Settings doesn't show them. The status and navigation
  bars take the page's background colour, from the `theme-color` the app
  already publishes for mobile browsers.
- **Theme export isn't available yet.** The app saves the file through a
  browser download, which the WebView can't hand to Android. Theme import
  works.

## Building

CI builds, tests and signs the APK (`.github/workflows/desktop-release.yml`).
To build it yourself you need JDK 17 or later and the Android SDK
(`ANDROID_HOME`). The Gradle plugin downloads the SDK platform it needs.

```bash
cd android && ./gradlew test lint assembleRelease
```

The output is unsigned: `build/outputs/apk/release/`. Android won't install an
unsigned APK, and an APK signed with any other key can't update the published
app.

The project has no runtime dependencies: everything comes from the Android
framework. `check-gradle-wrapper.sh` checks that `gradle-wrapper.jar` is the jar
Gradle publishes for the pinned version, and CI runs it before `./gradlew`.

## The signing key (once, for the maintainer)

Android installs an update only if it's signed with the same key as the app
already installed, so this key is permanent. If it's lost, every installed copy
has to be uninstalled and installed again. Until both secrets below exist, the
release workflow builds and tests the APK but doesn't publish it, and says so
in a warning. The web build and the desktop clients publish as usual.

Create the key on your own machine. `keytool` comes with any JDK.

```bash
keytool -genkeypair -keystore smylte-release.p12 -storetype PKCS12 -alias smylte -keyalg RSA -keysize 4096 -validity 36500 -dname "CN=Smylte"
```

Store it in the repository's Actions secrets on GitHub, where the release
workflow runs. Use `base64 -i smylte-release.p12` on macOS.

```bash
base64 -w0 smylte-release.p12 | gh secret set ANDROID_KEYSTORE_B64 -R nicholaskmitchell/smylte
```

```bash
gh secret set ANDROID_KEYSTORE_PASSWORD -R nicholaskmitchell/smylte
```

Keep `smylte-release.p12` and its password somewhere safe outside the
repository, such as a password manager. `.gitignore` refuses keystore files.

Only the `sign-android` job can read the key. It runs no Gradle and no
dependency code, only `zipalign` and `apksigner` from the runner's Android SDK.
The job that builds the APK never has the key.

## Tests

```bash
cd android && ./gradlew test
```

The JVM unit tests run without a device. They cover:

- the request split and the path-traversal guard;
- the CSP port's hashing, against vectors from `backend/smylted/csp.py`;
- unpacking the web build, including zip-slip and size limits;
- staging, swapping and recovering an interrupted swap;
- the update decisions and digest checks;
- the server address rules;
- the bar colours;
- the launcher icon against `frontend/public/favicon.svg`.

`backend/tests/test_csp.py` fails if `Csp.kt`'s directives drift from the
server's.

## Source layout

```
MainActivity.kt   the window: WebView, splash, update strip, back, file picker
SetupActivity.kt  the settings screen
LocalAssets.kt    answers the WebView's requests from the web build; the colour bridge
AssetRoutes.kt    which requests are answered locally, and the traversal guard
Csp.kt            Content-Security-Policy, a port of backend/smylted/csp.py
Updater.kt        release check, web build download, APK download and checks
WebBuild.kt       the web build on disk: stage, swap, recover
UpdatePolicy.kt   the update decisions
GitHub.kt         GitHub requests, with the token kept to api.github.com
Session.kt        server check and sign-in
Settings.kt       stored settings
PasswordVault.kt  AES-GCM under an Android keystore key
ServerAddress.kt  the server address rules
ThemeColour.kt    the page colour and the script that reports it
ApkProvider.kt    hands the downloaded APK to the installer
Insets.kt         edge to edge, clear of the bars and the keyboard
Background.kt     the one thread updates run on
Release.kt        where the release is
```
