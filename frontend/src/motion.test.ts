import { afterEach, describe, expect, it } from 'vitest'
import { parseTime, tickExit } from './motion'

describe('parseTime', () => {
  it.each([['.5s', 500], ['0.38s', 380], ['60ms', 60], ['0s', 0], ['0ms', 0], [' .45s ', 450]])(
    '%s is %d ms', (v, ms) => expect(parseTime(v)).toBe(ms))
  it.each(['', 'auto', '5', '1x'])('"%s" is unreadable', (v) => expect(parseTime(v)).toBeNaN())
})

describe('tickExit', () => {
  const root = document.documentElement
  const set = (o: Record<string, string>) => { for (const [k, v] of Object.entries(o)) root.style.setProperty(k, v) }
  afterEach(() => { for (const k of ['--stagger', '--dur-stroke', '--dur', '--dur-slow']) root.style.removeProperty(k) })

  it('holds for the strike to draw and a beat, then leaves over --dur-slow', () => {
    // The shipped values (ds/app-motion.css), as the built CSS serialises them.
    set({ '--stagger': '60ms', '--dur-stroke': '.5s', '--dur': '.24s', '--dur-slow': '.45s' })
    expect(tickExit()).toEqual({ ink: 980, leave: 450 })
  })
  it('is null under reduced motion, where every token is zero', () => {
    set({ '--stagger': '0ms', '--dur-stroke': '0s', '--dur': '0s', '--dur-slow': '0s' })
    expect(tickExit()).toBeNull()
  })
  it('is null under a preset, which has no ink tokens', () => {
    // tokens.css gives every preset --dur and --dur-slow, and nothing else.
    set({ '--dur': '.2s', '--dur-slow': '.32s' })
    expect(tickExit()).toBeNull()
  })
})
