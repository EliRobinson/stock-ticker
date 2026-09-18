import { useQuery } from '@tanstack/react-query'
import { getStatus } from '@/lib/api'
import { refetchIntervalFor } from '@/lib/staleness'

export const statusKeys = {
  all: ['status'] as const
}

export function useStatus() {
  return useQuery({
    queryKey: statusKeys.all,
    queryFn: () => getStatus(),
    refetchInterval: (query) => refetchIntervalFor(query.state.data)
  })
}
