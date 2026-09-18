/**
 * Staleness is always computed from a single response's own `server_time`,
 * never `Date.now()` - the browser clock can drift from the server, and two
 * cached queries can be arbitrarily out of sync with each other (see #8
 * review round 2: "never combine two cached queries for this").
 */
export const STALE_THRESHOLD_MS = 2 * 60 * 1000

export function getQuoteAgeMs(
  observedAt: string | null,
  serverTime: string
): number {
  if (observedAt === null) return 0
  const ageMs = new Date(serverTime).getTime() - new Date(observedAt).getTime()
  return Math.max(0, ageMs)
}

export function isQuoteStale(
  observedAt: string | null,
  serverTime: string
): boolean {
  if (observedAt === null) return true
  return getQuoteAgeMs(observedAt, serverTime) > STALE_THRESHOLD_MS
}

export interface QuoteStaleness {
  ageMs: number
  isStale: boolean
}

export function getQuoteStaleness(
  observedAt: string | null,
  serverTime: string
): QuoteStaleness {
  return {
    ageMs: getQuoteAgeMs(observedAt, serverTime),
    isStale: isQuoteStale(observedAt, serverTime)
  }
}

export interface MarketClockLike {
  is_open: boolean
}

export type MarketStatus = 'open' | 'closed' | 'unknown'

/**
 * The API's MarketClock is a plain is_open boolean plus next_open/next_close
 * - it has no pre-market/after-hours state. Callers that want a pre/after
 * label are asking for something the API doesn't report; this returns
 * 'unknown' only when there is no clock at all (schema has it nullable
 * "until the Alpaca agent wires up fetch_market_clock").
 */
export function getMarketStatus(clock: MarketClockLike | null): MarketStatus {
  if (clock === null) return 'unknown'
  return clock.is_open ? 'open' : 'closed'
}
