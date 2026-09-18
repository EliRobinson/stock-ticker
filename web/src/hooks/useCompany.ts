import { queryOptions, useQuery, type QueryClient } from '@tanstack/react-query'
import { getCompany } from '@/lib/api'
import { HISTORY_STALE_TIME_MS } from '@/lib/query-config'

export const companyKeys = {
  all: ['company'] as const,
  detail: (cik: string | undefined) => [...companyKeys.all, cik] as const
}

/** The one query definition useCompany and prefetchCompany both build on -
 * see barsQueryOptions for why. */
export function companyQueryOptions(cik: string | undefined) {
  return queryOptions({
    queryKey: companyKeys.detail(cik),
    queryFn: () => getCompany(cik as string),
    staleTime: HISTORY_STALE_TIME_MS
  })
}

export function useCompany(cik: string | undefined) {
  return useQuery({ ...companyQueryOptions(cik), enabled: cik !== undefined })
}

/** Called on Market row hover so the Company screen has data before the
 * click lands. */
export function prefetchCompany(
  queryClient: QueryClient,
  cik: string
): Promise<void> {
  return queryClient.prefetchQuery(companyQueryOptions(cik))
}
