import { useQuery } from '@tanstack/react-query'
import { getMarket, type MarketResponse } from '@/lib/api'
import { pollIntervalMs } from '@/lib/staleness'

export const marketKeys = {
  all: ['market'] as const
}

const DEFAULT_POLL_MS = 10 * 1000

function nextPollIntervalMs(data: MarketResponse | undefined): number {
  if (!data) return DEFAULT_POLL_MS
  return pollIntervalMs(data.market_clock, data.server_time)
}

export function useMarket() {
  return useQuery({
    queryKey: marketKeys.all,
    queryFn: () => getMarket(),
    refetchInterval: (query) => nextPollIntervalMs(query.state.data)
  })
}
