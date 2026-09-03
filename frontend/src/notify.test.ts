import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { notifyPermission, requestNotify, showNotify } from './notify'

let shown: Array<{ title: string; options: Record<string, unknown> }> = []
let permission = 'default'

function install(perm: string, answer = 'granted') {
  permission = perm
  const Fake = class {
    static get permission() { return permission }
    static requestPermission = vi.fn(async () => { permission = answer; return answer })
    constructor(title: string, options: Record<string, unknown>) { shown.push({ title, options }) }
    close() { /* noop */ }
  }
  vi.stubGlobal('Notification', Fake)
  return Fake
}

beforeEach(() => { shown = [] })
afterEach(() => vi.unstubAllGlobals())

describe('the notification', () => {
  it('reports unsupported where the API is absent, and never throws', async () => {
    vi.stubGlobal('Notification', undefined)
    expect(notifyPermission()).toBe('unsupported')
    expect(await requestNotify()).toBe('unsupported')
    expect(showNotify('x', 'y')).toBe(false)
  })

  it('asks only when asked, and shows only once granted', async () => {
    const Fake = install('default')
    expect(showNotify('Interval over', 'Draft the memo')).toBe(false)
    expect(shown).toEqual([])
    expect(await requestNotify()).toBe('granted')
    expect(Fake.requestPermission).toHaveBeenCalledTimes(1)
    expect(showNotify('Interval over', 'Draft the memo')).toBe(true)
    // Tagged so a repeat replaces, and silent: the chime is the sound.
    expect(shown).toEqual([{
      title: 'Interval over',
      options: { body: 'Draft the memo', tag: 'smylte-focus', silent: true },
    }])
  })

  it('takes no for an answer', async () => {
    install('denied', 'denied')
    expect(await requestNotify()).toBe('denied')
    expect(showNotify('x', 'y')).toBe(false)
    expect(shown).toEqual([])
  })
})
