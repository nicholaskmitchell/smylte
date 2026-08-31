import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/app.css'
import './styles/display.css'
import { App } from './App'
import { BookingPage } from './components/BookingPage'
import { DisplayView } from './components/DisplayView'

// /book/<token> is the public client-booking page: no session, no login — the
// branch happens before mount so the authed shell (and its /api/me call) never
// loads there. Everything else gets the normal app.
const booking = location.pathname.match(/^\/book\/([A-Za-z0-9_-]+)\/?$/)

// /display/<token> is a screen on a wall: no session, no login, and no input at
// all. It branches here for the same reason the booking page does — the device
// has no session and never will, so the authed shell would show a wall panel a
// login form. The token pattern is `token_urlsafe`'s alphabet, as above.
const display = location.pathname.match(/^\/display\/([A-Za-z0-9_-]+)\/?$/)

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {booking ? <BookingPage token={booking[1]} />
      : display ? <DisplayView token={display[1]} />
        : <App />}
  </React.StrictMode>,
)
