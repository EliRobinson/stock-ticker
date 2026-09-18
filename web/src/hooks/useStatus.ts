import { useQuery } from '@tanstack/react-query'
import { getStatus, type StatusResponse } from '@/lib/api'
import { pollIntervalMs } from '@/lib/staleness'

export const statusKeys = {
  all: ['status'] as const
}

const DEFAULT_POLL_MS = 10 * 1000

function nextPollIntervalMs(data: StatusResponse | undefined): number {
  if (!data) return DEFAULT_POLL_MS
  return pollIntervalMs(data.market_clock, data.server_time)
}

export function useStatus() {
  return useQuery({
    queryKey: statusKeys.all,
    queryFn: () => getStatus(),
    refetchInterval: (query) => nextPollIntervalMs(query.state.data)
  })
}
