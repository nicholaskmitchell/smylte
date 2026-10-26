import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, AuthError, HttpError } from './api'

const TOKEN = 'aB3_-'.repeat(8) + 'abc'      // 43 characters of the token alphabet

function stubFetch(status: number, body?: unknown, headers: Record<string, string> = {}) {
  const res = {
    status,
    ok: status >= 200 && status < 300,
    statusText: 'status text',
    headers: new Headers(headers),
    json: () => (body === undefined
      ? Promise.reject(new SyntaxError('no body'))
      : Promise.resolve(body)),
  }
  const fn = vi.fn().mockResolvedValue(res)
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('publicShareView', () => {
  it('sends the conditional GET with nothing about the visitor', async () => {
    const fetchMock = stubFetch(200, { v: 1 }, { ETag: '"abc"' })
    await api.publicShareView(TOKEN, '"prev"')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/public/share/${TOKEN}`)
    expect(init.method).toBe('GET')
    expect(init.headers).toEqual({ 'If-None-Match': '"prev"' })
    expect(init.credentials).toBe('omit')
    expect(init.cache).toBe('no-store')
    expect(init.referrerPolicy).toBe('no-referrer')
    expect(init.body).toBeUndefined()
  })

  it('sends no If-None-Match before it has an etag', async () => {
    const fetchMock = stubFetch(200, { v: 1 })
    await api.publicShareView(TOKEN, null)
    expect(fetchMock.mock.calls[0][1].headers).toBeUndefined()
  })

  it('passes the abort signal through', async () => {
    const fetchMock = stubFetch(200, { v: 1 })
    const ctl = new AbortController()
    await api.publicShareView(TOKEN, null, ctl.signal)
    expect(fetchMock.mock.calls[0][1].signal).toBe(ctl.signal)
  })

  it('escapes the token in the path', async () => {
    const fetchMock = stubFetch(200, { v: 1 })
    await api.publicShareView('a/b?c', null)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/public/share/a%2Fb%3Fc')
  })

  it('returns the body and the etag on a 200', async () => {
    stubFetch(200, { v: 1, day: '2026-10-26' }, { ETag: '"abc"' })
    expect(await api.publicShareView(TOKEN, null))
      .toEqual({ status: 'fresh', body: { v: 1, day: '2026-10-26' }, etag: '"abc"' })
  })

  it('has a null etag when the response carries none', async () => {
    stubFetch(200, { v: 1 })
    expect(await api.publicShareView(TOKEN, null))
      .toEqual({ status: 'fresh', body: { v: 1 }, etag: null })
  })

  it('maps a 304 to unchanged, without reading a body', async () => {
    stubFetch(304)
    expect(await api.publicShareView(TOKEN, '"prev"')).toEqual({ status: 'unchanged' })
  })

  it('turns a 401 into AuthError, as a proxy in front would give', async () => {
    stubFetch(401, { detail: 'sign in' })
    await expect(api.publicShareView(TOKEN, null)).rejects.toBeInstanceOf(AuthError)
  })

  it('turns a 404 into HttpError(404) with the server\'s words', async () => {
    stubFetch(404, { detail: 'unknown share' })
    const err = await api.publicShareView(TOKEN, null).catch(e => e)
    expect(err).toBeInstanceOf(HttpError)
    expect(err.status).toBe(404)
    expect(err.message).toBe('unknown share')
  })

  it('keeps the status of a 429 and a 5xx', async () => {
    stubFetch(429, { detail: 'slow down' })
    expect(await api.publicShareView(TOKEN, null).catch(e => e)).toMatchObject({ status: 429 })
    stubFetch(500, { detail: 'share unavailable' })
    expect(await api.publicShareView(TOKEN, null).catch(e => e)).toMatchObject({ status: 500 })
  })
})

describe('the owner\'s share calls', () => {
  it('key every route by id, escaped', async () => {
    const fetchMock = stubFetch(200, {})
    await api.sharePreview('a/b')
    await api.patchShare('a/b', { enabled: false })
    await api.rotateShareToken('a/b')
    await api.deleteShare('a/b')
    const calls = fetchMock.mock.calls.map(([url, init]) => `${init.method} ${url}`)
    expect(calls).toEqual([
      'GET /api/shares/a%2Fb/preview',
      'PATCH /api/shares/a%2Fb',
      'POST /api/shares/a%2Fb/rotate',
      'DELETE /api/shares/a%2Fb',
    ])
  })

  it('send the session, unlike the public view', async () => {
    const fetchMock = stubFetch(200, [])
    await api.shares()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/shares')
    expect(fetchMock.mock.calls[0][1].credentials).toBe('same-origin')
  })

  it('create posts the body given', async () => {
    const fetchMock = stubFetch(200, {})
    await api.createShare({ name: 'Sam' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/shares')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ name: 'Sam' })
  })

  it('patch sends only the fields given', async () => {
    const fetchMock = stubFetch(200, {})
    await api.patchShare('x', { horizon_days: 14 })
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ horizon_days: 14 })
  })
})
