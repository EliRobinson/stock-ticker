import type { MarketResponse, MarketRow } from '@/lib/api'

import { formatAge, formatDate, toNumber } from '../shared/format'
import { quoteState } from '../shared/market-session'
import { marketCopy as copy } from './copy'

export const HISTORY_START = '2018-01-02'

export interface MarketRowView extends MarketRow {
  ageMs: number | null
  ageLabel: string
  stale: boolean
  closed: boolean
  backfillPending: boolean
  historyNote: string | null
  capNote: string | null
}

export function toRowViews(
  market: MarketResponse,
  { forceStale = false }: { forceStale?: boolean } = {}
): MarketRowView[] {
  const isOpen = market.market_clock?.is_open ?? false
  return market.listings.map((r) => {
    const q = quoteState(r.observed_at, market.server_time, isOpen)
    const stale = forceStale || q.stale
    const backfillPending = r.first_bar_date == null
    const partialHistory =
      r.first_bar_date != null && r.first_bar_date > HISTORY_START
    return {
      ...r,
      ageMs: q.ageMs,
      ageLabel:
        q.ageMs == null ? '—' : `${formatAge(q.ageMs)}${stale ? ' old' : ''}`,
      stale,
      closed: !isOpen,
      backfillPending,
      historyNote:
        partialHistory && toNumber(r.change_pct) == null
          ? copy.historyStarts(formatDate(r.first_bar_date!))
          : null,
      capNote:
        !backfillPending && r.market_cap == null ? copy.capUnavailable : null
    }
  })
}

export const SECTORS = [
  'Communication Services',
  'Consumer Discretionary',
  'Consumer Staples',
  'Energy',
  'Financials',
  'Health Care',
  'Industrials',
  'Information Technology',
  'Materials',
  'Real Estate',
  'Utilities'
] as const
