import { useQuery } from '@tanstack/react-query'
import { getStatus, type StatusResponse } from '@/lib/api'
import { pollIntervalMs } from '@/lib/staleness'
import { OPEN_POLL_MS } from '@/lib/query-config'

export const statusKeys = {
  all: ['status'] as const
}

function nextPollIntervalMs(data: StatusResponse | undefined): number {
  if (!data) return OPEN_POLL_MS
  return pollIntervalMs(data.market_clock, data.server_time)
}

export function useStatus() {
  return useQuery({
    queryKey: statusKeys.all,
    queryFn: () => getStatus(),
    refetchInterval: (query) => nextPollIntervalMs(query.state.data)
  })
}
