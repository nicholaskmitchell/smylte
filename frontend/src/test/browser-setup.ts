// Setup for the `browser` project only. Deliberately NOT `setup.ts`.
//
// That file's entire body is a hand-written `window.matchMedia` — correct for
// jsdom, which has none, and exactly wrong here. The media queries are half of
// what this project exists to test: a rule inside `@media (max-width: 720px)`
// that loses the cascade to a later declaration is invisible to a stub, because a
// stub answers a question about a query string and this project asks a question
// about a computed box.
//
// So: the jest-dom matchers (`toBeInTheDocument`, used by the anti-vacuity checks
// beside the measurements), the real stylesheets, and nothing else installed over
// the browser's own behaviour.
import { afterEach } from 'vitest'
import '@testing-library/jest-dom/vitest'

// The stylesheets, in `main.tsx`'s order — which is load-bearing. `app.css` comes
// after `tokens.css` so that, at equal specificity, app.css wins; several rules
// depend on that (the mobile `--gutter` re-declaration outranks the preset's only
// because of source order). Importing them in the wrong order here would make
// this project measure a cascade the app never has.
import '../styles/fonts.css'
import '../styles/tokens.css'
import '../styles/app.css'
// The display page's own sheet, last, as main.tsx loads it. It is here because
// what it asserts cannot be asserted anywhere else: a display is drawn in the
// app's three typefaces, and "which face won" is a question about the cascade
// and about `document.fonts`, neither of which jsdom has.
import '../styles/display.css'

afterEach(() => {
  // index.html's pre-paint script does not run in this project — vitest browser
  // mode serves its own harness page — so `<html>` starts clean, which is what
  // makes "measure the shipped default" possible at all. Anything a test sets to
  // measure a theme or a preset has to come back off, or it leaks into the next
  // file: the root element is the one piece of state the per-test container
  // teardown does not own.
  const root = document.documentElement
  delete root.dataset.theme
  delete root.dataset.preset
  root.removeAttribute('style')
  try { localStorage.clear() } catch { /* private mode */ }
})
