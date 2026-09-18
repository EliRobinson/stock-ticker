import type { CandlestickData, HistogramData, Time } from 'lightweight-charts'
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
 * A Note or Event placed on the loaded bars: `barDate` is the bar the marker
 * sits on, and `start`/`end` is the span to shade (both real bar dates; equal
 * for a single date or an Event). Color and shape are the component's call,
 * from `kind` and the theme tokens, so this module stays DOM-free.
 */
export interface PlacedMarker {
  id: string
  kind: 'note' | 'event'
  barDate: string
  start: string
  end: string
}

interface ItemSpan {
  start: string
  end: string
}

interface MapToMarkersResult<T> {
  markers: PlacedMarker[]
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
 *   snapped inward (start forward, end backward); the marker sits on its
 *   first bar. Events always have start === end.
 */
function mapToMarkers<T>(
  items: T[],
  bars: Bar[],
  dateOf: (item: T) => ItemSpan,
  idOf: (item: T) => string,
  kind: PlacedMarker['kind']
): MapToMarkersResult<T> {
  const dates = sortedBarDates(bars)
  const rangeStart = dates[0]
  const rangeEnd = dates[dates.length - 1]
  const markers: PlacedMarker[] = []
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
      markers.push({
        id: idOf(item),
        kind,
        barDate: snapped,
        start: snapped,
        end: snapped
      })
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
    markers.push({ id: idOf(item), kind, barDate: from, start: from, end: to })
  }

  return { markers, outsideRange }
}

export interface MappedNotes {
  markers: PlacedMarker[]
  outsideRange: Note[]
}

export function mapNotesToMarkers(notes: Note[], bars: Bar[]): MappedNotes {
  return mapToMarkers(
    notes,
    bars,
    (note) => ({ start: note.start_date, end: note.end_date }),
    (note) => note.id,
    'note'
  )
}

export interface MappedEvents {
  markers: PlacedMarker[]
  outsideRange: MarketEvent[]
}

/** Event ids are prefixed so they never collide with a Note's id. */
export function eventMarkerId(event: Pick<MarketEvent, 'id'>): string {
  return `event-${event.id}`
}

export function mapEventsToMarkers(
  events: MarketEvent[],
  bars: Bar[]
): MappedEvents {
  return mapToMarkers(
    events,
    bars,
    (event) => ({ start: event.event_date, end: event.event_date }),
    eventMarkerId,
    'event'
  )
}
