'use client'

import { useQueryClient } from '@tanstack/react-query'
import type { SortingState } from '@tanstack/react-table'
import type { Route } from 'next'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo } from 'react'

import { prefetchCompany } from '@/hooks/useCompany'
import { useMarket } from '@/hooks/useMarket'
import { useStatus } from '@/hooks/useStatus'
import type { StatusResponse } from '@/lib/api'
import {
  marketFilterStateToSearchParams,
  parseMarketFilterState
} from '@/lib/market-table'
import type { MarketFilterState } from '@/lib/market-table'

import { MarketScreen } from '../market/market-screen'
import type { QuotesProblem } from '../market/market-screen'
import { companyHref } from './shell-container'

export function quotesProblemOf(
  status: StatusResponse | undefined
): QuotesProblem {
  if (!status) return null
  if (status.missing_keys.some((k) => k.startsWith('ALPACA'))) {
    return { kind: 'missing-key' }
  }
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
  const pathname = usePathname()
  const params = useSearchParams()
  const queryClient = useQueryClient()
  const market = useMarket()
  const status = useStatus()

  const state = useMemo(
    () => parseMarketFilterState(new URLSearchParams(params.toString())),
    [params]
  )
  const sorting: SortingState = useMemo(
    () =>
      state.sort
        ? [{ id: state.sort.id, desc: state.sort.desc }]
        : [{ id: 'symbol', desc: false }],
    [state.sort]
  )

  const write = useCallback(
    (next: MarketFilterState) => {
      const qs = marketFilterStateToSearchParams(next).toString()
      router.replace(`${pathname}${qs ? `?${qs}` : ''}` as Route, {
        scroll: false
      })
    },
    [router, pathname]
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
      onQueryChange={(q) => write({ ...state, q })}
      sector={state.sector}
      onSectorChange={(sector) => write({ ...state, sector })}
      sorting={sorting}
      onSortingChange={(s) =>
        write({
          ...state,
          sort: s[0] ? { id: s[0].id, desc: s[0].desc } : null
        })
      }
      onOpenCompany={(row) => router.push(companyHref(row.cik))}
      onPrefetchCompany={(row) => {
        prefetchCompany(queryClient, row.cik).catch(() => {})
      }}
    />
  )
}
