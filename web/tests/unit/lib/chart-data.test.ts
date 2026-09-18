import { describe, expect, it } from 'vitest'
import {
  mapBarsToCandlestickSeries,
  mapBarsToVolumeSeries,
  mapEventsToMarkers,
  mapNotesToMarkers,
  snapBackward,
  snapForward
} from '@/lib/chart-data'
import { makeBar, makeEvent, makeNote } from '../fixtures'

describe('mapBarsToCandlestickSeries', () => {
  it('scales OHLC by the adjusted-close factor', () => {
    const bars = [
      makeBar({
        open: '100',
        high: '110',
        low: '90',
        close: '100',
        adj_close: '50'
      })
    ]
    expect(mapBarsToCandlestickSeries(bars)).toEqual([
      { time: '2024-06-03', open: 50, high: 55, low: 45, close: 50 }
    ])
  })

  it('leaves an unadjusted bar unchanged', () => {
    const bars = [
      makeBar({
        open: '10',
        high: '12',
        low: '9',
        close: '11',
        adj_close: '11'
      })
    ]
    expect(mapBarsToCandlestickSeries(bars)).toEqual([
      { time: '2024-06-03', open: 10, high: 12, low: 9, close: 11 }
    ])
  })

  it('skips a bar with a zero close instead of dividing by zero', () => {
    const bars = [
      makeBar({ trade_date: '2024-06-03', close: '0', adj_close: '0' }),
      makeBar({ trade_date: '2024-06-04', close: '104', adj_close: '104' })
    ]
    expect(mapBarsToCandlestickSeries(bars)).toEqual([
      { time: '2024-06-04', open: 100, high: 105, low: 99, close: 104 }
    ])
  })

  it('skips a bar with an unparseable close', () => {
    const bars = [makeBar({ close: 'n/a' })]
    expect(mapBarsToCandlestickSeries(bars)).toEqual([])
  })
})

describe('mapBarsToVolumeSeries', () => {
  it('marks the first bar flat and later bars by adjusted-close direction', () => {
    const bars = [
      makeBar({
        trade_date: '2024-06-03',
        close: '100',
        adj_close: '100',
        volume: 10
      }),
      makeBar({
        trade_date: '2024-06-04',
        close: '105',
        adj_close: '105',
        volume: 20
      }),
      makeBar({
        trade_date: '2024-06-05',
        close: '102',
        adj_close: '102',
        volume: 30
      })
    ]
    expect(mapBarsToVolumeSeries(bars)).toEqual([
      { time: '2024-06-03', value: 10, direction: 'flat' },
      { time: '2024-06-04', value: 20, direction: 'up' },
      { time: '2024-06-05', value: 30, direction: 'down' }
    ])
  })

  it('reads direction from adj_close, not the raw close a split moves', () => {
    // A 2-for-1 split halves the raw close without the Company losing
    // value - adj_close (already split-adjusted) stays flat.
    const bars = [
      makeBar({ trade_date: '2024-06-03', close: '200', adj_close: '100' }),
      makeBar({ trade_date: '2024-06-04', close: '100', adj_close: '100' })
    ]
    expect(mapBarsToVolumeSeries(bars)[1]?.direction).toBe('flat')
  })
})

describe('snapForward', () => {
  const dates = ['2024-06-03', '2024-06-04', '2024-06-06']

  it('returns null for an empty series', () => {
    expect(snapForward('2024-06-03', [])).toBeNull()
  })

  it('returns the exact date when a bar exists', () => {
    expect(snapForward('2024-06-04', dates)).toBe('2024-06-04')
  })

  it('snaps forward across a gap', () => {
    expect(snapForward('2024-06-05', dates)).toBe('2024-06-06')
  })

  it('snaps forward from before the first loaded bar', () => {
    expect(snapForward('2024-06-01', dates)).toBe('2024-06-03')
  })

  it('returns null past the last loaded bar', () => {
    expect(snapForward('2024-06-10', dates)).toBeNull()
  })
})

describe('snapBackward', () => {
  const dates = ['2024-06-03', '2024-06-04', '2024-06-06']

  it('returns the exact date when a bar exists', () => {
    expect(snapBackward('2024-06-04', dates)).toBe('2024-06-04')
  })

  it('snaps backward across a gap', () => {
    expect(snapBackward('2024-06-05', dates)).toBe('2024-06-04')
  })

  it('snaps backward from after the last loaded bar', () => {
    expect(snapBackward('2024-06-10', dates)).toBe('2024-06-06')
  })

  it('returns null before the first loaded bar', () => {
    expect(snapBackward('2024-06-01', dates)).toBeNull()
  })
})

describe('mapNotesToMarkers', () => {
  const bars = [
    makeBar({ trade_date: '2024-06-03' }),
    makeBar({ trade_date: '2024-06-04' }),
    makeBar({ trade_date: '2024-06-06' })
  ]

  it('places a single-date note anchored to a loaded bar', () => {
    const note = makeNote({ start_date: '2024-06-03', end_date: '2024-06-03' })
    const { markers, outsideRange } = mapNotesToMarkers([note], bars)
    expect(outsideRange).toEqual([])
    expect(markers).toEqual([
      {
        id: 'note-1',
        kind: 'note',
        barDate: '2024-06-03',
        start: '2024-06-03',
        end: '2024-06-03'
      }
    ])
  })

  it('snaps a single date FORWARD to the next bar, never back', () => {
    // 06-05 falls in the gap between the 06-04 and 06-06 bars.
    const note = makeNote({ start_date: '2024-06-05', end_date: '2024-06-05' })
    const { markers } = mapNotesToMarkers([note], bars)
    expect(markers[0]?.barDate).toBe('2024-06-06')
  })

  it('lists a note with no overlap with the loaded range separately', () => {
    const note = makeNote({
      id: 'note-2',
      start_date: '2020-01-01',
      end_date: '2020-01-02'
    })
    const { markers, outsideRange } = mapNotesToMarkers([note], bars)
    expect(markers).toEqual([])
    expect(outsideRange).toEqual([note])
  })

  it('draws a range note fully inside the loaded range, snapped inward', () => {
    const note = makeNote({ start_date: '2024-06-03', end_date: '2024-06-06' })
    const { markers, outsideRange } = mapNotesToMarkers([note], bars)
    expect(outsideRange).toEqual([])
    expect(markers).toEqual([
      {
        id: 'note-1',
        kind: 'note',
        barDate: '2024-06-03',
        start: '2024-06-03',
        end: '2024-06-06'
      }
    ])
  })

  it('draws a range note that starts before the loaded range but overlaps it, clamped', () => {
    const note = makeNote({ start_date: '2020-01-01', end_date: '2024-06-04' })
    const { markers, outsideRange } = mapNotesToMarkers([note], bars)
    expect(outsideRange).toEqual([])
    expect(markers).toEqual([
      {
        id: 'note-1',
        kind: 'note',
        barDate: '2024-06-03',
        start: '2024-06-03',
        end: '2024-06-04'
      }
    ])
  })

  it('draws a range note that ends after the loaded range but overlaps it, clamped', () => {
    const note = makeNote({ start_date: '2024-06-04', end_date: '2030-01-01' })
    const { markers, outsideRange } = mapNotesToMarkers([note], bars)
    expect(outsideRange).toEqual([])
    expect(markers).toEqual([
      {
        id: 'note-1',
        kind: 'note',
        barDate: '2024-06-04',
        start: '2024-06-04',
        end: '2024-06-06'
      }
    ])
  })
})

describe('mapEventsToMarkers', () => {
  const bars = [
    makeBar({ trade_date: '2024-06-03' }),
    makeBar({ trade_date: '2024-06-04' })
  ]

  it('places an event anchored to a loaded bar', () => {
    const event = makeEvent({ event_date: '2024-06-04' })
    const { markers, outsideRange } = mapEventsToMarkers([event], bars)
    expect(outsideRange).toEqual([])
    expect(markers).toEqual([
      {
        id: 'event-1',
        kind: 'event',
        barDate: '2024-06-04',
        start: '2024-06-04',
        end: '2024-06-04'
      }
    ])
  })

  it('snaps an event date FORWARD across a gap, never back', () => {
    const gapBars = [
      makeBar({ trade_date: '2024-06-03' }),
      makeBar({ trade_date: '2024-06-06' })
    ]
    const gapEvent = makeEvent({ event_date: '2024-06-04' })
    const { markers } = mapEventsToMarkers([gapEvent], gapBars)
    expect(markers[0]?.barDate).toBe('2024-06-06')
  })

  it('lists an event outside the loaded range separately', () => {
    const event = makeEvent({ id: 2, event_date: '2030-01-01' })
    const { markers, outsideRange } = mapEventsToMarkers([event], bars)
    expect(markers).toEqual([])
    expect(outsideRange).toEqual([event])
  })
})
