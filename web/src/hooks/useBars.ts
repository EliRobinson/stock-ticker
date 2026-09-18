import {
  keepPreviousData,
  useQuery,
  type QueryClient
} from '@tanstack/react-query'
import { DEFAULT_BARS_TIMEFRAME, getBars, type GetBarsParams } from '@/lib/api'
import { HISTORY_STALE_TIME_MS } from '@/lib/query-config'

function normalizeBarsParams(params: GetBarsParams): Required<GetBarsParams> {
  return {
    from: params.from ?? '',
    to: params.to ?? '',
    timeframe: params.timeframe ?? DEFAULT_BARS_TIMEFRAME
  }
}

export const barsKeys = {
  all: ['bars'] as const,
  symbol: (symbol: string | undefined) => [...barsKeys.all, symbol] as const,
  /** Normalizes the omitted-timeframe case once, here - the request
   * defaults `timeframe` to '1d' when it's absent, so a call with `{}` and
   * a call with `{timeframe: '1d'}` must produce the same key or they
   * silently fetch and cache the identical response twice. */
  list: (symbol: string | undefined, params: GetBarsParams) =>
    [...barsKeys.symbol(symbol), normalizeBarsParams(params)] as const
}

export function useBars(
  symbol: string | undefined,
  params: GetBarsParams = {}
) {
  return useQuery({
    queryKey: barsKeys.list(symbol, params),
    queryFn: () => getBars(symbol as string, params),
    staleTime: HISTORY_STALE_TIME_MS,
    placeholderData: keepPreviousData,
    enabled: symbol !== undefined
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
    staleTime: HISTORY_STALE_TIME_MS
  })
}
