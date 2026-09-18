'use client'

import {
  AreaSeries,
  CandlestickSeries,
  createChart,
  HistogramSeries
} from 'lightweight-charts'
import type {
  CandlestickData,
  HistogramData,
  IChartApi,
  ISeriesApi,
  Time
} from 'lightweight-charts'
import { useEffect, useMemo, useRef } from 'react'

import type { PlacedMarker } from '@/lib/chart-data'
import { formatPrice } from '@/lib/format'
import { cn } from '@/lib/utils'

import { baseChartOptions, useChartColors } from './chart-theme'
import type { ChartColors } from './chart-theme'
import { MarkersPrimitive } from './markers-primitive'

export interface PriceChartProps {
  candles: CandlestickData<Time>[]
  volume: HistogramData<Time>[]
  mode: 'line' | 'candles'
  markers?: PlacedMarker[]
  highlightedId?: string | null
  visibleRange?: { from: string; to: string } | null
  onSelect?: (start: string, end: string) => void
  height?: number
  volumeHeight?: number
  ariaLabel: string
  summary: string
  className?: string
}

interface ChartParts {
  chart: IChartApi
  area: ISeriesApi<'Area'>
  candles: ISeriesApi<'Candlestick'>
  volume: ISeriesApi<'Histogram'>
  primitive: MarkersPrimitive
  attachedTo: ISeriesApi<'Area'> | ISeriesApi<'Candlestick'>
}

function seriesColors(colors: ChartColors) {
  return {
    area: {
      lineColor: colors.line,
      topColor: colors.area,
      bottomColor: colors.area,
      crosshairMarkerBackgroundColor: colors.line
    },
    candles: {
      upColor: colors.up,
      downColor: colors.down,
      borderUpColor: colors.up,
      borderDownColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down
    },
    volume: { color: colors.volume }
  }
}

// Adjusted close (line) or adjusted OHLC (candles), a synced volume pane, and
// Note/Event markers. The chart is built once; data, mode, theme, markers
// and range each update it in place, so zoom and an in-progress drag survive
// a refetch or a toggle. Click selects a date, a mouse drag selects a range.
export function PriceChart({
  candles,
  volume,
  mode,
  markers = [],
  highlightedId = null,
  visibleRange = null,
  onSelect,
  height = 250,
  volumeHeight = 58,
  ariaLabel,
  summary,
  className
}: PriceChartProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const colors = useChartColors(hostRef)
  const partsRef = useRef<ChartParts | null>(null)
  const datesRef = useRef<string[]>([])
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  const ready = colors !== null

  // Build once, when the theme tokens are first readable.
  useEffect(() => {
    const host = hostRef.current
    if (!host || !ready || !colors) return
    const chart = createChart(host, {
      ...baseChartOptions(colors),
      height: height + volumeHeight,
      handleScroll: {
        pressedMouseMove: false,
        mouseWheel: true,
        horzTouchDrag: true,
        vertTouchDrag: false
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: false
      }
    })
    const palette = seriesColors(colors)
    // No last-value labels: the stat row already shows the price, and the
    // label collides with the axis ticks near the top of the scale.
    const common = { priceLineVisible: false, lastValueVisible: false }
    const area = chart.addSeries(AreaSeries, {
      ...common,
      ...palette.area,
      lineWidth: 2
    })
    const candleSeries = chart.addSeries(CandlestickSeries, {
      ...common,
      ...palette.candles,
      visible: false
    })
    const volumeSeries = chart.addSeries(
      HistogramSeries,
      { ...common, ...palette.volume, priceFormat: { type: 'volume' } },
      1
    )
    const panes = chart.panes()
    panes[0]?.setHeight(height)
    panes[1]?.setHeight(volumeHeight)
    const primitive = new MarkersPrimitive({
      markers: [],
      values: new Map(),
      highlightedId: null,
      selection: null,
      colors
    })
    area.attachPrimitive(primitive)
    partsRef.current = {
      chart,
      area,
      candles: candleSeries,
      volume: volumeSeries,
      primitive,
      attachedTo: area
    }

    let dragFrom: number | null = null
    const xOf = (e: PointerEvent) =>
      e.clientX - host.getBoundingClientRect().left
    const dateAt = (x: number) => {
      const dates = datesRef.current
      const logical = chart.timeScale().coordinateToLogical(x)
      if (logical == null || dates.length === 0) return null
      const i = Math.max(0, Math.min(dates.length - 1, Math.round(logical)))
      return dates[i] ?? null
    }
    const cancel = () => {
      dragFrom = null
      primitive.update({ selection: null })
    }
    // Touch pans the chart; only a mouse or pen selects dates.
    const down = (e: PointerEvent) => {
      if (e.pointerType === 'touch' || e.button !== 0 || !onSelectRef.current)
        return
      dragFrom = xOf(e)
    }
    const move = (e: PointerEvent) => {
      if (dragFrom == null) return
      const x = xOf(e)
      if (Math.abs(x - dragFrom) > 4)
        primitive.update({ selection: { from: dragFrom, to: x } })
    }
    const up = (e: PointerEvent) => {
      if (dragFrom == null) return
      const x = xOf(e)
      const a = dateAt(Math.min(dragFrom, x))
      const b = dateAt(Math.max(dragFrom, x))
      cancel()
      if (a && b) onSelectRef.current?.(a, b)
    }
    host.addEventListener('pointerdown', down)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', cancel)

    return () => {
      host.removeEventListener('pointerdown', down)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', cancel)
      chart.remove()
      partsRef.current = null
    }
    // Colors are applied by their own effect; rebuilding on a theme change
    // would reset zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, height, volumeHeight])

  useEffect(() => {
    const parts = partsRef.current
    if (!parts || !colors) return
    const palette = seriesColors(colors)
    parts.chart.applyOptions(baseChartOptions(colors))
    parts.area.applyOptions(palette.area)
    parts.candles.applyOptions(palette.candles)
    parts.volume.applyOptions(palette.volume)
    parts.primitive.update({ colors })
  }, [colors])

  const values = useMemo(
    () => new Map(candles.map((c) => [String(c.time), c.close])),
    [candles]
  )

  useEffect(() => {
    const parts = partsRef.current
    if (!parts) return
    datesRef.current = candles.map((c) => String(c.time))
    parts.area.setData(candles.map((c) => ({ time: c.time, value: c.close })))
    parts.candles.setData(candles)
  }, [candles, ready])

  useEffect(() => {
    partsRef.current?.volume.setData(volume)
  }, [volume, ready])

  useEffect(() => {
    const parts = partsRef.current
    if (!parts) return
    parts.area.applyOptions({ visible: mode === 'line' })
    parts.candles.applyOptions({ visible: mode === 'candles' })
    const next = mode === 'line' ? parts.area : parts.candles
    if (next !== parts.attachedTo) {
      parts.attachedTo.detachPrimitive(parts.primitive)
      next.attachPrimitive(parts.primitive)
      parts.attachedTo = next
    }
  }, [mode, ready])

  useEffect(() => {
    partsRef.current?.primitive.update({ markers, values, highlightedId })
  }, [markers, values, highlightedId, ready])

  const hasData = candles.length > 0
  useEffect(() => {
    const chart = partsRef.current?.chart
    if (!chart || !hasData) return
    if (visibleRange) {
      chart
        .timeScale()
        .setVisibleRange({
          from: visibleRange.from as Time,
          to: visibleRange.to as Time
        })
    } else {
      chart.timeScale().fitContent()
    }
  }, [visibleRange, hasData, ready])

  const sampled = useMemo(() => {
    const step = Math.max(1, Math.floor(candles.length / 24))
    return candles.filter((_, i) => i % step === 0 || i === candles.length - 1)
  }, [candles])

  return (
    <figure className={cn('m-0', className)}>
      <div
        ref={hostRef}
        role='img'
        aria-label={`${ariaLabel}. ${summary}`}
        className={cn('w-full touch-pan-y', onSelect && 'cursor-crosshair')}
        style={{ height: height + volumeHeight }}
      />
      <table className='sr-only'>
        <caption>{ariaLabel}</caption>
        <thead>
          <tr>
            <th scope='col'>Trading Day</th>
            <th scope='col'>Adjusted close</th>
          </tr>
        </thead>
        <tbody>
          {sampled.map((c) => (
            <tr key={String(c.time)}>
              <td>{String(c.time)}</td>
              <td>{formatPrice(c.close, { currency: false })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
