import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, AuthError, clientId } from './api'

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
