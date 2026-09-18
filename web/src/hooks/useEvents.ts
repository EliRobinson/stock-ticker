import { useInfiniteQuery } from '@tanstack/react-query'
import {
  getEvents,
  type EventsListParams,
  type GetEventsParams
} from '@/lib/api'
import {
  HISTORY_STALE_TIME_MS,
  LIST_PAGE_LIMIT,
  cursorPaging
} from '@/lib/query-config'

import { flattenPages, useAllPages } from './useAllPages'

export const eventsKeys = {
  all: ['events'] as const,
  list: (params: EventsListParams) => [...eventsKeys.all, params] as const
}

/** Every Event matching `params`, all pages, flattened. */
export function useEvents(params: EventsListParams) {
  const query = useInfiniteQuery({
    queryKey: eventsKeys.list(params),
    // TS can't carry the cik-xor-symbol discriminant through an object
    // spread; `params` already satisfies it, and adding `cursor` doesn't
    // change that.
    queryFn: ({ pageParam }) =>
      getEvents({
        limit: LIST_PAGE_LIMIT,
        ...params,
        cursor: pageParam
      } as GetEventsParams),
    ...cursorPaging,
    staleTime: HISTORY_STALE_TIME_MS,
    enabled: Boolean(params.cik ?? params.symbol),
    select: flattenPages
  })
  useAllPages(query)
  return query
}
