'use client'

import { useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'

const noopSubscribe = () => () => {}

/** False on the server and during the hydration render, true after. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  )
}

/**
 * Renders `fallback` on the server and on the hydration pass, `children`
 * after. A page inside a `loading.tsx` boundary can hydrate after the shell's
 * queries have already filled the shared cache, so its first client render
 * would show data the server HTML never had.
 */
export function AfterHydration({
  fallback,
  children
}: {
  fallback: ReactNode
  children: ReactNode
}) {
  return useHydrated() ? children : fallback
}
