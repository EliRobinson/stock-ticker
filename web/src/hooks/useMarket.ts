import { useQuery } from '@tanstack/react-query'
import { getMarket, type MarketResponse } from '@/lib/api'

export const marketKeys = {
  all: ['market'] as const
}

const OPEN_POLL_MS = 10 * 1000
const CLOSED_POLL_MS = 5 * 60 * 1000

function nextPollIntervalMs(data: MarketResponse | undefined): number {
  if (!data?.market_clock) return OPEN_POLL_MS
  return data.market_clock.is_open ? OPEN_POLL_MS : CLOSED_POLL_MS
}

export function useMarket() {
  return useQuery({
    queryKey: marketKeys.all,
    queryFn: () => getMarket(),
    refetchInterval: (query) => nextPollIntervalMs(query.state.data)
  })
}
