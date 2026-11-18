// Field notes' calm Tasks rows, measured in a real browser.
//
// A row's "+ sub" and "del" are hidden with opacity and pointer-events until
// the row is in use, and whether that wins over app.css's own `.task-actions`
// rules (which show them on hover and on every touchscreen) is a question
// about the cascade that jsdom cannot answer. So is the row's type: the title
// is set as Today's is, and the tick has to stay on its first line.

import { describe, expect, it, beforeEach } from 'vitest'
import { mount, viewport } from './test/browser-measure'
import { applyDesign } from './appearance'

beforeEach(() => {
  document.body.innerHTML = ''
  // The shipped design, which the browser setup already switches on; said again
  // here because this file is about nothing else.
  document.documentElement.dataset.surface = 'app'
})

/** A row in the list pane, where TasksView puts it: the page's own `.scroll`
 *  inside a `.content` that names its pane. */
const PANE = `
  <div class="shell"><div class="work"><div class="content" data-pane="list"><div class="scroll">
    <div class="task-drag"><div class="task"><div class="pri-bar"></div><span class="twisty-gap"></span>
      <button class="check">&#10003;</button>
      <div class="task-body" role="button" tabindex="0"><div class="task-title"><span class="list-dot"></span>Plan a trip</div>
        <div class="task-meta"><span class="due">&#9719; Sep 23</span></div></div>
      <div class="task-actions"><button>+ sub</button><button class="danger">del</button></div>
    </div></div>
  </div></div></div></div>`

/** Let a started opacity transition finish, so the value read is the one it
 *  settles on (see today-calm.browser.test.tsx). */
async function settle(...els: Element[]) {
  els.forEach((el) => getComputedStyle(el).opacity)
  for (const a of document.getAnimations()) a.finish()
  await new Promise(requestAnimationFrame)
}

const look = (el: Element) => {
  const s = getComputedStyle(el)
  return { opacity: s.opacity, pointerEvents: s.pointerEvents }
}

describe('Field notes Tasks rows keep their tools out of sight until asked', () => {
  it('hides "+ sub" and "del" at rest', async () => {
    const host = await mount(PANE)
    const tools = host.querySelector('.task-actions')!
    await settle(tools)
    expect(look(tools)).toEqual({ opacity: '0', pointerEvents: 'none' })
  })

  it('shows them when focus is anywhere in the row', async () => {
    const host = await mount(PANE)
    const tools = host.querySelector('.task-actions')!
    host.querySelector<HTMLElement>('.task-body')!.focus()
    await settle(tools)
    expect(look(tools)).toEqual({ opacity: '1', pointerEvents: 'auto' })
  })

  it('leaves the presets as they were', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(PANE)
    const tools = host.querySelector('.task-actions')!
    await settle(tools)
    // app.css fades them in on hover, and never takes the pointer away.
    expect(getComputedStyle(tools).pointerEvents).toBe('auto')
  })
})

describe('a Field notes Tasks row reads as Today\'s', () => {
  const centre = (el: Element) => { const r = el.getBoundingClientRect(); return (r.top + r.bottom) / 2 }

  it.each([1200, 390])('at %ipx', async (w) => {
    await viewport(w)
    const host = await mount(PANE)
    const title = host.querySelector('.task-title')!
    const cs = getComputedStyle(title)
    expect(cs.fontFamily).toMatch(/^"?Newsreader/)
    expect(cs.fontSize).toBe('20px')
    // The tick on the title's first line: half the item line (`--today-line`,
    // which the title takes as its line-height) down its top.
    const line = parseFloat(cs.lineHeight)
    expect(line, 'the title has no line in px, so the check below is vacuous').toBe(25)
    const top = title.getBoundingClientRect().top
    expect(Math.abs(centre(host.querySelector('.task > .check')!) - top - line / 2),
      'the tick is off its title\'s first line').toBeLessThanOrEqual(0.5)
  })
})
