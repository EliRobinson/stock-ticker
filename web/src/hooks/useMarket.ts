import { useQuery } from '@tanstack/react-query'
import { getMarket } from '@/lib/api'
import { refetchIntervalFor } from '@/lib/staleness'

export const marketKeys = {
  all: ['market'] as const
}

export function useMarket() {
  return useQuery({
    queryKey: marketKeys.all,
    queryFn: () => getMarket(),
    refetchInterval: (query) => refetchIntervalFor(query.state.data)
  })
}
