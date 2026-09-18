import { useInfiniteQuery } from '@tanstack/react-query'
import { getEvents, type GetEventsParams } from '@/lib/api'

export const eventsKeys = {
  all: ['events'] as const,
  list: (params: Omit<GetEventsParams, 'cursor'>) =>
    [...eventsKeys.all, params] as const
}

/** Events are sourced facts (splits, filings, ...); they don't change once
 * ingested, so this can cache as long as bars. */
const STALE_TIME_MS = 60 * 60 * 1000

export function useEvents(params: Omit<GetEventsParams, 'cursor'>) {
  return useInfiniteQuery({
    queryKey: eventsKeys.list(params),
    // TS can't carry the cik-xor-symbol discriminant through an object
    // spread; `params` already satisfies it, and adding `cursor` doesn't
    // change that.
    queryFn: ({ pageParam }) =>
      getEvents({ ...params, cursor: pageParam } as GetEventsParams),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: STALE_TIME_MS,
    enabled: Boolean(params.cik ?? params.symbol)
  })
}
