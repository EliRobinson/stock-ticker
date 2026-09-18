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

// Keep in step with the `touch` custom variant in app/globals.css, which
// styles the same breakpoint in CSS.
export const TOUCH_PHONE = '(max-width: 639px) and (pointer: coarse)'

// Viewport widths the shell switches layout at (design R1): the Ask panel
// docks from 900px and the sidebar shows labels from 1200px.
export const DOCK_ASK = '(min-width: 900px)'
export const DESK = '(min-width: 1200px)'

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
