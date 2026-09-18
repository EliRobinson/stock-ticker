import type {
  CandlestickData,
  HistogramData,
  SeriesMarkerPosition,
  SeriesMarkerShape,
  Time
} from 'lightweight-charts'
import { directionOf, toNumber, type Direction } from './format'
import type { Bar, MarketEvent, Note } from './api'

/** Bars with no usable close (0, missing, or unparseable) can't produce an
 * adjustment factor - skip them rather than dividing by zero or drawing a
 * bogus candle. */
export function mapBarsToCandlestickSeries(
  bars: Bar[]
): CandlestickData<Time>[] {
  const series: CandlestickData<Time>[] = []
  for (const bar of bars) {
    const close = toNumber(bar.close)
    const adjClose = toNumber(bar.adj_close)
    if (close === null || close === 0 || adjClose === null) continue
    const factor = adjClose / close
    series.push({
      time: bar.trade_date,
      open: Number(bar.open) * factor,
      high: Number(bar.high) * factor,
      low: Number(bar.low) * factor,
      close: adjClose
    })
  }
  return series
}

export interface VolumeBar extends HistogramData<Time> {
  direction: Direction
}

/** Direction compares adj_close, not the raw close - a split or dividend
 * moves the raw close without the Company's value actually changing, and
 * would otherwise paint a false down (or up) day. */
export function mapBarsToVolumeSeries(bars: Bar[]): VolumeBar[] {
  return bars.map((bar, i) => {
    const adjClose = toNumber(bar.adj_close)
    const prevBar = i > 0 ? bars[i - 1] : undefined
    const prevAdjClose = prevBar ? toNumber(prevBar.adj_close) : null
    const direction: Direction =
      adjClose === null || prevAdjClose === null
        ? 'flat'
        : directionOf(adjClose - prevAdjClose)
    return { time: bar.trade_date, value: bar.volume, direction }
  })
}

const sortedDatesCache = new WeakMap<Bar[], string[]>()

/** Memoized on the `bars` array identity - React Query hands back a stable
 * reference until the data actually changes, so re-sorting on every render
 * that reuses the same bars is wasted work. */
function sortedBarDates(bars: Bar[]): string[] {
  const cached = sortedDatesCache.get(bars)
  if (cached) return cached
  const sorted = bars.map((bar) => bar.trade_date).sort()
  sortedDatesCache.set(bars, sorted)
  return sorted
}

/** First loaded bar date >= dateStr, or null past the end of the series. */
export function snapForward(dateStr: string, dates: string[]): string | null {
  let lo = 0
  let hi = dates.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    const d = dates[mid]
    if (d !== undefined && d < dateStr) {
      lo = mid + 1
    } else {
      hi = mid
    }
  }
  const found = dates[lo]
  return found === undefined ? null : found
}

/** Last loaded bar date <= dateStr, or null before the start of the series. */
export function snapBackward(dateStr: string, dates: string[]): string | null {
  let lo = 0
  let hi = dates.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    const d = dates[mid]
    if (d !== undefined && d <= dateStr) {
      lo = mid + 1
    } else {
      hi = mid
    }
  }
  const idx = lo - 1
  const found = idx >= 0 ? dates[idx] : undefined
  return found === undefined ? null : found
}

/**
 * `color` is left to the caller: this module is pure and unit-tested with
 * no DOM, and marker color is a design-token decision that belongs to the
 * component that reads CSS custom properties, not to this data mapping.
 * `kind` tells the caller which token to use.
 */
export interface ChartMarker {
  id: string
  kind: 'note' | 'event'
  time: string
  position: SeriesMarkerPosition
  shape: SeriesMarkerShape
  text: string
}

/** A Note range clipped to the loaded bars and snapped inward at both
 * ends - `from`/`to` are always real bar dates, ready to shade. */
export interface NoteRange {
  id: string
  from: string
  to: string
}

interface ItemSpan {
  start: string
  end: string
}

interface MapToMarkersResult<T> {
  markers: ChartMarker[]
  ranges: NoteRange[]
  outsideRange: T[]
}

/**
 * One mapper for both Notes and Events, since both are "a date or a date
 * range, drawn on the chart or listed as outside it":
 * - No overlap at all with the loaded range -> outsideRange.
 * - A single date (start === end) -> a marker snapped FORWARD to the next
 *   existing bar (never back - a Note logged on a Sunday belongs to the
 *   Monday that follows it, not the Friday before).
 * - A real range that overlaps the loaded range (even partially, starting
 *   before it or ending after) -> clamped to the loaded range and each end
 *   snapped inward (start forward, end backward), via `toRange`. Events
 *   have no `toRange` - they're never ranged, so this path is unreachable
 *   for them.
 */
function mapToMarkers<T>(
  items: T[],
  bars: Bar[],
  dateOf: (item: T) => ItemSpan,
  toMarker: (item: T, snappedDate: string) => ChartMarker,
  toRange?: (item: T, from: string, to: string) => NoteRange
): MapToMarkersResult<T> {
  const dates = sortedBarDates(bars)
  const rangeStart = dates[0]
  const rangeEnd = dates[dates.length - 1]
  const markers: ChartMarker[] = []
  const ranges: NoteRange[] = []
  const outsideRange: T[] = []

  for (const item of items) {
    if (rangeStart === undefined || rangeEnd === undefined) {
      outsideRange.push(item)
      continue
    }

    const { start, end } = dateOf(item)
    const overlaps = start <= rangeEnd && end >= rangeStart
    if (!overlaps) {
      outsideRange.push(item)
      continue
    }

    if (start === end) {
      const snapped = snapForward(start, dates)
      if (snapped === null) {
        outsideRange.push(item)
        continue
      }
      markers.push(toMarker(item, snapped))
      continue
    }

    if (!toRange) {
      outsideRange.push(item)
      continue
    }

    const clampedStart = start < rangeStart ? rangeStart : start
    const clampedEnd = end > rangeEnd ? rangeEnd : end
    const from = snapForward(clampedStart, dates)
    const to = snapBackward(clampedEnd, dates)
    if (from === null || to === null) {
      outsideRange.push(item)
      continue
    }
    ranges.push(toRange(item, from, to))
  }

  return { markers, ranges, outsideRange }
}

export interface MappedNotes {
  markers: ChartMarker[]
  ranges: NoteRange[]
  outsideRange: Note[]
}

export function mapNotesToMarkers(notes: Note[], bars: Bar[]): MappedNotes {
  return mapToMarkers(
    notes,
    bars,
    (note) => ({ start: note.start_date, end: note.end_date }),
    (note, time) => ({
      id: note.id,
      kind: 'note',
      time,
      position: 'belowBar',
      shape: 'circle',
      text: note.body.slice(0, 40)
    }),
    (note, from, to) => ({ id: note.id, from, to })
  )
}

export interface MappedEvents {
  markers: ChartMarker[]
  outsideRange: MarketEvent[]
}

export function mapEventsToMarkers(
  events: MarketEvent[],
  bars: Bar[]
): MappedEvents {
  const { markers, outsideRange } = mapToMarkers(
    events,
    bars,
    (event) => ({ start: event.event_date, end: event.event_date }),
    (event, time) => ({
      id: String(event.id),
      kind: 'event',
      time,
      position: 'aboveBar',
      shape: 'square',
      text: event.title.slice(0, 40)
    })
  )
  return { markers, outsideRange }
}
