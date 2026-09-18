import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  deleteNote,
  getBars,
  getEvents,
  getMarket,
  getNotes,
  putNote
} from '@/lib/api'
import {
  AAPL_CIK,
  jsonResponse,
  makeBar,
  makeNote,
  problemResponse
} from '../fixtures'

/** The client's `fetch` wrapper hands openapi-fetch's built `Request`
 * straight to `globalThis.fetch` (see lib/api.ts), so the mock is called
 * with a single `Request`, not a `(url, init)` pair. */
function requestFrom(fetchMock: ReturnType<typeof vi.fn>): Request {
  const [request] = fetchMock.mock.calls[0] as [Request]
  return request
}

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('calls the configured API base URL for GET requests', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        server_time: '2024-06-03T15:00:00.000Z',
        market_clock: null,
        listings: []
      })
    )

    await getMarket()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const request = requestFrom(fetchMock)
    expect(request.url).toBe('http://127.0.0.1:8000/api/v1/market')
    expect(request.method).toBe('GET')
  })

  it('sends a PUT with a JSON content-type for putNote, defaulting cik and end_date', async () => {
    const fetchMock = vi.mocked(fetch)
    const note = makeNote({ cik: null, body: 'hello' })
    fetchMock.mockResolvedValueOnce(jsonResponse(note, { status: 200 }))

    await putNote('note-1', { start_date: '2024-06-03', body: 'hello' })

    const request = requestFrom(fetchMock)
    expect(request.url).toBe('http://127.0.0.1:8000/api/v1/notes/note-1')
    expect(request.method).toBe('PUT')
    expect(request.headers.get('Content-Type')).toBe('application/json')
    // end_date defaults to start_date and cik defaults to null client-side -
    // the generated NotePut type requires both, even though api-read's own
    // docs say a `mode="before"` validator fills end_date in server-side
    // too if it's omitted.
    await expect(request.text()).resolves.toBe(
      JSON.stringify({
        cik: null,
        start_date: '2024-06-03',
        end_date: '2024-06-03',
        body: 'hello'
      })
    )
  })

  it('passes through an explicit end_date instead of defaulting it', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeNote({
          cik: AAPL_CIK,
          start_date: '2024-06-01',
          end_date: '2024-06-10',
          body: 'range note'
        })
      )
    )

    await putNote('note-1', {
      cik: AAPL_CIK,
      start_date: '2024-06-01',
      end_date: '2024-06-10',
      body: 'range note'
    })

    const request = requestFrom(fetchMock)
    await expect(request.text()).resolves.toBe(
      JSON.stringify({
        cik: AAPL_CIK,
        start_date: '2024-06-01',
        end_date: '2024-06-10',
        body: 'range note'
      })
    )
  })

  it('sends no body for DELETE and resolves on 204', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await expect(deleteNote('note-1')).resolves.toBeUndefined()
    const request = requestFrom(fetchMock)
    expect(request.method).toBe('DELETE')
  })

  it('builds query strings from provided params only', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null })
    )

    await getNotes({ cik: AAPL_CIK, limit: 20 })

    const request = requestFrom(fetchMock)
    expect(request.url).toBe(
      'http://127.0.0.1:8000/api/v1/notes?cik=0000320193&limit=20'
    )
  })

  it('sends include_market alongside cik', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null })
    )

    await getNotes({ cik: AAPL_CIK, include_market: true })

    const request = requestFrom(fetchMock)
    expect(request.url).toBe(
      'http://127.0.0.1:8000/api/v1/notes?cik=0000320193&include_market=true'
    )
  })

  it('unwraps BarsResponse to a plain Bar[]', async () => {
    const fetchMock = vi.mocked(fetch)
    const bar = makeBar()
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ symbol: 'AAPL', timeframe: '1d', bars: [bar] })
    )

    const bars = await getBars('AAPL', { from: '2024-01-01' })

    expect(bars).toEqual([bar])
    const request = requestFrom(fetchMock)
    expect(request.url).toBe(
      'http://127.0.0.1:8000/api/v1/listings/AAPL/bars?from=2024-01-01&timeframe=1d'
    )
  })

  it('joins multiple event kinds with a comma', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null })
    )

    await getEvents({ cik: AAPL_CIK, kind: ['split', 'cash_dividend'] })

    const request = requestFrom(fetchMock)
    expect(request.url).toBe(
      'http://127.0.0.1:8000/api/v1/events?cik=0000320193&kind=split%2Ccash_dividend'
    )
  })

  it('throws a typed ApiError parsed from a problem+json body, carrying the full problem', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      problemResponse(422, {
        type: 'https://stockticker.local/problems/unknown-cik',
        title: 'Unknown CIK',
        detail: 'No company with that CIK.',
        errors: [{ loc: ['query', 'cik'], msg: 'unknown', type: 'value_error' }]
      })
    )

    const error = await getMarket().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.slug).toBe('unknown-cik')
    expect(apiError.status).toBe(422)
    expect(apiError.detail).toBe('No company with that CIK.')
    expect(apiError.problem.type).toBe(
      'https://stockticker.local/problems/unknown-cik'
    )
    expect(apiError.problem.errors).toEqual([
      { loc: ['query', 'cik'], msg: 'unknown', type: 'value_error' }
    ])
  })

  it('falls back to about:blank when the error body is not JSON', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      new Response('not json', { status: 500, statusText: 'Server Error' })
    )

    const error = await getMarket().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.slug).toBe('about:blank')
    expect(apiError.status).toBe(500)
  })

  it('does not throw on a 200 response with an empty body', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(new Response('', { status: 200 }))

    // getMarket expects a MarketResponse body; an empty 200 has no data to
    // return, so this surfaces as a well-formed ApiError, not an unhandled
    // JSON-parse exception.
    const error = await getMarket().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
  })

  it('trusts a non-string title/detail/type as little as a missing one', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { type: 404, title: null, status: 404, detail: 12345 },
        { status: 404 }
      )
    )

    const error = await getMarket().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.slug).toBe('about:blank')
    expect(apiError.detail).toBeNull()
  })
})
