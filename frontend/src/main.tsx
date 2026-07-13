import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './styles/app.css'
import { App } from './App'
import { BookingPage } from './components/BookingPage'

// /book/<token> is the public client-booking page: no session, no login — the
// branch happens before mount so the authed shell (and its /api/me call) never
// loads there. Everything else gets the normal app.
const booking = location.pathname.match(/^\/book\/([A-Za-z0-9_-]+)\/?$/)

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {booking ? <BookingPage token={booking[1]} /> : <App />}
  </React.StrictMode>,
)
