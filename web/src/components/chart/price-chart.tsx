'use client'

import {
  AreaSeries,
  CandlestickSeries,
  createChart,
  HistogramSeries,
  LineStyle
} from 'lightweight-charts'
import type {
  DeepPartial,
  ChartOptions,
  IChartApi,
  ISeriesApi,
  Time
} from 'lightweight-charts'
import { useEffect, useMemo, useRef } from 'react'

import { cn } from '@/lib/utils'

import { useChartColors } from './chart-theme'
import type { ChartColors } from './chart-theme'
import { MarkersPrimitive } from './markers-primitive'
import type { PlacedMarker } from './markers-primitive'

export interface ChartBar {
  time: string
  open: number
  high: number
  low: number
  close: number
}

export interface VolumePoint {
  time: string
  value: number
}

export function baseChartOptions(
  colors: ChartColors,
  height: number
): DeepPartial<ChartOptions> {
  return {
    height,
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

export interface PriceChartProps {
  bars: ChartBar[]
  volume: VolumePoint[]
  mode: 'line' | 'candles'
  markers?: PlacedMarker[]
  highlightedId?: string | null
  visibleRange?: { from: string; to: string } | null
  onSelect?: (start: string, end: string) => void
  height?: number
  volumeHeight?: number
  ariaLabel: string
  className?: string
}

// Adjusted close (line) or adjusted OHLC (candles), a synced volume pane, and
// Note/Event markers. Click selects a date, drag selects a range.
export function PriceChart({
  bars,
  volume: volumePoints,
  mode,
  markers = [],
  highlightedId = null,
  visibleRange = null,
  onSelect,
  height = 250,
  volumeHeight = 58,
  ariaLabel,
  className
}: PriceChartProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const colors = useChartColors(hostRef)
  const chartRef = useRef<IChartApi | null>(null)
  const mainRef = useRef<ISeriesApi<'Area'> | ISeriesApi<'Candlestick'> | null>(
    null
  )
  const primitiveRef = useRef<MarkersPrimitive | null>(null)
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  const values = useMemo(
    () => new Map(bars.map((b) => [b.time, b.close])),
    [bars]
  )
  const placed = markers

  useEffect(() => {
    const host = hostRef.current
    if (!host || !colors) return
    const chart = createChart(host, {
      ...baseChartOptions(colors, height + volumeHeight),
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
    chartRef.current = chart

    const main =
      mode === 'candles'
        ? chart.addSeries(CandlestickSeries, {
            upColor: colors.up,
            downColor: colors.down,
            borderUpColor: colors.up,
            borderDownColor: colors.down,
            wickUpColor: colors.up,
            wickDownColor: colors.down,
            priceLineVisible: false
          })
        : chart.addSeries(AreaSeries, {
            lineColor: colors.line,
            lineWidth: 2,
            topColor: colors.area,
            bottomColor: colors.area,
            priceLineVisible: false,
            crosshairMarkerBackgroundColor: colors.line
          })
    if (mode === 'candles') {
      ;(main as ISeriesApi<'Candlestick'>).setData(
        bars.map((b) => ({
          time: b.time as Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close
        }))
      )
    } else {
      ;(main as ISeriesApi<'Area'>).setData(
        bars.map((b) => ({ time: b.time as Time, value: b.close }))
      )
    }
    mainRef.current = main

    const volume = chart.addSeries(
      HistogramSeries,
      {
        color: colors.volume,
        priceFormat: { type: 'volume' },
        priceLineVisible: false,
        lastValueVisible: false
      },
      1
    )
    volume.setData(
      volumePoints.map((v) => ({ time: v.time as Time, value: v.value }))
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
    main.attachPrimitive(primitive)
    primitiveRef.current = primitive

    let dragFrom: number | null = null
    const xOf = (e: PointerEvent) =>
      e.clientX - host.getBoundingClientRect().left
    const dateAt = (x: number) => {
      const logical = chart.timeScale().coordinateToLogical(x)
      if (logical == null) return null
      const i = Math.max(0, Math.min(bars.length - 1, Math.round(logical)))
      return bars[i]?.time ?? null
    }
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || !onSelectRef.current) return
      dragFrom = xOf(e)
    }
    const move = (e: PointerEvent) => {
      if (dragFrom == null) return
      const x = xOf(e)
      if (Math.abs(x - dragFrom) > 4) {
        primitive.update({ selection: { from: dragFrom, to: x } })
      }
    }
    const up = (e: PointerEvent) => {
      if (dragFrom == null) return
      const x = xOf(e)
      const a = dateAt(Math.min(dragFrom, x))
      const b = dateAt(Math.max(dragFrom, x))
      dragFrom = null
      primitive.update({ selection: null })
      if (a && b) onSelectRef.current?.(a, b)
    }
    host.addEventListener('pointerdown', down)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)

    return () => {
      host.removeEventListener('pointerdown', down)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      chart.remove()
      chartRef.current = null
      mainRef.current = null
      primitiveRef.current = null
    }
  }, [bars, volumePoints, mode, colors, height, volumeHeight])

  useEffect(() => {
    primitiveRef.current?.update({ markers: placed, values, highlightedId })
  }, [placed, values, highlightedId, colors, mode, bars])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || bars.length === 0) return
    if (visibleRange) {
      chart.timeScale().setVisibleRange({
        from: visibleRange.from as Time,
        to: visibleRange.to as Time
      })
    } else {
      chart.timeScale().fitContent()
    }
  }, [visibleRange, bars, mode, colors])

  const first = bars[0]
  const last = bars[bars.length - 1]
  const sampled = useMemo(() => {
    const step = Math.max(1, Math.floor(bars.length / 24))
    return bars.filter((_, i) => i % step === 0 || i === bars.length - 1)
  }, [bars])

  return (
    <figure className={cn('m-0', className)}>
      <div
        ref={hostRef}
        role='img'
        aria-label={`${ariaLabel}${first && last ? `, ${first.time} to ${last.time}, from ${first.close.toFixed(2)} to ${last.close.toFixed(2)}` : ''}. ${placed.filter((m) => m.kind === 'note').length} Notes and ${placed.filter((m) => m.kind === 'event').length} Events marked.`}
        className={cn('w-full touch-pan-y', onSelect && 'cursor-crosshair')}
        style={{ height: height + volumeHeight }}
      />
      <table className='sr-only'>
        <caption>{ariaLabel}, sampled points</caption>
        <thead>
          <tr>
            <th scope='col'>Trading Day</th>
            <th scope='col'>Adjusted close</th>
          </tr>
        </thead>
        <tbody>
          {sampled.map((b) => (
            <tr key={b.time}>
              <td>{b.time}</td>
              <td>{b.close.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
