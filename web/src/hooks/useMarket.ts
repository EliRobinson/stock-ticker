import { useQuery } from '@tanstack/react-query'
import { getMarket, type MarketResponse } from '@/lib/api'
import { pollIntervalMs } from '@/lib/staleness'
import { OPEN_POLL_MS } from '@/lib/query-config'

export const marketKeys = {
  all: ['market'] as const
}

function nextPollIntervalMs(data: MarketResponse | undefined): number {
  if (!data) return OPEN_POLL_MS
  return pollIntervalMs(data.market_clock, data.server_time)
}

export function useMarket() {
  return useQuery({
    queryKey: marketKeys.all,
    queryFn: () => getMarket(),
    refetchInterval: (query) => nextPollIntervalMs(query.state.data)
  })
}
