// The day's drawing on the client: the payload is checked to the letter before
// it reaches the DOM, the conditions agree with the server's, and the renderer
// marks exactly the parts the day's state calls for.
import { render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import fixture from './test/drawing-fixture.json'
import { DayDrawing } from './components/DayDrawing'
import { EMPTY_DAY, cacheDrawing, evaluate, readCachedDrawing, sanitizeDrawing, type Atom, type DayState } from './drawing'
import { setCacheUser } from './cache'

const day = (over: Partial<DayState>): DayState => ({ ...EMPTY_DAY, nothingPlanned: false, ...over })

describe('conditions, as the server writes them (conditions.py)', () => {
  const cases: Array<[Atom[], Partial<DayState>, boolean]> = [
    [[], {}, true],
    [[['reward', 0]], { rewards: 0 }, false],
    [[['reward', 0]], { rewards: 1 }, true],
    [[['reward', 11]], { rewards: 40 }, true],
    [[['focus']], { focusActive: true }, true],
    [[['allDone']], { allDone: true }, true],
    [[['notAllDone']], { allDone: true }, false],
    [[['nothingPlanned']], { nothingPlanned: true }, true],
    [[['planned']], { nothingPlanned: true }, false],
    [[['overdue', 3]], { overdue: 9 }, true],
    [[['overdue', 2]], { overdue: 1 }, false],
    [[['calm']], { overdue: 0 }, true],
    [[['progress', 0.5]], { progress: 0.5 }, true],
    [[['hour', 20, 6]], { hour: 22 }, true],
    [[['hour', 20, 6]], { hour: 3 }, true],
    [[['hour', 20, 6]], { hour: 12 }, false],
    [[['hour', 11, 15]], { hour: 15 }, false],
    [[['planned'], ['notAllDone']], { allDone: false }, true],
    [[['unlit', 0]], { rewards: 0 }, true],
    [[['unlit', 0]], { rewards: 1 }, false],
    [[['unlit', 5]], { rewards: 3 }, true],
    [[['unlit', 11]], { rewards: 40 }, false],
    [[['idle']], { focusActive: false }, true],
    [[['idle']], { focusActive: true }, false],
  ]
  it.each(cases)('%j with %j is %s', (when, state, want) => {
    expect(evaluate(when, day(state))).toBe(want)
  })
})

describe('sanitizeDrawing', () => {
  it('accepts what the server sends', () => {
    const d = sanitizeDrawing(fixture)
    expect(d, 'the fixture is a real payload from smylted.drawing').not.toBeNull()
    expect(d!.marks.length).toBeGreaterThan(20)
  })

  const broken = (patch: (p: Record<string, unknown>) => void) => {
    const p = JSON.parse(JSON.stringify(fixture))
    patch(p)
    return sanitizeDrawing(p)
  }

  it('refuses path data outside the server\'s alphabet', () => {
    expect(broken((p) => { (p.marks as { frames: string[] }[])[0].frames[0] = 'M0 0 L1 1"/><script>' })).toBeNull()
    expect(broken((p) => { (p.marks as { frames: string[] }[])[0].frames[0] = 'M0 0 A 1 1 0 0 0 2 2' })).toBeNull()
  })

  it('refuses an unknown role, atom, id or reward', () => {
    expect(broken((p) => { (p.marks as { role: string }[])[0].role = 'image' })).toBeNull()
    expect(broken((p) => { (p.marks as { when: unknown[] }[])[0].when = [['script']] })).toBeNull()
    expect(broken((p) => { (p.marks as { id: string }[])[0].id = 'x"y' })).toBeNull()
    expect(broken((p) => { (p.marks as { reward: number }[])[0].reward = 12 })).toBeNull()
  })

  it('takes a glow, and an origin on a reward inside the picture', () => {
    const d = broken((p) => {
      const marks = p.marks as { role: string; reward: number | null; origin?: unknown }[]
      marks.find((m) => m.role === 'wash')!.role = 'glow'
      marks.find((m) => m.reward !== null)!.origin = [80, 40]
    })
    expect(d).not.toBeNull()
    expect(d!.marks.some((m) => m.role === 'glow')).toBe(true)
    expect(d!.marks.find((m) => m.reward !== null)!.origin).toEqual([80, 40])
  })

  it('refuses an origin off the picture, on a mark that is not a reward, or not two numbers', () => {
    const reward = (fixture.marks as { reward: number | null }[]).findIndex((m) => m.reward !== null)
    const still = (fixture.marks as { reward: number | null }[]).findIndex((m) => m.reward === null)
    const withOrigin = (i: number, o: unknown) => broken((p) => { (p.marks as { origin?: unknown }[])[i].origin = o })
    expect(withOrigin(reward, [500, 40])).toBeNull()
    expect(withOrigin(reward, [80])).toBeNull()
    expect(withOrigin(reward, ['80', 40])).toBeNull()
    expect(withOrigin(still, [80, 40])).toBeNull()
  })

  it('takes a line in three boil frames or one still frame, and refuses two', () => {
    const marks = fixture.marks as { role: string; frames: string[] }[]
    const boiling = marks.findIndex((m) => m.role === 'line' && m.frames.length === 3)
    const still = marks.findIndex((m) => m.role === 'line' && m.frames.length === 1)
    expect(boiling, 'the fixture has a boiling line').toBeGreaterThanOrEqual(0)
    expect(still, 'the fixture has a still line (a reward outline)').toBeGreaterThanOrEqual(0)
    expect(broken((p) => { (p.marks as { frames: string[] }[])[boiling].frames.pop() })).toBeNull()
    expect(broken((p) => { (p.marks as { frames: string[] }[])[still].frames.push('M 0 0') })).toBeNull()
  })
})

describe('<DayDrawing>', () => {
  const drawing = sanitizeDrawing(fixture)!
  const rewards = drawing.marks.filter((m) => m.reward !== null)

  it('is hidden from assistive technology: the text beside it says it all', () => {
    const { container } = render(<DayDrawing drawing={drawing} state={day({})} />)
    expect(container.querySelector('svg')!.getAttribute('aria-hidden')).toBe('true')
  })

  it('draws every reward slot, and marks as many on as there are rewards', () => {
    const { container, rerender } = render(<DayDrawing drawing={drawing} state={day({ rewards: 0 })} />)
    const slots = () => container.querySelectorAll('.dm-reward')
    expect(slots().length).toBe(rewards.length)
    expect(container.querySelectorAll('.dm-reward.on').length).toBe(0)
    rerender(<DayDrawing drawing={drawing} state={day({ rewards: 2 })} />)
    const on = new Set(rewards.filter((m) => m.reward! < 2).map((m) => m.id))
    expect(container.querySelectorAll('.dm-reward.on').length).toBe(on.size)
    // An untick takes it back: the same slots, off again.
    rerender(<DayDrawing drawing={drawing} state={day({ rewards: 1 })} />)
    expect(container.querySelectorAll('.dm-reward.on').length)
      .toBe(rewards.filter((m) => m.reward! < 1).length)
    expect(slots().length).toBe(rewards.length)
  })

  it('draws a line as three boil frames, and a still line as one path', () => {
    const { container } = render(<DayDrawing drawing={drawing} state={day({})} />)
    const line = container.querySelector('g.dm-line')!
    expect([...line.querySelectorAll('path')].map((p) => p.getAttribute('class')))
      .toEqual(['boil f1', 'boil f2', 'boil f3'])
    const still = container.querySelector('path.dm-line.dm-reward')!
    expect(still, 'a reward outline holds still').not.toBeNull()
    expect(still.querySelector('path')).toBeNull()
  })

  it('gives a glow a soft edge of its own, and draws no gradient when there is no glow', () => {
    const { container } = render(<DayDrawing drawing={drawing} state={day({})} />)
    expect(container.querySelector('radialGradient')).toBeNull()
    const glowing = { ...drawing, marks: drawing.marks.map((m, i) => (i === 0 && m.role === 'wash' ? { ...m, role: 'glow' as const } : m)) }
    expect(glowing.marks[0].role, 'the fixture opens with a wash').toBe('glow')
    const { container: c2 } = render(<DayDrawing drawing={glowing} state={day({})} />)
    const grad = c2.querySelector('radialGradient')!
    expect(grad).not.toBeNull()
    const svg = c2.querySelector('svg')!
    expect(svg.style.getPropertyValue('--dm-glow')).toBe(`url(#${grad.id})`)
    expect(c2.querySelector('.dm-glow')).not.toBeNull()
  })

  it('grows a reward from its origin', () => {
    const first = rewards[0]
    const anchored = { ...drawing, marks: drawing.marks.map((m) => (m.reward === first.reward ? { ...m, origin: [70, 30] as [number, number] } : m)) }
    const { container } = render(<DayDrawing drawing={anchored} state={day({})} />)
    const el = container.querySelector<SVGElement>(`.dm-reward[data-c]`)!
    const styled = [...container.querySelectorAll<SVGElement>('.dm-reward')].filter((e) => e.style.transformOrigin)
    expect(el).not.toBeNull()
    expect(styled.length).toBe(anchored.marks.filter((m) => m.origin).length)
    expect(styled[0].style.transformOrigin).toBe('70px 30px')
    expect(styled[0].style.transformBox).toBe('view-box')
  })

  it('runs its focus loop only while a session runs', () => {
    const { container, rerender } = render(<DayDrawing drawing={drawing} state={day({})} />)
    expect(container.querySelector('.dm-ambient')!.classList.contains('on')).toBe(false)
    rerender(<DayDrawing drawing={drawing} state={day({ focusActive: true })} />)
    expect(container.querySelector('.dm-ambient')!.classList.contains('on')).toBe(true)
    expect(container.querySelectorAll('.dm-ambient .amb').length).toBe(6)
  })
})

describe("the month's drawing", () => {
  const month = (day: string) => ({ ...fixture, view: 'month', day })
  afterEach(() => {
    setCacheUser('')
    localStorage.clear()
  })

  it("is accepted when named by its month's first day", () => {
    expect(sanitizeDrawing(month('2026-11-01'))).not.toBeNull()
    expect(sanitizeDrawing(month('2026-11-16'))).toBeNull()
    expect(sanitizeDrawing({ ...month('2026-11-01'), day: null })).toBeNull()
  })

  it('is mirrored once per month of the year', () => {
    setCacheUser('u')
    const theme = fixture.theme as 'light'
    cacheDrawing(sanitizeDrawing(month('2026-11-01'))!)
    cacheDrawing(sanitizeDrawing(month('2026-12-01'))!)
    expect(readCachedDrawing('month', '2026-11-01', theme)?.day).toBe('2026-11-01')
    expect(readCachedDrawing('month', '2026-12-01', theme)?.day).toBe('2026-12-01')
    expect(readCachedDrawing('month', '2027-11-01', theme)).toBeNull()
    const keys = Object.keys(localStorage).filter((k) => k.startsWith('smylte-cache:drawing:')).sort()
    expect(keys).toEqual([`smylte-cache:drawing:u:month-11:${theme}`, `smylte-cache:drawing:u:month-12:${theme}`])
  })
})
