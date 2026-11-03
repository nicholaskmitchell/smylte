import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { RAMP, RAMP2 } from './test/accent'

// The module keeps its state at module level, so each test gets a fresh one.
let a: typeof import('./android')

// A module that listened for the host's events keeps listening after its test,
// and would answer the next test's events with a bridge that is not its own.
// So the listeners added for the host are remembered and removed after each test.
const heard: EventListenerOrEventListenerObject[] = []
const addListener = window.addEventListener.bind(window)
window.addEventListener = ((type: string, fn: EventListenerOrEventListenerObject, opts?: unknown) => {
  if (type === 'smylte-android') heard.push(fn)
  addListener(type, fn, opts as AddEventListenerOptions)
}) as typeof window.addEventListener

// The same for the click listener the host installs on the document.
const clicked: EventListenerOrEventListenerObject[] = []
const addDocListener = document.addEventListener.bind(document)
document.addEventListener = ((type: string, fn: EventListenerOrEventListenerObject, opts?: unknown) => {
  if (type === 'click') clicked.push(fn)
  addDocListener(type, fn, opts as AddEventListenerOptions)
}) as typeof document.addEventListener

beforeEach(async () => {
  vi.resetModules()
  a = await import('./android')
})
afterEach(() => {
  for (const fn of heard.splice(0)) window.removeEventListener('smylte-android', fn)
  for (const fn of clicked.splice(0)) document.removeEventListener('click', fn, true)
  document.body.innerHTML = ''
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
    expect(() => a.markReady()).not.toThrow()
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
    expect(() => a.markReady()).not.toThrow()
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
    expect(hello).toHaveBeenCalledWith('back,haptics,ready,save')
  })

  it.each([
    ['{"v":1,"clock24":true}', { clock24: true }],
    ['{"v":1,"clock24":"yes"}', {}],
    ['{"v":1,"clock24":false,"accent":["#fff"],"future":1}', { clock24: false }],
    [JSON.stringify({ v: 1, clock24: false, accent: RAMP }), { clock24: false, accent: RAMP }],
    [JSON.stringify({ v: 1, clock24: true, accent: RAMP.slice(0, 12) }), { clock24: true }],
    [JSON.stringify({ v: 1, clock24: true, accent: [...RAMP, '#000000'] }), { clock24: true }],
    [JSON.stringify({ v: 1, clock24: true, accent: RAMP.map((c, i) => (i === 0 ? '#FFFFFF' : c)) }), { clock24: true }],
    [JSON.stringify({ v: 1, clock24: true, accent: RAMP.map((c, i) => (i === 0 ? 7 : c)) }), { clock24: true }],
    ['{"v":1,"clock24":true,"accent":"#ffffff"}', { clock24: true }],
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

describe('android: the wallpaper palette', () => {
  it('is null outside the client, in a client without hello, and on a phone without one', async () => {
    expect(a.hostAccent()).toBeNull()
    bridge({ themeColour: vi.fn() })
    a.startAndroidHost()
    expect(a.hostAccent()).toBeNull()
    // The module is fresh again, so this start reads a hello with no palette.
    vi.resetModules()
    a = await import('./android')
    bridge({ hello: () => '{"v":1,"clock24":false}' })
    a.startAndroidHost()
    expect(a.hostAccent()).toBeNull()
  })

  it('follows an env event, and an env without one drops it', () => {
    bridge({ hello: () => JSON.stringify({ v: 1, clock24: false, accent: RAMP }) })
    a.startAndroidHost()
    expect(a.hostAccent()).toEqual(RAMP)
    fire({ type: 'env', env: { v: 1, clock24: false, accent: RAMP2 } })
    expect(a.hostAccent()).toEqual(RAMP2)
    fire({ type: 'env', env: { v: 1, clock24: false } })
    expect(a.hostAccent()).toBeNull()
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

describe('android: back', () => {
  // The real layer stack has its own suite (layers.test.tsx); here it is a
  // fake, so this file sees exactly what android.ts asks of it.
  let depth = 0
  let listeners: Set<(n: number) => void>
  let backTopLayer: ReturnType<typeof vi.fn<() => boolean>>

  beforeEach(async () => {
    depth = 0
    listeners = new Set()
    backTopLayer = vi.fn(() => depth > 0)
    vi.resetModules()
    vi.doMock('./layers', () => ({
      layerDepth: () => depth,
      onLayerDepth: (fn: (n: number) => void) => {
        listeners.add(fn)
        return () => { listeners.delete(fn) }
      },
      backTopLayer: () => backTopLayer(),
    }))
    a = await import('./android')
  })
  afterEach(() => {
    vi.doUnmock('./layers')
  })

  const set = (n: number) => {
    depth = n
    for (const fn of [...listeners]) fn(n)
  }
  const tick = () => Promise.resolve()

  it('reports depth only to a host that has layers()', async () => {
    const layers = vi.fn()
    bridge({ hello: () => '{"v":1}', layers })
    a.startAndroidHost()
    set(1)
    await tick()
    expect(layers).toHaveBeenCalledTimes(1)
    expect(layers).toHaveBeenCalledWith(1)
  })

  it('subscribes to nothing in a client without layers()', () => {
    bridge({ hello: () => '{"v":1}' })
    a.startAndroidHost()
    expect(listeners.size).toBe(0)
  })

  it('nothing listens outside the client', () => {
    a.startAndroidHost()
    expect(listeners.size).toBe(0)
    fire({ type: 'back' })
    expect(backTopLayer).not.toHaveBeenCalled()
  })

  it('coalesces a burst and skips an unchanged depth', async () => {
    const layers = vi.fn()
    bridge({ layers })
    a.startAndroidHost()
    set(1); set(0); set(1)
    await tick()
    expect(layers.mock.calls).toEqual([[1]])
    set(2); set(1)
    await tick()
    expect(layers).toHaveBeenCalledTimes(1)
  })

  it('closes the top layer on a back event', async () => {
    const layers = vi.fn()
    bridge({ layers })
    a.startAndroidHost()
    set(1)
    await tick()
    fire({ type: 'back' })
    expect(backTopLayer).toHaveBeenCalledTimes(1)
    expect(layers.mock.calls).toEqual([[1]])
  })

  it('tells the host nothing is open when Back finds no layer', () => {
    const layers = vi.fn()
    bridge({ layers })
    a.startAndroidHost()
    // 0 is what the host was last told, and it is sent again: the host's count
    // is the one that is wrong.
    fire({ type: 'back' })
    expect(layers.mock.calls).toEqual([[0]])
  })

  it('survives a host whose layers() throws, and retries on the next change', async () => {
    const layers = vi.fn(() => { throw new Error('boom') })
    bridge({ layers })
    a.startAndroidHost()
    expect(() => set(1)).not.toThrow()
    await tick()
    set(0)
    await tick()
    set(1)
    await tick()
    expect(layers.mock.calls).toEqual([[1], [1]])
    expect(() => fire({ type: 'back' })).not.toThrow()
  })

  it('logs a layer handler that throws instead of reporting 0', () => {
    const layers = vi.fn()
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    bridge({ layers })
    a.startAndroidHost()
    backTopLayer.mockImplementation(() => { throw new Error('boom') })
    fire({ type: 'back' })
    expect(error).toHaveBeenCalled()
    expect(layers).not.toHaveBeenCalled()
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

describe('android: haptics', () => {
  const hello = () => '{"v":1}'
  const html = (markup: string) => {
    document.body.innerHTML = markup
    return document.body.firstElementChild as HTMLElement
  }

  it('plays nothing outside the client', () => {
    const add = vi.spyOn(document, 'addEventListener')
    expect(() => a.haptic('confirm')).not.toThrow()
    a.startAndroidHost()
    expect(add).not.toHaveBeenCalledWith('click', expect.anything(), expect.anything())
  })

  it('installs nothing in a client without haptic()', () => {
    bridge({ hello, layers: vi.fn() })
    const add = vi.spyOn(document, 'addEventListener')
    a.startAndroidHost()
    expect(add).not.toHaveBeenCalledWith('click', expect.anything(), expect.anything())
  })

  it('passes the kind through, and survives a host that throws', () => {
    const haptic = vi.fn()
    bridge({ haptic })
    a.haptic('toggleOn')
    expect(haptic).toHaveBeenCalledWith('toggleOn')
    bridge({ haptic: () => { throw new Error('host failed') } })
    expect(() => a.haptic('reject')).not.toThrow()
  })

  it.each<[string, string | null, string?]>([
    ['<button class="check" aria-pressed="false"></button>', 'confirm'],
    ['<button class="check" aria-pressed="true"></button>', 'toggleOff'],
    ['<button aria-pressed="false">Busy</button>', 'toggleOn'],
    ['<button aria-pressed="true">Busy</button>', 'toggleOff'],
    ['<div role="checkbox" aria-checked="false"></div>', 'toggleOn'],
    ['<div role="checkbox" aria-checked="true"></div>', 'toggleOff'],
    // The role decides which attribute is the state.
    ['<button role="switch" aria-checked="true" aria-pressed="false"></button>', 'toggleOff'],
    ['<button>Save</button>', null],
    ['<div role="button">Open</div>', null],
    ['<button class="check" aria-pressed="false" disabled></button>', null],
    ['<button aria-pressed="false" aria-disabled="true"></button>', null],
    ['<button data-haptic="confirm">Done</button>', 'confirm'],
    ['<button data-haptic="buzz" aria-pressed="false"></button>', 'toggleOn'],
    ['<button aria-pressed="false"><span>Busy</span></button>', 'toggleOn', 'span'],
    ['<div role="checkbox" aria-checked="false"><button>Edit</button></div>', null, 'button'],
  ])('reads %s as %s', (markup, expected, inner) => {
    const root = html(markup)
    const el = inner ? root.querySelector(inner) : root
    expect(a.hapticFor(el)).toBe(expected)
  })

  it('reads nothing from no target or the document', () => {
    expect(a.hapticFor(null)).toBeNull()
    expect(a.hapticFor(document)).toBeNull()
  })

  it('a checkbox plays the state it goes to', () => {
    const haptic = vi.fn()
    bridge({ haptic })
    a.startAndroidHost()
    const input = html('<input type="checkbox">') as HTMLInputElement
    input.click()
    input.click()
    expect(haptic.mock.calls).toEqual([['toggleOn'], ['toggleOff']])
  })

  it('a label plays once', () => {
    const haptic = vi.fn()
    bridge({ haptic })
    a.startAndroidHost()
    html('<label><input type="checkbox"><span>Busy</span></label>')
    document.querySelector<HTMLElement>('span')!.click()
    expect(haptic.mock.calls).toEqual([['toggleOn']])
  })

  it('reads the state before the app\'s handler changes it', () => {
    const haptic = vi.fn()
    bridge({ haptic })
    a.startAndroidHost()
    for (const [cls, expected] of [['', 'toggleOn'], ['check', 'confirm']]) {
      haptic.mockClear()
      const button = html(`<button class="${cls}" aria-pressed="false"></button>`)
      button.addEventListener('click', () => button.setAttribute('aria-pressed', 'true'))
      button.click()
      expect(haptic.mock.calls).toEqual([[expected]])
    }
  })

  it('delegates once however often it starts', () => {
    const haptic = vi.fn()
    bridge({ haptic })
    a.startAndroidHost()
    a.startAndroidHost()
    html('<button aria-pressed="false"></button>').click()
    expect(haptic).toHaveBeenCalledTimes(1)
  })
})

describe('android: ready', () => {
  it('does nothing in a client without ready()', () => {
    const hello = vi.fn(() => '{"v":1}')
    const themeColour = vi.fn()
    bridge({ hello, themeColour })
    expect(() => a.markReady()).not.toThrow()
    expect(hello).not.toHaveBeenCalled()
    expect(themeColour).not.toHaveBeenCalled()
  })

  it('tells the host, and nothing more', () => {
    const ready = vi.fn()
    bridge({ ready })
    a.markReady()
    expect(ready.mock.calls).toEqual([[]])
  })

  it('calls it on the bridge, not detached', () => {
    const host = { ready: vi.fn() }
    bridge(host)
    a.markReady()
    expect(host.ready.mock.contexts[0]).toBe(host)
  })

  it('survives a host that throws', () => {
    bridge({ ready: () => { throw new Error('host failed') } })
    expect(() => a.markReady()).not.toThrow()
  })

  it('does not wait for a frame', () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame')
    const ready = vi.fn()
    bridge({ ready })
    a.markReady()
    expect(ready).toHaveBeenCalledTimes(1)
    expect(raf).not.toHaveBeenCalled()
  })
})
