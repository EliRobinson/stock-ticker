'use client'

import { createChart, LineSeries } from 'lightweight-charts'
import type { Time } from 'lightweight-charts'
import { useEffect, useRef } from 'react'

import { useChartColors } from './chart-theme'
import type { ChartColors } from './chart-theme'
import { baseChartOptions } from './price-chart'

export interface TimeseriesSeries {
  label: string
  points: { time: string; value: number }[]
}

const seriesColor = (colors: ChartColors, i: number, el: HTMLElement) =>
  i === 0
    ? colors.line
    : getComputedStyle(el)
        .getPropertyValue(`--chart-${(i % 5) + 1}`)
        .trim()

// The AI panel's time-series view: same chart options and series color as the
// Company chart, so an answer's chart reads as part of the app (brief, Ask).
export function TimeseriesChart({
  series,
  height = 150,
  ariaLabel
}: {
  series: TimeseriesSeries[]
  height?: number
  ariaLabel: string
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const colors = useChartColors(hostRef)

  useEffect(() => {
    const host = hostRef.current
    if (!host || !colors) return
    const chart = createChart(host, {
      ...baseChartOptions(colors, height),
      handleScroll: false,
      handleScale: false
    })
    series.forEach((s, i) => {
      const line = chart.addSeries(LineSeries, {
        color: seriesColor(colors, i, host),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: series.length === 1,
        title: series.length > 1 ? s.label : ''
      })
      line.setData(
        s.points.map((p) => ({ time: p.time as Time, value: p.value }))
      )
    })
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [series, colors, height])

  const first = series[0]?.points[0]
  const last = series[0]?.points[series[0].points.length - 1]
  return (
    <div
      ref={hostRef}
      role='img'
      aria-label={`${ariaLabel}${first && last ? `, ${first.time} to ${last.time}, from ${first.value.toFixed(2)} to ${last.value.toFixed(2)}` : ''}`}
      className='w-full'
      style={{ height }}
    />
  )
}
