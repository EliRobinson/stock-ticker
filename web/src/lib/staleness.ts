/**
 * Staleness and the poll interval are always computed from a single
 * response's own `server_time`, never `Date.now()` - the browser clock can
 * drift from the server, and two cached queries can be arbitrarily out of
 * sync with each other (see #8 review round 2: "never combine two cached
 * queries for this").
 */
export const STALE_THRESHOLD_MS = 2 * 60 * 1000

function toEpochMs(value: string): number {
  return new Date(value).getTime()
}

/** null covers both "never observed" and an unparseable timestamp - callers
 * must not treat either as "0ms old". */
export function getQuoteAgeMs(
  observedAt: string | null,
  serverTime: string
): number | null {
  if (observedAt === null) return null
  const observedMs = toEpochMs(observedAt)
  const serverMs = toEpochMs(serverTime)
  if (Number.isNaN(observedMs) || Number.isNaN(serverMs)) return null
  return Math.max(0, serverMs - observedMs)
}

/**
 * CONTEXT.md: "Stale Quote: A Quote older than expected while the market is
 * open." Staleness is not a concept that applies while the market is
 * closed, so this is false whenever `isMarketOpen` is false, regardless of
 * age - it is not staleness that is being cleared, it is the question
 * itself that doesn't apply.
 */
export function isQuoteStale(
  observedAt: string | null,
  serverTime: string,
  isMarketOpen: boolean
): boolean {
  if (!isMarketOpen) return false
  const ageMs = getQuoteAgeMs(observedAt, serverTime)
  if (ageMs === null) return true
  return ageMs > STALE_THRESHOLD_MS
}

export interface QuoteStaleness {
  ageMs: number | null
  isStale: boolean
}

export function getQuoteStaleness(
  observedAt: string | null,
  serverTime: string,
  isMarketOpen: boolean
): QuoteStaleness {
  return {
    ageMs: getQuoteAgeMs(observedAt, serverTime),
    isStale: isQuoteStale(observedAt, serverTime, isMarketOpen)
  }
}

export interface MarketClockLike {
  is_open: boolean
  next_open: string
  next_close: string
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

const OPEN_POLL_MS = 10 * 1000
const CLOSED_POLL_MS = 5 * 60 * 1000
const MIN_POLL_MS = 1000

/**
 * One poll-interval rule, shared by useMarket and useStatus so the two
 * hooks can never drift apart: 10s while open, capped so a poll is never
 * scheduled past the close; 5min while closed, capped so a poll is never
 * scheduled past the open; 10s with no clock at all. Every branch has a 1s
 * floor - `next_open`/`next_close` a few seconds out (or briefly in the
 * past, on clock skew) must never produce a near-zero or negative interval.
 */
export function pollIntervalMs(
  clock: MarketClockLike | null,
  serverTime: string
): number {
  if (clock === null) return OPEN_POLL_MS
  const now = toEpochMs(serverTime)
  if (clock.is_open) {
    const untilClose = toEpochMs(clock.next_close) - now
    return Math.max(MIN_POLL_MS, Math.min(OPEN_POLL_MS, untilClose))
  }
  const untilOpen = toEpochMs(clock.next_open) - now
  return Math.max(MIN_POLL_MS, Math.min(CLOSED_POLL_MS, untilOpen))
}
