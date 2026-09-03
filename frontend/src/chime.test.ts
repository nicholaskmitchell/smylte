import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { _resetChime, chimeReady, playChime, unlockChime } from './chime'

// A fake AudioContext: enough of the Web Audio surface to see what the chime
// asks of it, and a `state` that starts suspended the way a real one does
// before any gesture.
class FakeCtx {
  state = 'suspended'
  currentTime = 10
  destination = {}
  oscillators: Array<{ hz: number; started: number; stopped: number }> = []
  resume = vi.fn(async () => { this.state = 'running' })
  createGain() {
    return { gain: { setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn() }, connect: vi.fn() }
  }
  createOscillator() {
    const osc = {
      type: '', frequency: { value: 0 }, connect: vi.fn(),
      start: (t: number) => { this.oscillators.push({ hz: osc.frequency.value, started: t, stopped: -1 }) },
      stop: (t: number) => { this.oscillators[this.oscillators.length - 1].stopped = t },
    }
    return osc
  }
}

let made: FakeCtx[] = []

beforeEach(() => {
  _resetChime()
  made = []
  vi.stubGlobal('AudioContext', class { constructor() { const c = new FakeCtx(); made.push(c); return c } })
})
afterEach(() => { vi.unstubAllGlobals(); _resetChime() })

describe('the chime', () => {
  it('is silent until a gesture unlocks it, then plays two notes', () => {
    playChime('focus')
    expect(made).toHaveLength(1)
    expect(made[0].oscillators).toEqual([])       // suspended: nothing scheduled
    expect(chimeReady()).toBe(false)
    unlockChime()
    expect(made[0].resume).toHaveBeenCalled()
    expect(chimeReady()).toBe(true)
    playChime('focus')
    expect(made[0].oscillators.map((o) => o.hz)).toEqual([660, 880])
    // Sequenced, short, and one context for the life of the page.
    const [a, b] = made[0].oscillators
    expect(b.started).toBeGreaterThan(a.started)
    expect(a.stopped - a.started).toBeCloseTo(0.3)
    unlockChime()
    expect(made).toHaveLength(1)
  })

  it('falls the other way when a break ends', () => {
    unlockChime()
    playChime('break')
    expect(made[0].oscillators.map((o) => o.hz)).toEqual([880, 660])
  })

  it('costs nothing where there is no audio at all', () => {
    vi.stubGlobal('AudioContext', undefined)
    _resetChime()
    expect(() => { unlockChime(); playChime('focus') }).not.toThrow()
    expect(chimeReady()).toBe(false)
  })
})
