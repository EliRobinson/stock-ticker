import type { MarketClock } from '@/lib/api'
import { getMarketStatus, getQuoteStaleness } from '@/lib/staleness'

import { shellCopy } from '../shell/copy'
import { formatTimeET } from './format'

export type Session = 'open' | 'closed' | 'pre' | 'after' | 'unknown'

function nyParts(iso: string) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false
  }).formatToParts(new Date(iso))
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  return {
    weekday: get('weekday'),
    minutes: (Number(get('hour')) % 24) * 60 + Number(get('minute'))
  }
}

// The API reports only is_open plus the next boundaries. The design's
// pre-market and after-hours pills are a display split of "closed", read off
// the response's own server_time in New York time; they never change staleness.
export function sessionOf(
  clock: MarketClock | null | undefined,
  serverTime: string
): Session {
  const status = getMarketStatus(clock ?? null)
  if (status !== 'closed' || !clock) return status
  const { weekday, minutes } = nyParts(serverTime)
  if (weekday === 'Sat' || weekday === 'Sun') return 'closed'
  const opensToday = clock.next_open.slice(0, 10) === serverTime.slice(0, 10)
  if (opensToday && minutes >= 4 * 60 && minutes < 9 * 60 + 30) return 'pre'
  if (minutes >= 16 * 60 && minutes < 20 * 60) return 'after'
  return 'closed'
}

export function sessionLabel(
  clock: MarketClock | null | undefined,
  serverTime: string
): string {
  const session = sessionOf(clock, serverTime)
  if (!clock || session === 'unknown') return shellCopy.status.unknown
  const open = formatTimeET(clock.next_open)
  switch (session) {
    case 'open':
      return shellCopy.status.open(formatTimeET(clock.next_close))
    case 'pre':
      return shellCopy.status.pre(open)
    case 'after':
      return shellCopy.status.after
    default:
      return shellCopy.status.closed(open)
  }
}

// Staleness only matters while the market is open; a closed market's last
// close is final, not stale (design M8).
export function quoteState(
  observedAt: string | null,
  serverTime: string,
  isOpen: boolean
) {
  const { ageMs, isStale } = getQuoteStaleness(observedAt, serverTime, isOpen)
  return { ageMs, stale: isStale }
}
