import {
  keepPreviousData,
  useQuery,
  type QueryClient
} from '@tanstack/react-query'
import { getBars, type GetBarsParams } from '@/lib/api'

export const barsKeys = {
  all: ['bars'] as const,
  symbol: (symbol: string) => [...barsKeys.all, symbol] as const,
  list: (symbol: string, params: GetBarsParams) =>
    [...barsKeys.symbol(symbol), params] as const
}

/** History rarely changes once ingested; invalidated after `bars_daily`
 * updates land, not on a timer. */
const STALE_TIME_MS = 60 * 60 * 1000

export function useBars(symbol: string, params: GetBarsParams = {}) {
  return useQuery({
    queryKey: barsKeys.list(symbol, params),
    queryFn: () => getBars(symbol, params),
    staleTime: STALE_TIME_MS,
    placeholderData: keepPreviousData,
    enabled: symbol !== ''
  })
}

export function prefetchBars(
  queryClient: QueryClient,
  symbol: string,
  params: GetBarsParams = {}
): Promise<void> {
  return queryClient.prefetchQuery({
    queryKey: barsKeys.list(symbol, params),
    queryFn: () => getBars(symbol, params),
    staleTime: STALE_TIME_MS
  })
}
