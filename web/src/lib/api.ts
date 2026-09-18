import createClient from 'openapi-fetch'
import { env } from '@/env'
import type { components, paths } from './api-types'

export type ProblemDetail = components['schemas']['ProblemDetail']
export type MarketResponse = components['schemas']['MarketResponse']
export type MarketRow = components['schemas']['MarketRow']
export type MarketClock = components['schemas']['MarketClock']
export type CompanyDetail = components['schemas']['CompanyDetail']
export type Bar = components['schemas']['Bar']
export type MarketEvent = components['schemas']['Event']
export type Note = components['schemas']['Note']
export type StatusResponse = components['schemas']['StatusResponse']
export type AiStatus = components['schemas']['AiStatus']
// The generated names (EventsPage/NotesPage) are api-read's internal
// class names, not a public contract - aliased so a rename on that side
// doesn't ripple through every hook that already says "Response".
export type EventsResponse = components['schemas']['EventsPage']
export type NotesResponse = components['schemas']['NotesPage']

/**
 * The generated `NotePut.end_date` is required - api-read's own docs say
 * it's filled in from `start_date` by a `mode="before"` validator on the
 * raw request body before Pydantic's required-field check runs, so the
 * route is expected to still accept an omitted `end_date` at runtime. This
 * type keeps that optional for callers; putNote() fills it in itself
 * before it ever reaches the generated (required-end_date) request type,
 * so it's correct either way.
 */
export interface PutNoteBody {
  cik?: string | null
  start_date: string
  end_date?: string
  body: string
}

const client = createClient<paths>({
  baseUrl: env.NEXT_PUBLIC_API_URL,
  // openapi-fetch resolves its `fetch` option once, at createClient() call
  // time - since this client is a module-scope singleton, that's before a
  // test's vi.stubGlobal('fetch', ...) ever runs. This wrapper looks up
  // globalThis.fetch on every call instead of capturing it up front, so
  // stubbing the global still works, and production behavior is unchanged.
  fetch: (input) => globalThis.fetch(input)
})

export class ApiError extends Error {
  /** The full problem, including `type` and `errors[]` - use `.slug`/
   * `.status`/`.detail` for the common case, reach into `.problem` for
   * anything else (per-field validation errors, the `instance` URI). */
  readonly problem: ProblemDetail
  readonly slug: string
  readonly status: number
  readonly detail: string | null

  constructor(problem: ProblemDetail) {
    super(typeof problem.title === 'string' ? problem.title : 'Request failed')
    this.name = 'ApiError'
    this.problem = problem
    this.slug = slugFromProblemType(problem.type)
    this.status = problem.status
    this.detail = typeof problem.detail === 'string' ? problem.detail : null
  }
}

function slugFromProblemType(type: string | undefined): string {
  if (!type || type === 'about:blank') return 'about:blank'
  const trimmed = type.replace(/\/+$/, '')
  const lastSlash = trimmed.lastIndexOf('/')
  return lastSlash === -1 ? trimmed : trimmed.slice(lastSlash + 1)
}

/**
 * Every error the API sends is problem+json by contract (system-design.md
 * §5), but the OpenAPI schema doesn't always say so - a route's 422 can be
 * documented as FastAPI's own `HTTPValidationError` even though the
 * runtime handler normalizes it to a Problem. This rebuilds a well-formed
 * ProblemDetail from whatever came back instead of trusting either shape.
 */
function normalizeProblem(raw: unknown, response: Response): ProblemDetail {
  const body = (raw ?? {}) as Partial<ProblemDetail>
  return {
    type: typeof body.type === 'string' ? body.type : 'about:blank',
    title:
      typeof body.title === 'string'
        ? body.title
        : response.statusText || 'Request failed',
    status: typeof body.status === 'number' ? body.status : response.status,
    detail: typeof body.detail === 'string' ? body.detail : null,
    instance: typeof body.instance === 'string' ? body.instance : null,
    errors: Array.isArray(body.errors) ? body.errors : null
  }
}

interface FetchResult<T> {
  data?: T
  error?: unknown
  response: Response
}

/** For routes that always return a body on success (every route here
 * except DELETE, which calls `client.DELETE` directly - see deleteNote). */
async function unwrap<T>(result: FetchResult<T>): Promise<T> {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(normalizeProblem(result.error, result.response))
  }
  if (result.data === undefined) {
    throw new ApiError(normalizeProblem(undefined, result.response))
  }
  return result.data
}

export async function getMarket(): Promise<MarketResponse> {
  return unwrap(await client.GET('/api/v1/market'))
}

export async function getCompany(cik: string): Promise<CompanyDetail> {
  return unwrap(
    await client.GET('/api/v1/companies/{cik}', { params: { path: { cik } } })
  )
}

export interface GetBarsParams {
  from?: string
  to?: string
  timeframe?: '1d'
}

export const DEFAULT_BARS_TIMEFRAME = '1d' satisfies GetBarsParams['timeframe']

/** The route wraps bars in {symbol, timeframe, bars}, echoing the
 * requested timeframe back so the cache key stays unambiguous once
 * intraday timeframes exist (system-design.md §5) - unwrapped here so
 * every caller keeps working with a plain Bar[]. */
export async function getBars(
  symbol: string,
  params: GetBarsParams = {}
): Promise<Bar[]> {
  const response = await unwrap(
    await client.GET('/api/v1/listings/{symbol}/bars', {
      params: {
        path: { symbol },
        query: {
          from: params.from,
          to: params.to,
          timeframe: params.timeframe ?? DEFAULT_BARS_TIMEFRAME
        }
      }
    })
  )
  return response.bars
}

/** Exactly one of `cik`/`symbol` is required by the route (422 with
 * `.../problems/missing-cik-or-symbol` otherwise) - the union makes
 * passing neither, or both, a type error instead of a runtime one. */
export type GetEventsParams = (
  { cik: string; symbol?: never } | { symbol: string; cik?: never }
) & {
  from?: string
  to?: string
  kind?: string[]
  limit?: number
  cursor?: string
}

export async function getEvents(
  params: GetEventsParams
): Promise<EventsResponse> {
  return unwrap(
    await client.GET('/api/v1/events', {
      params: {
        query: {
          cik: params.cik,
          symbol: params.symbol,
          from: params.from,
          to: params.to,
          kind: params.kind?.join(','),
          limit: params.limit,
          cursor: params.cursor
        }
      }
    })
  )
}

export interface GetNotesParams {
  cik?: string
  from?: string
  to?: string
  market_only?: boolean
  /** With `cik`, also return whole-market Notes (cik === null). The route
   * 422s if `market_only` and `cik` are both given - `include_market` is
   * the one meant to combine with `cik`. */
  include_market?: boolean
  limit?: number
  cursor?: string
}

export async function getNotes(
  params: GetNotesParams = {}
): Promise<NotesResponse> {
  return unwrap(
    await client.GET('/api/v1/notes', {
      params: {
        query: {
          cik: params.cik,
          from: params.from,
          to: params.to,
          market_only: params.market_only,
          include_market: params.include_market,
          limit: params.limit,
          cursor: params.cursor
        }
      }
    })
  )
}

export async function putNote(id: string, body: PutNoteBody): Promise<Note> {
  return unwrap(
    await client.PUT('/api/v1/notes/{note_id}', {
      params: { path: { note_id: id } },
      body: {
        cik: body.cik ?? null,
        start_date: body.start_date,
        end_date: body.end_date ?? body.start_date,
        body: body.body
      }
    })
  )
}

export async function deleteNote(id: string): Promise<void> {
  const result = await client.DELETE('/api/v1/notes/{note_id}', {
    params: { path: { note_id: id } }
  })
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(normalizeProblem(result.error, result.response))
  }
}

export async function getStatus(): Promise<StatusResponse> {
  return unwrap(await client.GET('/api/v1/status'))
}
