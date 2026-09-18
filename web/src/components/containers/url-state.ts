'use client'

import { usePathname, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef } from 'react'

// Screen view state (Market filters, Company range and tab, Notes filters)
// lives in the URL so a research view can be linked to. Writes use
// history.replaceState, which Next.js syncs with useSearchParams, so typing
// never waits on a router round trip. `debounceMs` batches fast input.
export function useUrlParams() {
  const pathname = usePathname()
  const params = useSearchParams()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pending = useRef<Record<string, string | null>>({})

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    []
  )

  const flush = useCallback(() => {
    const next = new URLSearchParams(window.location.search)
    for (const [key, value] of Object.entries(pending.current)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    pending.current = {}
    const qs = next.toString()
    window.history.replaceState(null, '', `${pathname}${qs ? `?${qs}` : ''}`)
  }, [pathname])

  const set = useCallback(
    (updates: Record<string, string | null>, { debounceMs = 0 } = {}) => {
      Object.assign(pending.current, updates)
      if (timer.current) clearTimeout(timer.current)
      if (debounceMs > 0) timer.current = setTimeout(flush, debounceMs)
      else flush()
    },
    [flush]
  )

  return { params, set }
}
