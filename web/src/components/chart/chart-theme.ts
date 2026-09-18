'use client'

import { useEffect, useState } from 'react'
import type { RefObject } from 'react'

export interface ChartColors {
  text: string
  muted: string
  grid: string
  border: string
  line: string
  area: string
  volume: string
  up: string
  down: string
  note: string
  event: string
  range: string
  ring: string
  background: string
  font: string
}

function read(el: HTMLElement): ChartColors {
  const s = getComputedStyle(el)
  const v = (name: string) => s.getPropertyValue(name).trim()
  return {
    text: v('--foreground'),
    muted: v('--muted-foreground'),
    grid: v('--chart-grid'),
    border: v('--border'),
    line: v('--chart-line'),
    area: v('--chart-area'),
    volume: v('--chart-volume'),
    up: v('--up'),
    down: v('--down'),
    note: v('--chart-note'),
    event: v('--chart-event'),
    range: v('--chart-range'),
    ring: v('--ring'),
    background: v('--background'),
    font: s.fontFamily
  }
}

// lightweight-charts paints to canvas, so it can't use CSS variables directly.
// Read the theme tokens off the element and re-read whenever the theme class flips.
export function useChartColors(ref: RefObject<HTMLElement | null>) {
  const [colors, setColors] = useState<ChartColors | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setColors(read(el))
    update()
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'style']
    })
    return () => observer.disconnect()
  }, [ref])
  return colors
}
