import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// The module keeps its state at module level, so each test gets a fresh one.
let a: typeof import('./android')

beforeEach(async () => {
  vi.resetModules()
  a = await import('./android')
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const fire = (detail: unknown) =>
  window.dispatchEvent(new CustomEvent(a.ANDROID_EVENT, { detail }))
const bridge = (o: Record<string, unknown>) => vi.stubGlobal('SmylteAndroid', o)

describe('android: outside the Android client', () => {
  it('does nothing and says so', async () => {
    const add = vi.spyOn(window, 'addEventListener')
    expect(a.isAndroidHost()).toBe(false)
    expect(a.canSaveFiles()).toBe(false)
    expect(a.hostEnv()).toBeNull()
    expect(() => a.startAndroidHost()).not.toThrow()
    expect(add).not.toHaveBeenCalledWith('smylte-android', expect.anything())
    expect(await a.saveTextFile('a', 'application/json', '{}')).toBe('unsupported')
  })

  it('is not fooled by a bridge that is not an object', () => {
    vi.stubGlobal('SmylteAndroid', 'x')
    expect(a.isAndroidHost()).toBe(false)
  })
})

describe('android: an older client', () => {
  it('has the colour method only', async () => {
    bridge({ themeColour: vi.fn() })
    expect(a.isAndroidHost()).toBe(true)
    expect(a.canSaveFiles()).toBe(false)
    expect(await a.saveTextFile('a', 'application/json', '{}')).toBe('unsupported')
    expect(() => a.startAndroidHost()).not.toThrow()
    expect(a.hostEnv()).toBeNull()
  })
})

describe('android: starting', () => {
  it('does not ask the host anything on import', async () => {
    // The bridge is in place BEFORE a fresh import, so a module-scope call to
    // the host would show up here; installed after, it would pass vacuously.
    const hello = vi.fn(() => '{"v":1}')
    vi.resetModules()
    bridge({ hello })
    a = await import('./android')
    expect(hello).not.toHaveBeenCalled()
    a.startAndroidHost()
    a.startAndroidHost()
    expect(hello).toHaveBeenCalledTimes(1)
    expect(hello).toHaveBeenCalledWith('save')
  })

  it.each([
    ['{"v":1,"clock24":true}', { clock24: true }],
    ['{"v":1,"clock24":"yes"}', {}],
    ['{"v":1,"clock24":false,"accent":["#fff"],"future":1}', { clock24: false }],
    ['{"v":2,"clock24":true}', null],
    ['{"clock24":true}', null],
    ['not json', null],
    ['[]', null],
    ['null', null],
  ])('reads %s field by field', (raw, expected) => {
    bridge({ hello: () => raw })
    a.startAndroidHost()
    expect(a.hostEnv()).toEqual(expected)
  })

  it('survives a host that throws', () => {
    bridge({ hello: () => { throw new Error('boom') } })
    expect(() => a.startAndroidHost()).not.toThrow()
    expect(a.hostEnv()).toBeNull()
  })
})

describe('android: env events', () => {
  beforeEach(() => bridge({ hello: () => '{"v":1,"clock24":false}' }))

  it('updates the env and tells the subscribers', () => {
    a.startAndroidHost()
    const fn = vi.fn()
    a.onHostEnv(fn)
    fire({ type: 'env', env: { v: 1, clock24: true } })
    expect(a.hostEnv()).toEqual({ clock24: true })
    expect(fn).toHaveBeenCalledWith({ clock24: true })
  })

  it('ignores an env it cannot read and keeps the last one', () => {
    a.startAndroidHost()
    const fn = vi.fn()
    a.onHostEnv(fn)
    fire({ type: 'env', env: { v: 2, clock24: true } })
    expect(a.hostEnv()).toEqual({ clock24: false })
    expect(fn).not.toHaveBeenCalled()
  })

  it('stops telling a subscriber that unsubscribed', () => {
    a.startAndroidHost()
    const fn = vi.fn()
    const off = a.onHostEnv(fn)
    off()
    fire({ type: 'env', env: { v: 1, clock24: true } })
    expect(fn).not.toHaveBeenCalled()
  })

  it('goes on to the next subscriber when one throws', () => {
    a.startAndroidHost()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const next = vi.fn()
    a.onHostEnv(() => { throw new Error('boom') })
    a.onHostEnv(next)
    fire({ type: 'env', env: { v: 1, clock24: true } })
    expect(next).toHaveBeenCalled()
  })

  it('ignores what it does not know', () => {
    a.startAndroidHost()
    const fn = vi.fn()
    a.onHostEnv(fn)
    expect(() => {
      fire({ type: 'from-the-future' })
      fire('x')
      fire(null)
      fire({ type: 'saved', outcome: 'saved' })   // nothing is waiting
    }).not.toThrow()
    expect(fn).not.toHaveBeenCalled()
    expect(a.hostEnv()).toEqual({ clock24: false })
  })
})

describe('android: the phone\'s clock', () => {
  it('is null outside the client and in a client without hello', () => {
    expect(a.hostClock()).toBeNull()
    bridge({ themeColour: vi.fn() })
    a.startAndroidHost()
    expect(a.hostClock()).toBeNull()
  })

  it.each([
    ['{"v":1,"clock24":true}', '24h'],
    ['{"v":1,"clock24":false}', '12h'],
    ['{"v":1}', null],
    ['{"v":1,"clock24":"yes"}', null],
    ['{"v":2,"clock24":true}', null],
  ])('reads %s as %s', (raw, expected) => {
    bridge({ hello: () => raw })
    a.startAndroidHost()
    expect(a.hostClock()).toBe(expected)
  })

  it('follows an env event', () => {
    bridge({ hello: () => '{"v":1,"clock24":false}' })
    a.startAndroidHost()
    expect(a.hostClock()).toBe('12h')
    fire({ type: 'env', env: { v: 1, clock24: true } })
    expect(a.hostClock()).toBe('24h')
  })
})

describe('android: saving a file', () => {
  const save = (saveFile: unknown) => bridge({ saveFile })

  it.each(['saved', 'cancelled'] as const)('resolves %s from the host\'s event', async (outcome) => {
    save(vi.fn(() => true))
    const p = a.saveTextFile('a.json', 'application/json', '{}')
    fire({ type: 'saved', outcome })
    expect(await p).toBe(outcome)
  })

  it.each(['exploded', 'unsupported'])('counts the outcome %s as failed', async (outcome) => {
    save(vi.fn(() => true))
    const p = a.saveTextFile('a.json', 'application/json', '{}')
    fire({ type: 'saved', outcome })
    expect(await p).toBe('failed')
  })

  it('passes the arguments through', () => {
    const saveFile = vi.fn(() => true)
    save(saveFile)
    void a.saveTextFile('a.json', 'application/json', '{"x":1}')
    expect(saveFile).toHaveBeenCalledWith('a.json', 'application/json', '{"x":1}')
  })

  it('fails when the host refuses, answers loosely, or throws', async () => {
    save(vi.fn(() => false))
    expect(await a.saveTextFile('a', 'application/json', '{}')).toBe('failed')
    save(vi.fn(() => 'true'))
    expect(await a.saveTextFile('a', 'application/json', '{}')).toBe('failed')
    save(vi.fn(() => { throw new Error('boom') }))
    expect(await a.saveTextFile('a', 'application/json', '{}')).toBe('failed')
  })

  it('says busy to a second call, and takes a new one once the first is answered', async () => {
    const saveFile = vi.fn(() => true)
    save(saveFile)
    const first = a.saveTextFile('a', 'application/json', '{}')
    expect(await a.saveTextFile('a', 'application/json', '{}')).toBe('busy')
    expect(saveFile).toHaveBeenCalledTimes(1)
    fire({ type: 'saved', outcome: 'saved' })
    expect(await first).toBe('saved')
    void a.saveTextFile('a', 'application/json', '{}')
    expect(saveFile).toHaveBeenCalledTimes(2)
  })

  it('listens without startAndroidHost having run', async () => {
    save(vi.fn(() => true))
    const p = a.saveTextFile('a', 'application/json', '{}')
    fire({ type: 'saved', outcome: 'saved' })
    expect(await p).toBe('saved')
  })
})

describe('android: main.tsx', () => {
  it('starts the bridge before anything renders', () => {
    const src = readFileSync(resolve(process.cwd(), 'src/main.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1')
    const start = src.indexOf('startAndroidHost()')
    expect(start).toBeGreaterThan(-1)
    expect(start).toBeLessThan(src.indexOf('createRoot('))
  })
})
