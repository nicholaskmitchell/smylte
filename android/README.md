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

### Where your server runs

The app doesn't care how Smylte is hosted, only that the phone can reach it at
an `https://` address, with a certificate Android trusts, and with Smylte at the
root of that address. How that works out for common setups:

| Hosting | Works? | Notes |
| --- | --- | --- |
| Tailscale Funnel | Yes | The public `https://<machine>.<tailnet>.ts.net` address and its certificate work as they are. |
| Tailscale, tailnet only (`tailscale serve` without Funnel) | Only while the phone's Tailscale app is connected | Any later background feature, such as reminders, will also need it connected. |
| Cloudflare Tunnel (`docs/DEPLOY.md`) | Yes | — |
| Cloudflare Access, or any proxy that asks you to sign in through a web page before letting requests through | No, when it covers `/api` | The app's API calls are redirected to the sign-in page instead of getting data, and the app never shows that page. The desktop clients have the same limitation. Leave `/api` to Smylte's own sign-in. |
| Your own reverse proxy with a public certificate (Caddy, nginx, Let's Encrypt) | Yes | — |
| Plain `http://`, a self-signed certificate, or a private CA | No | The sign-in cookie is `Secure`, Android refuses cleartext, and the app trusts only the system's certificate authorities. |

This is about the app, not the server's own setup. One server point does vary
with hosting, though. Sign-in and booking are rate-limited per client address,
which Smylte reads from `X-Real-IP`, and the provided Caddy snippet fills that
in from a Cloudflare header. Behind anything other than Cloudflare, that header
must come from whatever terminates TLS, and any copy a client sends must be
discarded. Otherwise the limits can be bypassed, or every client shares one
limit. See `docs/DEPLOY.md` step 3.

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
mobile data often shares its address with many others. Smylte keeps its checks
rare: a start within ten minutes of the last check reuses that check's answer,
and while the app is open it checks again only after six hours. A failed check
never stops the app from opening. If checks keep failing, add a GitHub token in
**Server settings**: it raises the limit, and with a token an unchanged release
(a 304 answer) doesn't count against it at all. A token with no scopes is
enough.

## Settings

Long-press the Smylte icon and choose **Server settings**. The same screen opens
on first run and from the error screen if the app can't start.

- **Server address**: checked against `/api/me` before it's saved.
- **Username and password**: optional. With a password saved, Smylte signs in
  by itself when the session runs out (the server's sessions last seven days).
  It checks the existing session first, so it doesn't sign in again on every
  start. Leave the password empty to sign in on the app's own screen, where
  password managers can fill it. A saved password is tied to the server address
  it was saved with: change the address and Smylte asks for the password again
  rather than sending the old one to the new server.
- **GitHub token**: optional; see above.

The password and the token are encrypted with AES-GCM under a key that the
Android keystore generates and never releases, so a copy of the app's files is
useless without the phone. The password is encrypted for its server address, so
it can't be decrypted for any other. As on the desktop, this doesn't stop code
running as the app from reading them.

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
| `cache/export/` | A file being saved, while Android's save dialog is open, in case Android closes Smylte meanwhile |
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
- **Saving a file asks where.** Theme export opens Android's own save dialog,
  where you choose the folder (or a cloud drive) and the name. Theme import
  works as in a browser.
- **The clock starts from the phone's.** If your account has never been set to
  a 12- or 24-hour clock, Smylte uses the phone's setting and saves it to your
  account the first time it opens, so reminders, the daily digest and wall
  displays match. After that, Smylte's own clock setting decides on every
  device, and changing the phone's setting doesn't change it.
- **Back closes what is open.** Back closes the top dialog, sheet or menu,
  then goes back through the app's pages, then leaves Smylte. A form with
  unsaved changes asks before discarding them, and Back on that question keeps
  editing.
- **Taps can be felt.** Ticking a task, flipping a switch and an action that
  fails each give a short vibration, as the phone's own controls do. It
  follows the phone's touch feedback setting and answers only a touch, so
  TalkBack (which has its own) and a keyboard get none.
- **The splash screen stays until the app is ready.** On Android 12 and
  later the phone's splash screen, with Smylte's icon, stays up until Smylte
  has signed in, or shown its sign-in screen or its offline notice. It never
  stays longer than three seconds: on a slow connection Smylte's own
  "Starting…" screen then says what it's waiting for.

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
framework.

The build tooling is checked in three places:

- `check-gradle-wrapper.sh` checks that `gradle-wrapper.jar` is the jar Gradle
  publishes for the pinned version. CI runs it before `./gradlew`.
- The Gradle distribution is pinned by checksum in `gradle-wrapper.properties`.
- Every plugin and library Gradle downloads is checked against
  `gradle/verification-metadata.xml`.

After changing a plugin or dependency version, regenerate that file on an empty
Gradle cache and review the diff:

```bash
GRADLE_USER_HOME=$(mktemp -d) ./gradlew --write-verification-metadata sha256 test lint assembleRelease assembleDebug
```

`aapt2` ships a separate jar for each operating system. The generated file
covers only the one you built on, so add the other two by hand, as the existing
entries show.

## The signing key (once, for the maintainer)

Android installs an update only if it's signed with the same key as the app
already installed, so this key is permanent, and there is no revoking it. If
it's lost, every installed copy has to be uninstalled and installed again; if
it leaks, whoever has it can sign an update that every phone accepts. Until it
is set up, the release workflow builds and tests the APK but doesn't publish
it, and says so in a warning. The web build and the desktop clients publish as
usual.

**1. Create a GitHub environment that only `main` can use.** The key goes in
this environment, not in the repository's secrets: a repository secret can be
read by a workflow on any branch that anyone with push access creates.

```bash
gh api -X PUT repos/nicholaskmitchell/smylte/environments/android-signing -F 'deployment_branch_policy[protected_branches]=false' -F 'deployment_branch_policy[custom_branch_policies]=true'
```

```bash
gh api -X POST repos/nicholaskmitchell/smylte/environments/android-signing/deployment-branch-policies -f name=main -f type=branch
```

You can do the same in the repository's settings under **Environments**: add
`android-signing` and set **Deployment branches and tags** to `main` only.

**2. Create the key** on your own machine. `keytool` comes with any JDK.

```bash
keytool -genkeypair -keystore smylte-release.p12 -storetype PKCS12 -alias smylte -keyalg RSA -keysize 4096 -validity 36500 -dname "CN=Smylte"
```

**3. Store it in the environment.** Use `base64 -i smylte-release.p12` on
macOS.

```bash
base64 -w0 smylte-release.p12 | gh secret set ANDROID_KEYSTORE_B64 --env android-signing -R nicholaskmitchell/smylte
```

```bash
gh secret set ANDROID_KEYSTORE_PASSWORD --env android-signing -R nicholaskmitchell/smylte
```

**4. Optional, recommended: pin the certificate.** With this set, a release
signed by any other key fails in CI, so a swapped or mistyped secret can't
reach phones that would refuse it. Print the fingerprint:

```bash
keytool -list -v -keystore smylte-release.p12 -alias smylte | grep SHA256
```

Then store it as a repository variable. Colons are fine.

```bash
gh variable set ANDROID_SIGNING_CERT_SHA256 -R nicholaskmitchell/smylte
```

Keep `smylte-release.p12` and its password somewhere safe outside the
repository, such as a password manager. `.gitignore` refuses keystore files.

Only the `sign-android` job uses the key, and it runs only for `main`. It runs
no Gradle, no dependency code and no native parser: only `apksigner` from the
runner's Android SDK, between the two GitHub artifact actions, with a token
that has no permissions.

Keeping the key out of the build keeps it secret, but it doesn't make the build
trustworthy. That is what the checksums above and the `inspect-android` job are
for. That job holds nothing. It reads the APK first and refuses one that:

- isn't `com.nicholaskmitchell.smylte`;
- is debuggable;
- sets `versionCodeMajor`;
- has a version code ahead of the clock.

`sign-android` signs only the file whose SHA-256 it reported.

Only the newest commit on `main` publishes. A re-run of an older run on `main`
publishes nothing, so it can't roll phones back.

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
- the page bridge: exactly which methods the page can call, that release builds
  keep them, that `android.ts` declares the same methods, and what each accepts;
- the bridge's rules: capabilities, the env and its events, a saved file's type,
  name and size, the wait between save dialogs, where a save's result is shown,
  touch tracking, when a haptic may play and which one each name plays on each
  Android version, where Back goes, which page a count of open layers
  belongs to, and when the splash screen is held and what ends it;
- that the page and the window agree on the event, its outcomes, the env
  version and the env's fields, every event type, the haptic names and the `ready`
  capability (against `frontend/src/android.ts`), that the window never
  overrides the system's touch feedback setting, and that the splash never waits
  on anything that needs a drawn window;
- the text zoom, and the body size it is measured at, against the stylesheet;
- the launcher icon against `frontend/public/favicon.svg`.

`backend/tests/test_csp.py` fails if `Csp.kt`'s directives drift from the
server's.

## Checks on a phone

The tests above run without a device. What only a phone can show is checked
by hand, on Android 12 or later and on Android 11 where a check names it,
before a release that changes it.

### Start-up and the splash screen

Time a cold start with the launcher's own intent. A start without the
`LAUNCHER` category never holds the splash, so `am start -n` alone measures
nothing:

```bash
adb shell am start -W -S -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n com.nicholaskmitchell.smylte/.MainActivity
```

`TotalTime` is when the window first drew, which is when the splash ended.

- **Signed in, fast network.** The icon stays until the app's tabs appear, with
  no "Starting…" in between. Record five starts on Wi-Fi and five on mobile
  data. Times well under 3000 ms show the page ran while the window was held.
  If every start takes 3000 ms or more, the WebView is starved while held and
  only the cap ends the splash: record it. If most starts on mobile data reach
  3000 ms, record that too, for the owner's choice of cap.
- **Signed out** (Log out in Settings, then start): the splash ends on the
  sign-in screen.
- **Server stopped, phone online:** the splash ends on the app with its offline
  notice, or at about 3 s on "Starting…".
- **A network that hangs** (a Wi-Fi network without internet access): the splash
  ends at about 3 s and "Starting…" shows its progress. `TotalTime` is about
  3000 ms, never near 5000.
- **Start-up fails:** block GitHub on the phone's network (a Private DNS or
  router block on `github.com` and `objects.githubusercontent.com`), clear
  Smylte's storage, set it up again (setup needs only the server), force-stop it
  and start it from the launcher. The failure screen, with Retry and Server
  settings, shows as soon as the check fails, not after 3 s.
- **Input during the splash:** on a slow start, tap the screen and press Back
  and a hardware key repeatedly. No "isn't responding" dialog appears.
- **TalkBack:** on a cold start TalkBack reads nothing from Smylte until the
  splash ends, never "Starting…" behind it, then reads the first screen.
- **The end of the splash:** nothing jumps under the status bar, and the bars
  take the page's colours.
- **No blank window on recreation.** With the app open, change the wallpaper (or
  the colour palette in Wallpaper & style), which rebuilds the window: the page
  returns with no splash and no blank pause. With Developer options' "Don't keep
  activities" on, leave Smylte and return from Recents. Then `adb shell am kill
  com.nicholaskmitchell.smylte` while it is in the background, and return. Each
  time, record what shows; it is never a blank window for longer than a flash.
  (A renderer crash rebuilds the window the same way, but can't be caused on
  demand.)
- **First run:** after Server settings is saved for the first time, the window
  opens on "Starting…" without a frozen settings screen or a blank pause.
- **After an app update:** Open in the installer holds the splash as the
  launcher does.
- **Hot start:** with Smylte in the background, open it again. There is no
  splash, and the page is as it was.
- **Android 11:** no change: "Starting…", then the app.
- **Version skew:** with the APK from before this change and the new web build,
  the start is as before (icon, "Starting…", the app) and the app works. With
  this APK and a web build from before this change (installed while the release
  still carries the old one), the splash ends when the page has loaded. Record
  any blank frame before the tabs appear.

## Source layout

```
MainActivity.kt   the window: WebView, splash, update strip, back, haptics, file picker and saves
SetupActivity.kt  the settings screen
LocalAssets.kt    answers the WebView's requests from the web build
PageBridge.kt     what the page can ask of the window (window.SmylteAndroid)
HostProtocol.kt   the bridge's rules and messages, free of Android classes so they are tested
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
TextZoom.kt       the page's text size, from the system font size
ApkProvider.kt    hands the downloaded APK to the installer
Insets.kt         edge to edge, clear of the bars and the keyboard
Background.kt     the threads updates and file saves run on
Release.kt        where the release is
```
