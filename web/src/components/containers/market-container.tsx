'use client'

import { useQueryClient } from '@tanstack/react-query'
import type { SortingState } from '@tanstack/react-table'
import { useRouter } from 'next/navigation'
import { useCallback, useMemo } from 'react'

import { prefetchBars } from '@/hooks/useBars'
import { prefetchCompany } from '@/hooks/useCompany'
import { useMarket } from '@/hooks/useMarket'
import { useStatus } from '@/hooks/useStatus'
import type { StatusResponse } from '@/lib/api'
import { parseMarketFilterState } from '@/lib/market-table'
import { companyHref } from '@/lib/routes'

import { MarketScreen } from '../market/market-screen'
import type { QuotesProblem } from '../market/market-screen'
import type { MarketRowView } from '../market/market-rows'
import { useUrlParams } from './url-state'

const SEARCH_DEBOUNCE_MS = 250

export function quotesProblemOf(
  status: StatusResponse | undefined
): QuotesProblem {
  if (!status) return null
  if (status.missing_keys.some((k) => k.startsWith('ALPACA')))
    return { kind: 'missing-key' }
  const quotes = status.jobs.find((j) => j.job === 'quotes')
  if (quotes?.status === 'failed') {
    return {
      kind: 'api-down',
      lastUpdated: quotes.last_success_at ?? status.data_as_of
    }
  }
  return null
}

// Filter and sort state lives in the URL (?q=&sector=&sort=), system design §7.
export function MarketContainer() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const market = useMarket()
  const status = useStatus()
  const { params, set } = useUrlParams()

  const state = useMemo(() => parseMarketFilterState(params), [params])
  const sorting: SortingState = useMemo(
    () =>
      state.sort
        ? [{ id: state.sort.id, desc: state.sort.desc }]
        : [{ id: 'symbol', desc: false }],
    [state.sort]
  )

  const onQueryChange = useCallback(
    (q: string) => set({ q }, { debounceMs: SEARCH_DEBOUNCE_MS }),
    [set]
  )
  const onSectorChange = useCallback(
    (sector: string | null) => set({ sector }),
    [set]
  )
  const onSortingChange = useCallback(
    (s: SortingState) =>
      set({ sort: s[0] ? `${s[0].desc ? '-' : ''}${s[0].id}` : null }),
    [set]
  )
  const onPrefetch = useCallback(
    (row: MarketRowView) => {
      prefetchCompany(queryClient, row.cik).catch(() => {})
      prefetchBars(queryClient, row.symbol).catch(() => {})
    },
    [queryClient]
  )

  return (
    <MarketScreen
      market={market.data ?? null}
      loading={market.isPending}
      quotesProblem={
        market.isError && !market.data
          ? { kind: 'api-down', lastUpdated: status.data?.data_as_of ?? null }
          : quotesProblemOf(status.data)
      }
      query={state.q}
      onQueryChange={onQueryChange}
      sector={state.sector}
      onSectorChange={onSectorChange}
      sorting={sorting}
      onSortingChange={onSortingChange}
      onOpenCompany={(row) => router.push(companyHref(row.cik))}
      onPrefetchCompany={onPrefetch}
    />
  )
}
