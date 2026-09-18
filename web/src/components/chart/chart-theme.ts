'use client'

import { LineStyle } from 'lightweight-charts'
import type { ChartOptions, DeepPartial } from 'lightweight-charts'
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
  /** Extra series colors for multi-series charts, after `line`. */
  series: string[]
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
    series: ['--chart-2', '--chart-3', '--chart-4', '--chart-5'].map(v),
    font: s.fontFamily
  }
}

// lightweight-charts paints to canvas, so it can't use CSS variables directly.
// Every chart reads the theme tokens here, and re-reads them when the theme
// class on <html> (or the chart's own theme scope) changes.
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

// Shared by the Company chart and the Ask panel's charts, so an answer's
// chart looks like part of the app (brief, Shared components).
export function baseChartOptions(
  colors: ChartColors
): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { color: 'transparent' },
      textColor: colors.muted,
      fontFamily: colors.font,
      fontSize: 11,
      attributionLogo: false,
      panes: { separatorColor: colors.border, enableResize: false }
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { color: colors.grid, style: LineStyle.Solid }
    },
    rightPriceScale: { borderColor: colors.border },
    timeScale: {
      borderColor: colors.border,
      fixLeftEdge: true,
      fixRightEdge: true
    },
    crosshair: {
      vertLine: { color: colors.muted, labelBackgroundColor: colors.line },
      horzLine: { color: colors.muted, labelBackgroundColor: colors.line }
    }
  }
}
