'use client'

import { notFound } from 'next/navigation'
import { useCallback, useMemo } from 'react'

import { useBars } from '@/hooks/useBars'
import { useCompany } from '@/hooks/useCompany'
import { useEvents } from '@/hooks/useEvents'
import { useMarket } from '@/hooks/useMarket'
import { useNotes, useSaveNote } from '@/hooks/useNotes'
import { ApiError } from '@/lib/api'
import { primaryListing } from '@/lib/company'
import { HISTORY_START, todayInNewYork, weekdaysBetween } from '@/lib/dates'

import { CompanyScreen } from '../company/company-screen'
import type { CompanyView } from '../company/company-screen'
import type { PanelTab } from '../company/notes-events-panel'
import { parseRange, rangeToParam } from '../company/range'
import { isBackfillPending } from '../market/market-rows'
import { useUrlParams } from './url-state'

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

// The chosen Listing, range, chart mode and side tab live in the URL
// (?listing=&range=&mode=&tab=), so a Company view can be linked to.
export function CompanyContainer({ cik }: { cik: string }) {
  const company = useCompany(cik)
  const market = useMarket()
  const { params, set } = useUrlParams()
  const symbol =
    params.get('listing') ??
    (company.data
      ? primaryListing(company.data.listings)?.symbol
      : undefined) ??
    ''
  const bars = useBars(symbol || undefined)
  const events = useEvents({ cik })
  const notes = useNotes({ cik })
  const { save } = useSaveNote()
  const today = todayInNewYork()

  const view: CompanyView = useMemo(
    () => ({
      range: parseRange(params.get('range')),
      mode: params.get('mode') === 'candles' ? 'candles' : 'line',
      tab: (params.get('tab') === 'events' ? 'events' : 'notes') as PanelTab
    }),
    [params]
  )
  const onViewChange = useCallback(
    (next: Partial<CompanyView>) =>
      set({
        ...(next.range && { range: rangeToParam(next.range) }),
        ...(next.mode && { mode: next.mode === 'line' ? null : next.mode }),
        ...(next.tab && { tab: next.tab === 'notes' ? null : next.tab })
      }),
    [set]
  )

  if (isNotFound(company.error)) notFound()

  const listing = company.data?.listings.find((l) => l.symbol === symbol)
  const quote = market.data?.listings.find((r) => r.symbol === symbol) ?? null
  const loaded = bars.data?.length ?? 0
  const backfill =
    listing && isBackfillPending(listing) && loaded > 0
      ? { loaded, expected: weekdaysBetween(HISTORY_START, today) }
      : null

  return (
    <CompanyScreen
      company={company.data ?? null}
      loading={company.isPending}
      error={company.isError}
      onRetry={() => {
        company.refetch().catch(() => {})
      }}
      symbol={symbol}
      onSymbolChange={(s) => set({ listing: s })}
      quote={quote}
      serverTime={market.data?.server_time ?? null}
      isOpen={market.data?.market_clock?.is_open ?? false}
      bars={bars.data ?? (bars.isError ? [] : null)}
      barsError={bars.isError}
      backfill={backfill}
      notes={notes.data ?? []}
      events={events.data ?? []}
      today={today}
      view={view}
      onViewChange={onViewChange}
      onSaveNote={save}
    />
  )
}
