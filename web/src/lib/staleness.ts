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
