'use client'

import { createChart, LineSeries } from 'lightweight-charts'
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import { memo, useEffect, useRef } from 'react'

import { baseChartOptions, useChartColors } from './chart-theme'
import type { ChartColors } from './chart-theme'

export interface TimeseriesSeries {
  label: string
  points: { time: string; value: number }[]
}

const colorAt = (colors: ChartColors, i: number) =>
  i === 0
    ? colors.line
    : (colors.series[(i - 1) % colors.series.length] ?? colors.line)

// The Ask panel's time-series view: the Company chart's options and series
// color, so an answer's chart reads as part of the app. Built once; new
// series data is set in place. Memoized so streaming tokens elsewhere in the
// thread don't touch it.
export const TimeseriesChart = memo(function TimeseriesChart({
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
  const chartRef = useRef<IChartApi | null>(null)
  const linesRef = useRef<ISeriesApi<'Line'>[]>([])
  const ready = colors !== null

  useEffect(() => {
    const host = hostRef.current
    if (!host || !ready || !colors) return
    const chart = createChart(host, {
      ...baseChartOptions(colors),
      height,
      handleScroll: false,
      handleScale: false
    })
    chartRef.current = chart
    return () => {
      chart.remove()
      chartRef.current = null
      linesRef.current = []
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, height])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !colors) return
    chart.applyOptions(baseChartOptions(colors))
    linesRef.current.forEach((line, i) =>
      line.applyOptions({ color: colorAt(colors, i) })
    )
  }, [colors])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !colors) return
    for (const line of linesRef.current) chart.removeSeries(line)
    linesRef.current = series.map((s, i) => {
      const line = chart.addSeries(LineSeries, {
        color: colorAt(colors, i),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        title: series.length > 1 ? s.label : ''
      })
      line.setData(
        s.points.map((p) => ({ time: p.time as Time, value: p.value }))
      )
      return line
    })
    chart.timeScale().fitContent()
    // Colors are applied by their own effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, ready])

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
})
