import { env } from '@/env'
import type { components } from './api-types'

export type ProblemDetail = components['schemas']['ProblemDetail']
export type MarketResponse = components['schemas']['MarketResponse']
export type MarketRow = components['schemas']['MarketRow']
export type MarketClock = components['schemas']['MarketClock']
export type CompanyDetail = components['schemas']['CompanyDetail']
export type Bar = components['schemas']['Bar']
export type Event = components['schemas']['Event']
export type Note = components['schemas']['Note']
export type StatusResponse = components['schemas']['StatusResponse']
export type PutNoteBody = components['schemas']['NoteUpsert']

/**
 * `NotesResponse` and `EventsResponse` are two generated, non-generic types
 * with the same {items, next_cursor} shape (confirmed with the api-read
 * agent). This generic view over them is what the notes/events hooks and
 * their infinite-query cache helpers are written against, so a third
 * cursor-paginated resource needs no new cache-shape code.
 */
export interface Paginated<T> {
  items: T[]
  next_cursor: string | null
}

export class ApiError extends Error {
  readonly slug: string
  readonly status: number
  readonly detail: string | null

  constructor(problem: ProblemDetail) {
    super(problem.title)
    this.name = 'ApiError'
    this.slug = slugFromProblemType(problem.type)
    this.status = problem.status
    this.detail = problem.detail ?? null
  }
}

function slugFromProblemType(type: string | undefined): string {
  if (!type || type === 'about:blank') return 'about:blank'
  const trimmed = type.replace(/\/+$/, '')
  const lastSlash = trimmed.lastIndexOf('/')
  return lastSlash === -1 ? trimmed : trimmed.slice(lastSlash + 1)
}

async function parseProblem(res: Response): Promise<ProblemDetail> {
  try {
    const body = (await res.json()) as Partial<ProblemDetail>
    return {
      type: body.type ?? 'about:blank',
      title: body.title ?? res.statusText,
      status: body.status ?? res.status,
      detail: body.detail ?? null,
      instance: body.instance ?? null,
      errors: body.errors ?? null
    }
  } catch {
    return {
      type: 'about:blank',
      title: res.statusText || 'Request failed',
      status: res.status,
      detail: null,
      instance: null,
      errors: null
    }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${env.NEXT_PUBLIC_API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers
    }
  })

  if (!res.ok) {
    throw new ApiError(await parseProblem(res))
  }

  if (res.status === 204) {
    return undefined as T
  }

  return (await res.json()) as T
}

function toQueryString(
  params: Record<string, string | number | boolean | null | undefined>
): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export function getMarket(): Promise<MarketResponse> {
  return request<MarketResponse>('/api/v1/market')
}

export function getCompany(cik: string): Promise<CompanyDetail> {
  return request<CompanyDetail>(`/api/v1/companies/${encodeURIComponent(cik)}`)
}

export interface GetBarsParams {
  from?: string
  to?: string
  timeframe?: '1d'
}

type BarsResponse = components['schemas']['BarsResponse']

/** The route wraps bars in {symbol, timeframe, bars}, echoing the
 * requested timeframe back so the cache key stays unambiguous once
 * intraday timeframes exist (system-design.md §5) - unwrapped here so
 * every caller keeps working with a plain Bar[]. */
export async function getBars(
  symbol: string,
  params: GetBarsParams = {}
): Promise<Bar[]> {
  const qs = toQueryString({
    from: params.from,
    to: params.to,
    timeframe: params.timeframe ?? '1d'
  })
  const response = await request<BarsResponse>(
    `/api/v1/listings/${encodeURIComponent(symbol)}/bars${qs}`
  )
  return response.bars
}

export interface GetEventsParams {
  cik?: string
  symbol?: string
  from?: string
  to?: string
  kind?: string[]
  limit?: number
  cursor?: string
}

export function getEvents(params: GetEventsParams): Promise<Paginated<Event>> {
  const qs = toQueryString({
    cik: params.cik,
    symbol: params.symbol,
    from: params.from,
    to: params.to,
    kind: params.kind?.join(','),
    limit: params.limit,
    cursor: params.cursor
  })
  return request<Paginated<Event>>(`/api/v1/events${qs}`)
}

export interface GetNotesParams {
  cik?: string
  from?: string
  to?: string
  market_only?: boolean
  limit?: number
  cursor?: string
}

export function getNotes(
  params: GetNotesParams = {}
): Promise<Paginated<Note>> {
  const qs = toQueryString({
    cik: params.cik,
    from: params.from,
    to: params.to,
    market_only: params.market_only,
    limit: params.limit,
    cursor: params.cursor
  })
  return request<Paginated<Note>>(`/api/v1/notes${qs}`)
}

export function putNote(id: string, body: PutNoteBody): Promise<Note> {
  return request<Note>(`/api/v1/notes/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(body)
  })
}

export function deleteNote(id: string): Promise<void> {
  return request<void>(`/api/v1/notes/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  })
}

export function getStatus(): Promise<StatusResponse> {
  return request<StatusResponse>('/api/v1/status')
}
