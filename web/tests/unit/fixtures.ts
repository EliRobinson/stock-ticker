import type { InfiniteData } from '@tanstack/react-query'
import type { Bar, MarketEvent, Note, ProblemDetail } from '@/lib/api'

/** Apple Inc.'s CIK - the one Company every test that needs a real cik
 * uses, so a typo'd digit string doesn't quietly become a second "real"
 * test company. */
export const AAPL_CIK = '0000320193'

export function makeBar(overrides: Partial<Bar> = {}): Bar {
  return {
    trade_date: '2024-06-03',
    open: '100',
    high: '105',
    low: '99',
    close: '104',
    volume: 1_000_000,
    adj_close: '104',
    ...overrides
  }
}

export function makeNote(overrides: Partial<Note> = {}): Note {
  return {
    id: 'note-1',
    cik: AAPL_CIK,
    start_date: '2024-06-03',
    end_date: '2024-06-03',
    body: 'Looks cheap here.',
    created_at: '2024-06-03T12:00:00.000Z',
    updated_at: '2024-06-03T12:00:00.000Z',
    ...overrides
  }
}

export function makeEvent(overrides: Partial<MarketEvent> = {}): MarketEvent {
  return {
    id: 1,
    cik: AAPL_CIK,
    symbol: 'AAPL',
    event_date: '2024-06-03',
    kind: 'split',
    title: '4-for-1 split',
    details: {},
    source: 'sec',
    source_ref: 'ref-1',
    ...overrides
  }
}

export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init
  })
}

/** A problem+json error response - every field defaults to what a route
 * with no more specific error would send, so a test only names the field
 * it actually cares about. */
export function problemResponse(
  status: number,
  overrides: Partial<ProblemDetail> = {}
): Response {
  return jsonResponse(
    {
      type: 'about:blank',
      title: 'Request failed',
      status,
      detail: null,
      instance: null,
      errors: null,
      ...overrides
    },
    { status }
  )
}

/**
 * Builds a TanStack `InfiniteData` from one items array per page - the
 * shape every notes/events cache entry has. `infinitePages([a, b])` is the
 * common single-page case (next_cursor: null); `infinitePages([a], [b])`
 * simulates a second page behind a cursor.
 */
export function infinitePages<T>(
  ...itemsPerPage: T[][]
): InfiniteData<{ items: T[]; next_cursor: string | null }> {
  const pages = itemsPerPage.map((items, i) => ({
    items,
    next_cursor: i < itemsPerPage.length - 1 ? `cursor-${i + 1}` : null
  }))
  return {
    pages,
    pageParams: itemsPerPage.map(() => undefined)
  }
}
