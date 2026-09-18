import { useQuery, type QueryClient } from '@tanstack/react-query'
import { getCompany } from '@/lib/api'
import { HISTORY_STALE_TIME_MS } from '@/lib/query-config'

export const companyKeys = {
  all: ['company'] as const,
  detail: (cik: string | undefined) => [...companyKeys.all, cik] as const
}

export function useCompany(cik: string | undefined) {
  return useQuery({
    queryKey: companyKeys.detail(cik),
    queryFn: () => getCompany(cik as string),
    staleTime: HISTORY_STALE_TIME_MS,
    enabled: cik !== undefined
  })
}

/** Called on Market row hover so the Company screen has data before the
 * click lands. */
export function prefetchCompany(
  queryClient: QueryClient,
  cik: string
): Promise<void> {
  return queryClient.prefetchQuery({
    queryKey: companyKeys.detail(cik),
    queryFn: () => getCompany(cik),
    staleTime: HISTORY_STALE_TIME_MS
  })
}
