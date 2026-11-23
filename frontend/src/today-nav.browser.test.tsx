// Today's day arrows under Field notes (the owner's pick of 22 Nov, "Ink
// chevrons"), measured in a real browser. The markup is TodayView's `nav` as it
// renders under Field notes, class for class (TodayView.fieldnotes.test.tsx
// holds the JSX to it): two `.day-step` buttons carrying the pen's chevrons,
// and on a past day the coral `.day-home` with its drawn arrow.
import { beforeEach, describe, expect, it } from 'vitest'
import { box, mount, viewport } from './test/browser-measure'

beforeEach(() => { document.body.innerHTML = '' })

const chevron = (icon: 'left' | 'right') => `<svg class="icon-ink" data-icon="${icon}" viewBox="0 0 24 24" aria-hidden="true">`
  + `<path d="${icon === 'left' ? 'M14.6 6.2C12.6 8.2 10.6 10.2 9 12.1C10.7 13.9 12.7 15.9 14.8 17.9' : 'M9.4 6.1C11.4 8.1 13.4 10.1 15 12C13.3 13.9 11.3 15.9 9.2 17.8'}"/></svg>`
const HOME = '<button type="button" class="day-home">Today<svg class="day-home-ink" viewBox="0 0 21 14" aria-hidden="true">'
  + '<path d="M1.6 7.4c5.8-.5 11.9-.4 17.6.2"/><path d="M14.4 2.6c1.8 1.6 3.5 3.1 5 4.9-1.6 1.6-3.3 3.1-5.1 4.6"/></svg></button>'

/** Today's head on `back` days ago: 0 is today (› disabled, no way back). */
const head = (back: number) => `
  <div class="shell"><div class="content today-pane">
    <div class="content-head today-head fn-head">
      <div class="fn-date">
        <span class="fn-weekday">Wednesday</span><span class="fn-day">Nov 22</span>
        <div class="today-nav">
          <button type="button" class="icon-btn day-step" aria-label="Previous day"${back >= 14 ? ' disabled' : ''}>&#8249;${chevron('left')}</button>
          <button type="button" class="icon-btn day-step" aria-label="Next day"${back === 0 ? ' disabled' : ''}>&#8250;${chevron('right')}</button>
          ${back > 0 ? HOME : ''}
        </div>
      </div>
      <svg class="day-drawing fn-drawing" viewBox="0 0 160 200"></svg>
    </div>
  </div></div>`

const tone = (host: HTMLElement, token: string) => {
  const i = host.appendChild(document.createElement('i'))
  i.style.color = `var(${token})`
  return getComputedStyle(i).color
}

describe("Today's day arrows under Field notes", () => {
  it('are the pen\'s chevrons on bare --control-h squares, and the glyph paints nothing', async () => {
    await viewport(1440, 900)
    const host = await mount(head(1))
    for (const b of host.querySelectorAll<HTMLElement>('.day-step')) {
      const s = getComputedStyle(b)
      expect(box(b).w).toBeCloseTo(40, 0)
      expect(box(b).h).toBeCloseTo(40, 0)
      expect(s.fontSize).toBe('0px')
      expect(s.borderTopWidth).toBe('0px')
      expect(s.color).toBe(tone(host, '--fg'))
      const icon = box(b.querySelector('.icon-ink')!)
      expect(icon.w).toBe(24)
      // Centred in its square.
      expect(Math.abs(icon.left + icon.w / 2 - (box(b).left + box(b).w / 2))).toBeLessThanOrEqual(0.5)
    }
  })

  it('show a disabled arrow in --fg-faint', async () => {
    const host = await mount(head(0))
    const next = host.querySelector<HTMLElement>('[aria-label="Next day"]')!
    expect(next).toBeDisabled()
    expect(getComputedStyle(next).color).toBe(tone(host, '--fg-faint'))
  })

  it('offer the way back as a coral word with no box, as tall as the arrows', async () => {
    const host = await mount(head(1))
    const home = host.querySelector<HTMLElement>('.day-home')!
    const s = getComputedStyle(home)
    expect(s.color).toBe(tone(host, '--accent'))
    expect(s.backgroundColor).toBe('rgba(0, 0, 0, 0)')
    expect(s.borderTopWidth).toBe('0px')
    expect(box(home).h).toBeCloseTo(box(host.querySelector('.day-step')!).h, 0)
    expect(box(home.querySelector('.day-home-ink')!).w).toBe(21)
  })

  it.each([[1440, 900], [390, 844]])('keep the date where it is on a past day, at %ix%i', async (w, h) => {
    await viewport(w, h)
    const at = async (back: number) => {
      document.body.innerHTML = ''
      const host = await mount(head(back))
      return { weekday: box(host.querySelector('.fn-weekday')!).top, day: box(host.querySelector('.fn-day')!).top }
    }
    const today = await at(0)
    const yesterday = await at(1)
    expect(yesterday.weekday).toBeCloseTo(today.weekday, 0)
    expect(yesterday.day).toBeCloseTo(today.day, 0)
  })

  it.each([320, 360, 390])('fit beside the drawing on a past day at %ipx', async (w) => {
    await viewport(w, 700)
    const host = await mount(head(1))
    const nav = host.querySelector('.today-nav')!
    const last = nav.lastElementChild!
    expect(last).toHaveClass('day-home')
    expect(box(last).right, 'the way back runs into the drawing')
      .toBeLessThanOrEqual(box(host.querySelector('.fn-drawing')!).left)
    expect(document.scrollingElement!.scrollWidth).toBeLessThanOrEqual(w)
  })

  it('lines the first chevron up with the date', async () => {
    await viewport(390, 844)
    const host = await mount(head(1))
    const icon = box(host.querySelector('.day-step .icon-ink')!)
    const date = box(host.querySelector('.fn-day')!)
    expect(Math.abs(icon.left - date.left)).toBeLessThanOrEqual(1)
  })
})
