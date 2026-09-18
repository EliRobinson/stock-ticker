import type { InfiniteData } from '@tanstack/react-query'
import { useEffect } from 'react'

/** The `select` for a cursor-paged list the screens use whole. The cache
 * keeps its InfiniteData pages (optimistic Note writes rely on them). */
export function flattenPages<P extends { items: unknown[] }>(
  data: InfiniteData<P, unknown>
): P['items'] {
  return data.pages.flatMap((page) => page.items)
}

/** Keeps fetching until the last page, so a screen never shows page 1 of a
 * Company's Notes or Events as if it were all of them. */
export function useAllPages(query: {
  hasNextPage: boolean
  isFetchingNextPage: boolean
  isError: boolean
  fetchNextPage: () => Promise<unknown>
}) {
  const { hasNextPage, isFetchingNextPage, isError, fetchNextPage } = query
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isError) {
      fetchNextPage().catch(() => {})
    }
  }, [hasNextPage, isFetchingNextPage, isError, fetchNextPage])
}
