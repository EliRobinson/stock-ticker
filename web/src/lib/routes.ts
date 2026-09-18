import type { Route } from 'next'

/** Every in-app path, in one place, so links and shortcuts can't drift. */
export const ROUTES = {
  market: '/',
  notes: '/notes'
} as const satisfies Record<string, Route>

export function companyHref(cik: string): Route {
  return `/companies/${encodeURIComponent(cik)}` as Route
}
