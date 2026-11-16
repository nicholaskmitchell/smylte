// The day's drawing on the client: the payload is checked to the letter before
// it reaches the DOM, the conditions agree with the server's, and the renderer
// marks exactly the parts the day's state calls for.
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import fixture from './test/drawing-fixture.json'
import { DayDrawing } from './components/DayDrawing'
import { EMPTY_DAY, evaluate, sanitizeDrawing, type Atom, type DayState } from './drawing'

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

  it('refuses a line without its three boil frames', () => {
    const i = (fixture.marks as { role: string }[]).findIndex((m) => m.role === 'line')
    expect(broken((p) => { (p.marks as { frames: string[] }[])[i].frames.pop() })).toBeNull()
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

  it('draws a line as three boil frames', () => {
    const { container } = render(<DayDrawing drawing={drawing} state={day({})} />)
    const line = container.querySelector('.dm-line')!
    expect([...line.querySelectorAll('path')].map((p) => p.getAttribute('class')))
      .toEqual(['boil f1', 'boil f2', 'boil f3'])
  })

  it('runs its focus loop only while a session runs', () => {
    const { container, rerender } = render(<DayDrawing drawing={drawing} state={day({})} />)
    expect(container.querySelector('.dm-ambient')!.classList.contains('on')).toBe(false)
    rerender(<DayDrawing drawing={drawing} state={day({ focusActive: true })} />)
    expect(container.querySelector('.dm-ambient')!.classList.contains('on')).toBe(true)
    expect(container.querySelectorAll('.dm-ambient .amb').length).toBe(6)
  })
})
