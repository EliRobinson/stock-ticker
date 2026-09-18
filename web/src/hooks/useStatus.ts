import { useQuery } from '@tanstack/react-query'
import { getStatus, type StatusResponse } from '@/lib/api'

export const statusKeys = {
  all: ['status'] as const
}

const OPEN_POLL_MS = 10 * 1000
const CLOSED_POLL_MS = 5 * 60 * 1000

function nextPollIntervalMs(data: StatusResponse | undefined): number {
  if (!data?.market_clock) return OPEN_POLL_MS
  return data.market_clock.is_open ? OPEN_POLL_MS : CLOSED_POLL_MS
}

export function useStatus() {
  return useQuery({
    queryKey: statusKeys.all,
    queryFn: () => getStatus(),
    refetchInterval: (query) => nextPollIntervalMs(query.state.data)
  })
}
