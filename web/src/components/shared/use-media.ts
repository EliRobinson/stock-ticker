'use client'

import { useEffect, useState, useSyncExternalStore } from 'react'
import type { RefObject } from 'react'

export function useMediaQuery(query: string, serverValue = false): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', notify)
      return () => mql.removeEventListener('change', notify)
    },
    () => window.matchMedia(query).matches,
    () => serverValue
  )
}

export const TOUCH_PHONE = '(max-width: 639px) and (pointer: coarse)'

export function useElementWidth(
  ref: RefObject<HTMLElement | null>,
  fallback = 1200
) {
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return width
}
