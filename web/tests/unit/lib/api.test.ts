import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  deleteNote,
  getEvents,
  getMarket,
  getNotes,
  putNote,
  type Note
} from '@/lib/api'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init
  })
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
    const [url] = fetchMock.mock.calls[0]!
    expect(url).toBe('http://127.0.0.1:8000/api/v1/market')
  })

  it('sends a PUT with a JSON content-type for putNote', async () => {
    const fetchMock = vi.mocked(fetch)
    const note: Note = {
      id: 'note-1',
      cik: null,
      start_date: '2024-06-03',
      end_date: '2024-06-03',
      body: 'hello',
      created_at: '2024-06-03T00:00:00.000Z',
      updated_at: '2024-06-03T00:00:00.000Z'
    }
    fetchMock.mockResolvedValueOnce(jsonResponse(note, { status: 200 }))

    await putNote('note-1', { start_date: '2024-06-03', body: 'hello' })

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('http://127.0.0.1:8000/api/v1/notes/note-1')
    expect(init?.method).toBe('PUT')
    expect((init?.headers as Record<string, string>)['Content-Type']).toBe(
      'application/json'
    )
    expect(init?.body).toBe(
      JSON.stringify({ start_date: '2024-06-03', body: 'hello' })
    )
  })

  it('sends no body for DELETE and resolves on 204', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await expect(deleteNote('note-1')).resolves.toBeUndefined()
    const [, init] = fetchMock.mock.calls[0]!
    expect(init?.method).toBe('DELETE')
  })

  it('builds query strings from provided params only', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null })
    )

    await getNotes({ cik: '0000320193', limit: 20 })

    const [url] = fetchMock.mock.calls[0]!
    expect(url).toBe(
      'http://127.0.0.1:8000/api/v1/notes?cik=0000320193&limit=20'
    )
  })

  it('joins multiple event kinds with a comma', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null })
    )

    await getEvents({ cik: '0000320193', kind: ['split', 'cash_dividend'] })

    const [url] = fetchMock.mock.calls[0]!
    expect(url).toBe(
      'http://127.0.0.1:8000/api/v1/events?cik=0000320193&kind=split%2Ccash_dividend'
    )
  })

  it('throws a typed ApiError parsed from a problem+json body', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          type: 'https://stockticker.local/problems/unknown-cik',
          title: 'Unknown CIK',
          status: 422,
          detail: 'No company with that CIK.'
        },
        { status: 422 }
      )
    )

    const error = await getMarket().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.slug).toBe('unknown-cik')
    expect(apiError.status).toBe(422)
    expect(apiError.detail).toBe('No company with that CIK.')
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
})
