import type {
  CandlestickData,
  HistogramData,
  SeriesMarkerPosition,
  SeriesMarkerShape,
  Time
} from 'lightweight-charts'
import type { Bar, Event, Note } from './api'

export function mapBarsToCandlestickSeries(
  bars: Bar[]
): CandlestickData<Time>[] {
  return bars.map((bar) => {
    const close = Number(bar.close)
    const adjClose = Number(bar.adj_close)
    const factor = close === 0 ? 1 : adjClose / close
    return {
      time: bar.trade_date,
      open: Number(bar.open) * factor,
      high: Number(bar.high) * factor,
      low: Number(bar.low) * factor,
      close: adjClose
    }
  })
}

export interface VolumeBar extends HistogramData<Time> {
  direction: 'up' | 'down' | 'flat'
}

export function mapBarsToVolumeSeries(bars: Bar[]): VolumeBar[] {
  return bars.map((bar, i) => {
    const close = Number(bar.close)
    const prevBar = i > 0 ? bars[i - 1] : undefined
    const prevClose = prevBar ? Number(prevBar.close) : null
    const direction: VolumeBar['direction'] =
      prevClose === null || close === prevClose
        ? 'flat'
        : close > prevClose
          ? 'up'
          : 'down'
    return { time: bar.trade_date, value: bar.volume, direction }
  })
}

function sortedBarDates(bars: Bar[]): string[] {
  return bars.map((bar) => bar.trade_date).sort()
}

/**
 * Snaps a date to the nearest date that has a loaded bar, never inventing a
 * date the chart has no data for (docs/design/system-design.md §7: markers
 * "snap to a bar that actually exists in the loaded series, never to a
 * synthesized date"). Returns null when the date falls outside the loaded
 * range entirely - the caller lists it as "Outside chart range" instead of
 * drawing it.
 */
export function snapToLoadedBar(
  dateStr: string,
  dates: string[]
): string | null {
  const first = dates[0]
  const last = dates[dates.length - 1]
  if (first === undefined || last === undefined) return null
  if (dateStr < first || dateStr > last) return null

  let lo = 0
  let hi = dates.length - 1
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2)
    const midDate = dates[mid]
    if (midDate !== undefined && midDate < dateStr) {
      lo = mid + 1
    } else {
      hi = mid
    }
  }

  const after = dates[lo]
  if (after === undefined) return null
  if (after === dateStr) return after
  const before = lo > 0 ? dates[lo - 1] : undefined
  if (before === undefined) return after
  const msAfter = Math.abs(
    new Date(after).getTime() - new Date(dateStr).getTime()
  )
  const msBefore = Math.abs(
    new Date(dateStr).getTime() - new Date(before).getTime()
  )
  return msBefore <= msAfter ? before : after
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

export interface MappedNotes {
  markers: ChartMarker[]
  outsideRange: Note[]
}

export function mapNotesToMarkers(notes: Note[], bars: Bar[]): MappedNotes {
  const dates = sortedBarDates(bars)
  const markers: ChartMarker[] = []
  const outsideRange: Note[] = []

  for (const note of notes) {
    const snapped = snapToLoadedBar(note.start_date, dates)
    if (snapped === null) {
      outsideRange.push(note)
      continue
    }
    markers.push({
      id: note.id,
      kind: 'note',
      time: snapped,
      position: 'belowBar',
      shape: 'circle',
      text: note.body.slice(0, 40)
    })
  }

  return { markers, outsideRange }
}

export interface MappedEvents {
  markers: ChartMarker[]
  outsideRange: Event[]
}

export function mapEventsToMarkers(events: Event[], bars: Bar[]): MappedEvents {
  const dates = sortedBarDates(bars)
  const markers: ChartMarker[] = []
  const outsideRange: Event[] = []

  for (const event of events) {
    const snapped = snapToLoadedBar(event.event_date, dates)
    if (snapped === null) {
      outsideRange.push(event)
      continue
    }
    markers.push({
      id: String(event.id),
      kind: 'event',
      time: snapped,
      position: 'aboveBar',
      shape: 'square',
      text: event.title.slice(0, 40)
    })
  }

  return { markers, outsideRange }
}
