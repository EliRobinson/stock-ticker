'use client'

import type { StatusResponse } from '@/lib/api'
import { cn } from '@/lib/utils'

import { ProgressTrack } from '../shared/feedback'
import { formatDate, formatTimeET } from '../shared/format'
import {
  AiSpendPill,
  IngestHealthPill,
  MarketStatusPill
} from '../shared/status-pills'
import type { IngestDetail, IngestHealth } from '../shared/status-pills'
import { shellCopy as copy } from './copy'

export type AiStatus = StatusResponse['ai']

export function ingestHealth(status: StatusResponse | null): IngestHealth {
  if (!status) return 'failing'
  if (status.missing_keys.some((k) => k.startsWith('ALPACA'))) return 'failing'
  if (status.jobs.some((j) => j.status === 'failed')) return 'failing'
  if (
    status.jobs.some(
      (j) => j.status === 'partial' || j.consecutive_failures > 0
    )
  ) {
    return 'degraded'
  }
  return 'ok'
}

export function ingestDetail(status: StatusResponse): IngestDetail {
  const quotes = status.jobs.find((j) => j.job === 'quotes')
  const { listings_done: done, listings_total: total } = status.backfill
  const parts = [
    quotes?.error_summary ??
      copy.status.ingestQuotes(quotes?.status ?? 'not run'),
    copy.status.ingestBars(done, total)
  ]
  if (quotes && quotes.consecutive_failures > 0) {
    parts.push(copy.status.ingestFailures(quotes.consecutive_failures))
  }
  return {
    lastRunAt: quotes?.finished_at ?? null,
    summary: parts.join(' · ')
  }
}

export function StatusStrip({
  status,
  ai = null,
  loading = false,
  className
}: {
  status: StatusResponse | null
  ai?: AiStatus | null
  loading?: boolean
  className?: string
}) {
  const health = ingestHealth(status)
  const backfilling =
    status != null &&
    status.backfill.listings_total > 0 &&
    status.backfill.listings_done < status.backfill.listings_total
  const pct = backfilling
    ? Math.round(
        (status.backfill.listings_done / status.backfill.listings_total) * 100
      )
    : 100

  return (
    <div className={cn('border-border border-b', className)}>
      <div className='flex flex-wrap items-center gap-x-3.5 gap-y-1.5 px-4 py-3 max-sm:px-2.5 max-sm:py-2'>
        {loading || !status ? (
          <span className='text-muted-foreground text-xs'>
            {copy.status.loading}
          </span>
        ) : (
          <>
            <MarketStatusPill
              clock={status.market_clock}
              serverTime={status.server_time}
            />
            <span className='text-muted-foreground tabular text-xs'>
              {status.data_as_of
                ? copy.status.dataAsOf(
                    formatTimeET(status.data_as_of, true),
                    formatDate(status.data_as_of)
                  )
                : copy.status.noData}
            </span>
            <IngestHealthPill health={health} detail={ingestDetail(status)} />
            {ai && (
              <AiSpendPill
                spendUsd={ai.spend_usd}
                limitUsd={ai.limit_usd}
                className='ml-auto'
              />
            )}
          </>
        )}
      </div>
      {backfilling && (
        <div className='border-border tabular flex items-center gap-2.5 border-t px-4 py-2 text-xs'>
          <span role='status' aria-live='polite' className='sr-only'>
            {copy.status.backfillAnnounce(Math.floor(pct / 10) * 10)}
          </span>
          <span>
            {copy.status.backfill(
              status.backfill.listings_done,
              status.backfill.listings_total
            )}
          </span>
          <ProgressTrack value={pct} />
          <span aria-hidden='true' className='text-muted-foreground'>
            {pct}%
          </span>
        </div>
      )}
    </div>
  )
}
