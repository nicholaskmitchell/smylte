import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/app.css'
import './styles/classic.css'
// The sidebar layout's frame, after Classic's levers: everything in it is
// scoped to that frame, so where it sits in the order matters only as the
// tiebreak for rules of equal specificity (see the sheet's header).
import './styles/layout.css'
import './styles/display.css'
import { App } from './App'
import { BookingPage } from './components/BookingPage'
import { DisplayView } from './components/DisplayView'
import { SharePage } from './components/SharePage'
import { markReady, startAndroidHost } from './android'
import { startCaptionSync } from './desktop'
import { startSystemAccent } from './system-accent'

// /book/<token> is the public client-booking page: no session, no login — the
// branch happens before mount so the authed shell (and its /api/me call) never
// loads there. Everything else gets the normal app.
const booking = location.pathname.match(/^\/book\/([A-Za-z0-9_-]+)\/?$/)

// /display/<token> is a screen on a wall: no session, no login, and no input at
// all. It branches here for the same reason the booking page does — the device
// has no session and never will, so the authed shell would show a wall panel a
// login form. The token pattern is `token_urlsafe`'s alphabet, as above.
const display = location.pathname.match(/^\/display\/([A-Za-z0-9_-]+)\/?$/)

// /share/<token> is a read-only page for a person who has no account here. It
// branches for the same reason the two above do — its reader has no session and
// never will — and takes the same `token_urlsafe` alphabet.
const share = location.pathname.match(/^\/share\/([A-Za-z0-9_-]+)\/?$/)

// Keep the Windows client's caption bar in step with the theme. A no-op in a
// browser, where /desktop/appearance does not exist — and started here rather
// than inside App so the booking and display routes get it too: a wall panel
// and a booking page have themes as much as the app does.
startCaptionSync()

// Read the Android client's facts before anything renders: `hello` is
// synchronous, so they are known on the first render. Started here for the same
// reason as the caption sync, so every route gets it, and a no-op in a browser
// and in the desktop clients.
startAndroidHost()

// This phone's accent from the wallpaper, when its switch is on, before the
// first frame: App paints it again after its own tokens, but only after the
// first paint, and the tab strip would open on the theme's accent until then.
// The app's own route only, because App is what keeps it current afterwards;
// the routes without a sign-in show the theme as they find it. A no-op in a
// browser, in the desktop clients and on Android 11.
if (!booking && !display && !share) startSystemAccent()

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {booking ? <BookingPage token={booking[1]} />
      : display ? <DisplayView token={display[1]} />
        : share ? <SharePage token={share[1]} />
          : <App />}
  </React.StrictMode>,
)

// The routes without a sign-in have nothing to wait for, so they tell the
// Android client their first view is up as soon as it has been handed to
// React, and its splash screen ends. App says so itself, when its sign-in
// check answers. A no-op in a browser and in the desktop clients.
if (booking || display || share) markReady()
