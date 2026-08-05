import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, AuthError, clientId, subscribe } from './api'

function stubFetch(status: number, body?: unknown, statusText = '') {
  const res = {
    status,
    ok: status >= 200 && status < 300,
    statusText,
    json: () => (body === undefined
      ? Promise.reject(new SyntaxError('no body'))
      : Promise.resolve(body)),
  }
  const fn = vi.fn().mockResolvedValue(res)
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('the fetch wrapper', () => {
  it('sends JSON with same-origin credentials', async () => {
    const fetchMock = stubFetch(200, { authenticated: true, user: 'admin' })
    await api.login('admin', 'pw')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/login')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('same-origin')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ username: 'admin', password: 'pw' })
  })

  it('turns a 401 into AuthError so guards can log the user out', async () => {
    stubFetch(401, { detail: 'authentication required' })
    await expect(api.lists()).rejects.toBeInstanceOf(AuthError)
  })

  it('surfaces the server detail on other errors', async () => {
    stubFetch(409, { detail: 'edit conflict, retry' })
    await expect(api.lists()).rejects.toThrow('edit conflict, retry')
  })

  it('falls back to statusText when the error body is not JSON', async () => {
    stubFetch(502, undefined, 'Bad Gateway')
    await expect(api.lists()).rejects.toThrow('Bad Gateway')
  })

  it('returns null for 204 (deletes)', async () => {
    stubFetch(204)
    await expect(api.deleteTask('l1', 'u1')).resolves.toBeNull()
  })

  it('URL-encodes path segments so a hostile uid cannot break out of the path', async () => {
    const fetchMock = stubFetch(200, {})
    await api.patchTask('inbox', '../../../etc/passwd?x=1', { summary: 'x' })
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/lists/inbox/tasks/..%2F..%2F..%2Fetc%2Fpasswd%3Fx%3D1')
  })
})

describe('clientId', () => {
  it('mints URL-safe lowercase hex (it becomes the CalDAV href slug)', () => {
    const a = clientId()
    const b = clientId()
    expect(a).toMatch(/^[0-9a-f]{32}$/)
    expect(a).not.toBe(b)
  })
})

describe('subscribe (SSE)', () => {
  /** Minimal EventSource stand-in: jsdom has none, and we need to drive the
   *  failure modes the real one only reaches over a network. */
  class FakeES {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSED = 2
    static instances: FakeES[] = []
    readyState = 0
    closed = false
    onopen: (() => void) | null = null
    onmessage: ((e: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    constructor(public url: string) { FakeES.instances.push(this) }
    close() { this.closed = true; this.readyState = 2 }
    /** Server accepted the stream. */
    accept() { this.readyState = 1; this.onopen?.() }
    /** Non-200 (401 / 502): the spec says fail the connection, never retry. */
    hardFail() { this.readyState = 2; this.onerror?.() }
    emit(payload: unknown) { this.onmessage?.({ data: JSON.stringify(payload) }) }
  }

  const withFakeES = async (fn: (ES: typeof FakeES) => Promise<void> | void) => {
    FakeES.instances = []
    vi.stubGlobal('EventSource', FakeES)
    try { await fn(FakeES) } finally { vi.unstubAllGlobals() }
  }

  it('reconnects after a hard failure instead of going dark forever', async () => {
    vi.useFakeTimers()
    try {
      await withFakeES(async (ES) => {
        const onChange = vi.fn()
        const stop = subscribe(onChange)
        expect(ES.instances).toHaveLength(1)
        ES.instances[0].accept()

        // A backend restart answers 502; EventSource closes for good on its own.
        ES.instances[0].hardFail()
        expect(ES.instances[0].readyState).toBe(ES.CLOSED)

        await vi.advanceTimersByTimeAsync(60_000)
        expect(ES.instances.length).toBeGreaterThan(1)   // we retried; it would not have
        stop()
      })
    } finally { vi.useRealTimers() }
  })

  it('refetches on reconnect, since events published while away are lost', async () => {
    vi.useFakeTimers()
    try {
      await withFakeES(async (ES) => {
        const onChange = vi.fn()
        const stop = subscribe(onChange)
        ES.instances[0].accept()
        expect(onChange).not.toHaveBeenCalled()          // first connect is not a change

        ES.instances[0].hardFail()
        await vi.advanceTimersByTimeAsync(60_000)
        ES.instances[ES.instances.length - 1].accept()
        expect(onChange).toHaveBeenCalledTimes(1)        // the reconnect stands in
        stop()
      })
    } finally { vi.useRealTimers() }
  })

  it('stops retrying once unsubscribed', async () => {
    vi.useFakeTimers()
    try {
      await withFakeES(async (ES) => {
        const stop = subscribe(vi.fn())
        ES.instances[0].accept()
        ES.instances[0].hardFail()
        stop()
        const n = ES.instances.length
        await vi.advanceTimersByTimeAsync(120_000)
        expect(ES.instances).toHaveLength(n)
      })
    } finally { vi.useRealTimers() }
  })

  it('fires on a change frame but not on hello or a keepalive', async () => {
    await withFakeES(async (ES) => {
      const onChange = vi.fn()
      const stop = subscribe(onChange)
      ES.instances[0].accept()
      ES.instances[0].emit({ type: 'hello' })
      ES.instances[0].onmessage?.({ data: ':keepalive' })
      expect(onChange).not.toHaveBeenCalled()
      ES.instances[0].emit({ type: 'task_updated', list: 'l1' })
      expect(onChange).toHaveBeenCalledTimes(1)
      stop()
    })
  })
})
