import { useInfiniteQuery } from '@tanstack/react-query'
import {
  getEvents,
  type EventsListParams,
  type GetEventsParams
} from '@/lib/api'
import { HISTORY_STALE_TIME_MS, cursorPaging } from '@/lib/query-config'

export const eventsKeys = {
  all: ['events'] as const,
  list: (params: EventsListParams) => [...eventsKeys.all, params] as const
}

export function useEvents(params: EventsListParams) {
  return useInfiniteQuery({
    queryKey: eventsKeys.list(params),
    // TS can't carry the cik-xor-symbol discriminant through an object
    // spread; `params` already satisfies it, and adding `cursor` doesn't
    // change that.
    queryFn: ({ pageParam }) =>
      getEvents({ ...params, cursor: pageParam } as GetEventsParams),
    ...cursorPaging,
    staleTime: HISTORY_STALE_TIME_MS,
    enabled: Boolean(params.cik ?? params.symbol)
  })
}
