/**
 * Every TanStack Query cache/poll timing constant, in one place. A value
 * duplicated across hooks always drifts eventually (see #22 review) -
 * every hook, providers.tsx, and staleness.ts import from here instead of
 * keeping a local copy.
 */

/** The default staleTime for any query that doesn't set its own
 * (providers.tsx) - short enough that a stale screen refreshes on the
 * next mount or refocus, long enough that navigating back and forth
 * doesn't refetch pointlessly. */
export const DEFAULT_STALE_TIME_MS = 60 * 1000

/** Bars, Company, and Events are all effectively historical once
 * ingested - a Daily Bar never changes, a Company's profile/market-cap/
 * 52-week range moves slowly, and Events are sourced facts - so all
 * three cache for an hour instead of the default minute. */
export const HISTORY_STALE_TIME_MS = 60 * 60 * 1000

/** Notes are the user's own writes - a minute is long enough to avoid
 * refetching on every remount, short enough that an edit made in another
 * tab shows up quickly. Kept as its own constant, not reused from
 * DEFAULT_STALE_TIME_MS, even though the values happen to match today -
 * Notes staleness is a product decision about the user's own data, not a
 * fallback for queries nobody configured. */
export const NOTES_STALE_TIME_MS = 60 * 1000

/** Market/status poll every 10s while the market is open - system-design.md
 * N1: a Quote should reach the screen within 30s of the provider's trade. */
export const OPEN_POLL_MS = 10 * 1000

/** ...5 minutes while closed - nothing changes intraday, so there's no
 * reason to poll as aggressively. */
export const CLOSED_POLL_MS = 5 * 60 * 1000

/** The floor under pollIntervalMs's next-open/next-close cap, so a clock
 * that's already past the transition (or only seconds from it) never
 * produces a near-zero or negative refetch interval. */
export const MIN_POLL_MS = 1000

/** A Quote older than this while the market is open counts as stale
 * (CONTEXT.md's Stale Quote definition). */
export const STALE_THRESHOLD_MS = 2 * 60 * 1000

/** Retries on a network error or 5xx - a 4xx never retries (providers.tsx:
 * the server is telling us the request itself is wrong, and retrying
 * unchanged input just repeats the same rejection). */
export const RETRY_COUNT = 2

/** The cursor-pagination half of useInfiniteQuery's options, shared by
 * useEvents and useNotes - both page through a `{next_cursor}` response
 * the same way, so there's exactly one place that decides how a page
 * turns into the next one's pageParam. */
export const cursorPaging = {
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage: { next_cursor?: string | null }) =>
    lastPage.next_cursor ?? undefined
}

/** Page size for lists the screens need whole (a Company's Notes and
 * Events, the Notes screen): the API's maximum, so one request usually
 * covers it and useAllPages fetches the rest. */
export const LIST_PAGE_LIMIT = 1000
