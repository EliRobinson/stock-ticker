import {
  keepPreviousData,
  useQuery,
  type QueryClient
} from '@tanstack/react-query'
import { DEFAULT_BARS_TIMEFRAME, getBars, type GetBarsParams } from '@/lib/api'

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

/** History rarely changes once ingested; invalidated after `bars_daily`
 * updates land, not on a timer. */
const STALE_TIME_MS = 60 * 60 * 1000

export function useBars(
  symbol: string | undefined,
  params: GetBarsParams = {}
) {
  return useQuery({
    queryKey: barsKeys.list(symbol, params),
    queryFn: () => getBars(symbol as string, params),
    staleTime: STALE_TIME_MS,
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
    staleTime: STALE_TIME_MS
  })
}
