// On and off under Field notes, measured in a real browser: a setting that is
// on or off is a drawn checkbox beside its word (a <button aria-pressed>
// carrying CheckInk), and the seven native checkboxes are drawn the same way
// over the input (`.box-ink`). The markup is the components', class for class;
// controls-ink.test.ts holds the JSX to it.
import { beforeEach, describe, expect, it } from 'vitest'
import { applyDesign } from './appearance'
import { box, mount, over, paint, ratio, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const CHECK = '<svg class="check-ink" viewBox="0 0 28 28" aria-hidden="true">'
  + '<path class="check-frame" d="M5.2 4.6C10 4.1 18.4 4.3 23.1 5.2C23.8 10 23.6 18.3 22.9 23.2C18 23.7 9.8 23.9 4.9 23.1C4.3 18.4 4.4 9.6 5.2 4.6Z"/>'
  + '<path class="check-tick ink" pathLength="1" d="M8.6 14.6C10 15.8 11.4 17.6 12.4 19C14.6 14.4 18.6 9.2 23.8 5.8"/></svg>'

const toggle = (on: boolean) =>
  `<button class="menu-toggle" aria-pressed="${on}">${CHECK}${on ? 'On' : 'Off'}</button>`
const tick = (el: Element) => getComputedStyle(el.querySelector('.check-tick')!)

describe('a setting that is on or off', () => {
  it.each(['light', 'dark'])('is a drawn box beside its word, with no face, %s', async (theme) => {
    document.documentElement.dataset.theme = theme
    const host = await mount(`<div class="shell" style="background: var(--bg)"><div class="menu-row">
      <label>Chime</label>${toggle(true)}${toggle(false)}</div></div>`)
    const [on, off] = host.querySelectorAll('.menu-toggle')
    const bg = paint(getComputedStyle(host.querySelector('.shell')!).backgroundColor)
    for (const t of [on, off]) {
      const s = getComputedStyle(t)
      expect(paint(s.backgroundColor)[3], 'a face').toBe(0)
      expect(paint(s.borderTopColor)[3], 'an edge').toBe(0)
      expect(getComputedStyle(t, '::before').content, 'the highlighter swipe').toBe('none')
      expect(box(t.querySelector('.check-ink')!).w).toBe(26)
      // The word reads on its ground.
      expect(ratio(over(paint(s.color), bg), bg)).toBeGreaterThanOrEqual(4.5)
      // The box is the control's edge, in ink.
      expect(ratio(over(paint(getComputedStyle(t.querySelector('.check-frame')!).stroke), bg), bg))
        .toBeGreaterThanOrEqual(3)
    }
    expect(tick(on).opacity).toBe('1')
    expect(tick(on).strokeDashoffset).toMatch(/^0(px)?$/)
    expect(tick(off).opacity).toBe('0')
    // On and off are told apart by more than the tick: the word steps back.
    expect(getComputedStyle(on).color).not.toBe(getComputedStyle(off).color)
  })

  it.each(['light', 'dark'])('keeps a face and no swipe for a setting whose words name its value, %s', async (theme) => {
    // "Shown" / "Hidden" and the like: a check beside a value word would read as
    // its negation, so these keep the face, and the highlighter's swipe (which
    // says "on") stays off them; a plain on/off toggle beside them still has it.
    document.documentElement.dataset.theme = theme
    const host = await mount(`<div class="shell" style="background: var(--bg)"><div class="menu-row">
      <button class="menu-toggle" aria-pressed="true" data-value="">Shown</button>
      <button class="menu-toggle" aria-pressed="true">12-hour</button></div></div>`)
    const [value, plain] = host.querySelectorAll('.menu-toggle')
    const s = getComputedStyle(value)
    expect(getComputedStyle(value, '::before').content, 'the swipe on a value toggle').toBe('none')
    expect(paint(s.backgroundColor)[3], 'a face').toBeGreaterThan(0)
    expect(paint(s.borderTopColor)[3], 'an edge at rest').toBe(0)
    expect(getComputedStyle(plain, '::before').content, 'the swipe on a plain pressed toggle').not.toBe('none')
  })

  it('keeps the face for a setting that cycles', async () => {
    const host = await mount('<div class="shell"><button class="menu-toggle">12-hour</button></div>')
    expect(paint(getComputedStyle(host.querySelector('.menu-toggle')!).backgroundColor)[3]).toBeGreaterThan(0)
  })

  it('is the old toggle under a preset', async () => {
    applyDesign(document.documentElement, 'refined')
    const host = await mount(`<div class="shell">${toggle(true)}</div>`)
    expect(getComputedStyle(host.querySelector('.check-ink')!).display).toBe('none')
  })
})

describe('a checkbox', () => {
  const ROW = (checked: boolean, disabled = false) => `<div class="shell"><div class="menu-row"><label for="c">Shortcut</label>
    <span class="box-ink"><input id="c" type="checkbox"${checked ? ' checked' : ''}${disabled ? ' disabled' : ''} />${CHECK}</span></div></div>`

  it('is the drawn box over the unpainted input, ticked while checked', async () => {
    const host = await mount(ROW(true) + ROW(false))
    const [yes, no] = host.querySelectorAll<HTMLInputElement>('input')
    for (const i of [yes, no]) {
      expect(getComputedStyle(i).appearance).toBe('none')
      expect(box(i).w).toBe(22)
      const frame = box(i.parentElement!.querySelector('.check-ink')!)
      // The drawing sits over the input it stands for.
      expect(Math.abs(frame.left + frame.w / 2 - (box(i).left + box(i).w / 2))).toBeLessThanOrEqual(0.5)
    }
    expect(tick(yes.parentElement!).opacity).toBe('1')
    expect(tick(no.parentElement!).opacity).toBe('0')
  })

  it('still toggles from its label', async () => {
    const host = await mount(ROW(false))
    const input = host.querySelector<HTMLInputElement>('input')!
    host.querySelector<HTMLLabelElement>('label')!.click()
    expect(input.checked).toBe(true)
    await new Promise(requestAnimationFrame)
    expect(tick(input.parentElement!).opacity).toBe('1')
  })

  it('is the browser\'s checkbox, laid out as before, under a preset', async () => {
    await viewport(1024)
    applyDesign(document.documentElement, 'refined')
    const host = await mount(ROW(true)
      + '<div class="shell"><div class="menu-row"><label>Shortcut</label><input id="bare" type="checkbox" checked /></div></div>')
    const wrapped = host.querySelector<HTMLInputElement>('.box-ink > input')!
    const bare = host.querySelector<HTMLInputElement>('#bare')!
    expect(getComputedStyle(wrapped.parentElement!).display).toBe('contents')
    expect(getComputedStyle(wrapped).appearance).not.toBe('none')
    expect(box(wrapped).w).toBe(box(bare).w)
    expect(box(wrapped).left).toBe(box(bare).left)
  })
})
