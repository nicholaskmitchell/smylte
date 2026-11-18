// Field notes' Home, measured in a real browser: the module heads and rows are
// set as Today's are, and a done row keeps no line-through of its own (the
// drawn strike stands in for it). jsdom computes no cascade, so the rules in
// fieldnotes.css's "cp3 · Home" block can only be checked here.

import { afterEach, describe, expect, it, beforeEach } from 'vitest'
import { mount } from './test/browser-measure'
import { applyDesign } from './appearance'

beforeEach(() => {
  document.body.innerHTML = ''
  document.documentElement.dataset.surface = 'app'
})

afterEach(() => { applyDesign(document.documentElement, null) })

const HOME = `
  <div class="shell"><div class="work"><div class="content"><div class="scroll">
    <div class="dash-grid">
      <section class="dash-mod" style="left:0;width:50%;top:0;height:200px">
        <header class="dash-mod-head"><span class="label">Today</span></header>
        <div class="dash-mod-body">
          <ul class="dash-tasks">
            <li class="dash-task done"><span class="list-dot"></span>
              <span class="dash-task-title">Ship it</span></li>
          </ul>
          <div class="mini-dots"><span class="mini-dot"></span></div>
        </div>
      </section>
    </div>
  </div></div></div></div>`

describe('Field notes Home', () => {
  it('sets a module head as a margin note in the ink colour, with no rule under it', async () => {
    const host = await mount(HOME)
    const label = getComputedStyle(host.querySelector('.dash-mod-head > .label')!)
    expect(label.fontFamily).toMatch(/Newsreader/)
    expect(label.textTransform).toBe('none')
    const probe = document.createElement('span')
    probe.style.color = 'var(--fg)'
    host.appendChild(probe)
    expect(label.color).toBe(getComputedStyle(probe).color)
    const head = getComputedStyle(host.querySelector('.dash-mod-head')!)
    expect(head.borderBottomColor).toBe('rgba(0, 0, 0, 0)')
  })

  it('draws the mini calendar\'s dots round', async () => {
    const host = await mount(HOME)
    expect(getComputedStyle(host.querySelector('.mini-dot')!).borderRadius).toBe('50%')
  })

  it('leaves a done row\'s line to the drawn strike', async () => {
    const host = await mount(HOME)
    const title = host.querySelector('.dash-task.done .dash-task-title')!
    expect(getComputedStyle(title).textDecorationLine).toBe('none')
  })

  it('keeps the presets as they were', async () => {
    const host = await mount(HOME)
    applyDesign(document.documentElement, 'refined')
    const label = getComputedStyle(host.querySelector('.dash-mod-head > .label')!)
    expect(label.fontFamily).not.toMatch(/Newsreader/)
    expect(getComputedStyle(host.querySelector('.dash-mod-head')!).borderBottomColor)
      .not.toBe('rgba(0, 0, 0, 0)')
  })
})
