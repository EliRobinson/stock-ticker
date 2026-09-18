import type { MarketResponse, MarketRow } from '@/lib/api'
import { HISTORY_START } from '@/lib/dates'
import { formatDateShort, toNumber } from '@/lib/format'
import { getQuoteStaleness } from '@/lib/staleness'

import { quoteAgeText } from '../shared/cells'
import { sharedCopy } from '../shared/copy'

export interface MarketRowView extends MarketRow {
  ageMs: number | null
  ageLabel: string
  stale: boolean
  closed: boolean
  backfillPending: boolean
  historyNote: string | null
  capNote: string | null
}

// A Listing's history is still loading until the API marks its backfill
// done. Until `backfill_completed_at` is in the generated types, a Listing
// with no first bar yet stands in for it.
export function isBackfillPending(
  row: Pick<MarketRow, 'first_bar_date'>
): boolean {
  if ('backfill_completed_at' in row) {
    return (
      (row as { backfill_completed_at: string | null }).backfill_completed_at ==
      null
    )
  }
  return row.first_bar_date == null
}

export function toRowViews(
  market: MarketResponse,
  { forceStale = false }: { forceStale?: boolean } = {}
): MarketRowView[] {
  const isOpen = market.market_clock?.is_open ?? false
  return market.listings.map((r) => {
    const q = getQuoteStaleness(r.observed_at, market.server_time, isOpen)
    const stale = forceStale || q.isStale
    const backfillPending = isBackfillPending(r)
    const partialHistory =
      r.first_bar_date != null && r.first_bar_date > HISTORY_START
    return {
      ...r,
      ageMs: q.ageMs,
      ageLabel: quoteAgeText(q.ageMs, stale),
      stale,
      closed: !isOpen,
      backfillPending,
      historyNote:
        partialHistory && toNumber(r.change_pct) == null
          ? sharedCopy.historyStarts(formatDateShort(r.first_bar_date))
          : null,
      capNote:
        !backfillPending && r.market_cap == null
          ? sharedCopy.capUnavailable
          : null
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
