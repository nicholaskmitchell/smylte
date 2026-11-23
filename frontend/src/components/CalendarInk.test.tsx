import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import {
  box, circled, CrossInk, GridInk, gridPaths, MonthInk, rand, ruled, TodayInk, type GridGeo,
} from './CalendarInk'

// The server's path alphabet (drawing.ts, PATH) less L and Z: the hand draws curves only.
const PATH = /^[MC0-9 .-]+$/
const geo: GridGeo = {
  w: 1203, h: 811, xs: [171.4, 343.3, 515.1, 687, 858.9, 1030.7],
  ys: [-0.5, 35.2, 139, 243, 353, 506, 609, 810.5], focus: null,
}
const numbers = (d: string) => [...d.matchAll(/(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)/g)].map((m) => [Number(m[1]), Number(m[2])])

describe("the calendar's hand", () => {
  it('rules a line in the pen\'s alphabet, the same for the same seed', () => {
    const a = ruled(0, 0, 0, 100, rand(7))
    expect(a).toMatch(PATH)
    expect(ruled(0, 0, 0, 100, rand(7))).toBe(a)
    expect(ruled(0, 0, 0, 100, rand(8))).not.toBe(a)
  })
  it('keeps a ruled line within its bow of the ruler', () => {
    for (const [x] of numbers(ruled(50, 0, 50, 800, rand(3)))) expect(Math.abs(x - 50)).toBeLessThan(3)
  })
  it('draws nothing for a line of no length', () => {
    expect(ruled(5, 5, 5, 5, rand(1))).toBe('')
  })
  it('circles in one open stroke', () => {
    const d = circled(20, 14, 16, 10.5, rand(2))
    expect(d).toMatch(PATH)
    expect(d.match(/M/g)).toHaveLength(1)
  })
  it('boxes with four strokes', () => {
    expect(box(0, 0, 40, 30, rand(4)).match(/M/g)).toHaveLength(4)
  })
  it('rules the month: six columns, eight rows, the page\'s frame heavier', () => {
    const p = gridPaths(geo, 'page|2026-11', null)
    expect(p.map((x) => x.cls)).toEqual([
      ...Array(6).fill('rule v'), 'rule h edge', ...Array(6).fill('rule h'), 'rule h edge'])
    for (const x of p) expect(x.d).toMatch(PATH)
    expect(gridPaths(geo, 'page|2026-11', null)).toEqual(p)
    expect(gridPaths(geo, 'page|2026-12', null)[0].d).not.toBe(p[0].d)
  })
  it("boxes the phone's chosen day in a hand of its own", () => {
    const p = gridPaths({ ...geo, focus: [0, 351, 171, 505] }, 'page|2026-11', 'focus|2026-11-22')
    expect(p).toHaveLength(15)
    expect(p[14].cls).toBe('focus')
    expect(p.slice(0, 14)).toEqual(gridPaths(geo, 'page|2026-11', null))
  })
})

describe("the calendar's marks", () => {
  it('are aria-hidden svg with no title and no text', () => {
    const { container } = render(<div><TodayInk day="2026-11-22" /><CrossInk day="2026-11-21" /><MonthInk /></div>)
    const svgs = [...container.querySelectorAll('svg')]
    expect(svgs.map((s) => s.getAttribute('class'))).toEqual(['today-ink', 'cross-ink', 'month-ink'])
    for (const s of svgs) {
      expect(s).toHaveAttribute('aria-hidden', 'true')
      expect(s.querySelector('title')).toBeNull()
    }
    expect(container.textContent).toBe('')
  })
  it('rules nothing where nothing is laid out', () => {
    const { container } = render(<div className="cal-grid"><GridInk seed="page|2026-11" focus={null} /></div>)
    const svg = container.querySelector('svg.grid-ink')!
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg.querySelectorAll('path')).toHaveLength(0)
  })
})
