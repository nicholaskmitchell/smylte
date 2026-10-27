// The Home Suggested and Shares modules, measured in a real browser.
//
// Both put text someone else wrote beside controls in a card that may be as
// narrow as 238px (a desktop module at its three-column minimum) or 320px (a
// phone). Two things go wrong there and neither shows under jsdom, which
// computes no layout: a pair of buttons wider than the card scrolls the module
// sideways, and a name set on one line with its "last opened" text is squeezed
// to nothing. Hence raw markup, the real stylesheets, and
// `getBoundingClientRect()`, as `share.browser.test.tsx` does.
//
// Class-for-class from `SuggestedModule` and `SharesModule` in `HomeView.tsx`,
// inside the `.dash-mod > .dash-mod-body` that `HomeView` wraps each in, with
// German strings because they run longest.
import { describe, expect, it, beforeEach } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const SUGGESTED = `
  <ul class="dash-tasks dash-sug">
    <li class="dash-task dash-sug-row" data-kind="update">
      <span class="dash-sug-head">
        <span class="dash-sug-title" dir="ltr">Ergänzt „Zahnarzttermin verschieben“</span>
        <span class="dash-task-due mono">Mo., 26. Okt.</span>
      </span>
      <span class="dash-sug-meta">
        <span class="dash-sug-kind">Ergänzung</span>
        <span class="dash-sug-src">Dr. Müller-Lüdenscheidt</span>
        <span class="dash-sug-actions">
          <button type="button" class="btn ghost">Verwerfen</button>
          <button type="button" class="btn">Änderung übernehmen</button>
        </span>
      </span>
    </li>
    <li class="dash-task dash-sug-row" data-kind="task">
      <span class="dash-sug-head">
        <span class="dash-sug-title" dir="ltr">Steuererklärung abgeben</span>
      </span>
      <span class="dash-sug-meta">
        <span class="dash-sug-kind">Aufgabe</span>
        <span class="dash-sug-src">finanzamt@example.org</span>
        <span class="dash-sug-actions">
          <button type="button" class="btn ghost">Verwerfen</button>
          <button type="button" class="btn">Aufgabe hinzufügen</button>
        </span>
      </span>
    </li>
  </ul>`

const SHARES = `
  <ul class="dash-tasks">
    <li class="dash-task dash-share-row ">
      <span class="dash-share-info">
        <span class="dash-task-title" id="name" dir="ltr">Großmutter und Großvater</span>
        <span class="dash-share-meta mono">Zuletzt geöffnet Mo., 26. Okt., 14:32</span>
        <span class="dash-share-note">Aus, seit sich deine Anmeldung geändert hat</span>
      </span>
      <button type="button" class="menu-toggle" id="switch" aria-pressed="false">Aus</button>
    </li>
  </ul>`

const section = (body: string, style: string) => `
  <section class="dash-mod" style="${style}">
    <header class="dash-mod-head"><span class="label">Module</span></header>
    <div class="dash-mod-body" id="body">${body}</div>
  </section>`

// The phone stacks its modules in `.dash-stack`, which gives them the width less
// its gutters. The desktop grid sizes a module in columns; 238px is what a
// three-column minimum comes to on a narrow window, so it is set outright.
const FRAMES: [string, number, (body: string) => string][] = [
  ['a 320px phone', 320, (body) =>
    `<div class="scroll dash-stack">${section(body, '')}</div>`],
  ['a 238px desktop module', 1000, (body) =>
    `<div class="dash-grid">${section(body, 'position: static; height: auto; width: 238px')}</div>`],
]

describe.each(FRAMES)('the Home modules in %s', (_name, width, frame) => {
  it('is a real browser with the app’s stylesheet loaded', async () => {
    // The vacuity guard `share.browser.test.tsx` argues for: under jsdom every
    // box is 0x0 and everything below would pass for the wrong reason.
    await viewport(width)
    const host = await mount(frame(SHARES))
    expect(box(host.querySelector('#switch')!).w, 'no layout — this is not a browser').toBeGreaterThan(0)
    expect(box(host.querySelector('.dash-mod')!).w).toBeLessThanOrEqual(width)
  })

  it('does not scroll the Suggested module sideways, buttons and all', async () => {
    await viewport(width)
    const host = await mount(frame(SUGGESTED))
    const body = host.querySelector('#body')!
    expect(body.scrollWidth, `the module widened to ${body.scrollWidth}`)
      .toBeLessThanOrEqual(body.clientWidth + 1)
    for (const b of host.querySelectorAll('.dash-sug-actions .btn')) {
      expect(box(b).right, `${b.textContent} runs past the module`)
        .toBeLessThanOrEqual(box(body).right + 0.5)
    }
  })

  it('gives a share’s name a line of its own, left of the switch', async () => {
    await viewport(width)
    const host = await mount(frame(SHARES))
    const body = host.querySelector('#body')!
    const name = host.querySelector('#name')!
    const sw = host.querySelector('#switch')!
    expect(box(name).w, 'the name was squeezed').toBeGreaterThanOrEqual(80)
    expect(box(name).right, 'the name runs under the switch').toBeLessThan(box(sw).left)
    expect(body.scrollWidth, `the module widened to ${body.scrollWidth}`)
      .toBeLessThanOrEqual(body.clientWidth + 1)
  })
})
