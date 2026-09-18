import { describe, expect, it } from 'vitest'
import {
  mapBarsToCandlestickSeries,
  mapBarsToVolumeSeries,
  mapEventsToMarkers,
  mapNotesToMarkers,
  snapToLoadedBar
} from '@/lib/chart-data'
import type { Bar, Event, Note } from '@/lib/api'

function makeBar(overrides: Partial<Bar>): Bar {
  return {
    trade_date: '2024-06-03',
    open: '100',
    high: '105',
    low: '99',
    close: '104',
    volume: 1_000_000,
    adj_close: '104',
    ...overrides
  }
}

function makeNote(overrides: Partial<Note>): Note {
  return {
    id: 'note-1',
    cik: '0000320193',
    start_date: '2024-06-03',
    end_date: '2024-06-03',
    body: 'Looks cheap here.',
    created_at: '2024-06-03T12:00:00.000Z',
    updated_at: '2024-06-03T12:00:00.000Z',
    ...overrides
  }
}

function makeEvent(overrides: Partial<Event>): Event {
  return {
    id: 1,
    cik: '0000320193',
    symbol: 'AAPL',
    event_date: '2024-06-03',
    kind: 'split',
    title: '4-for-1 split',
    details: {},
    source: 'sec',
    source_ref: 'ref-1',
    ...overrides
  }
}

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
})

describe('mapBarsToVolumeSeries', () => {
  it('marks the first bar flat and later bars by close direction', () => {
    const bars = [
      makeBar({ trade_date: '2024-06-03', close: '100', volume: 10 }),
      makeBar({ trade_date: '2024-06-04', close: '105', volume: 20 }),
      makeBar({ trade_date: '2024-06-05', close: '102', volume: 30 })
    ]
    expect(mapBarsToVolumeSeries(bars)).toEqual([
      { time: '2024-06-03', value: 10, direction: 'flat' },
      { time: '2024-06-04', value: 20, direction: 'up' },
      { time: '2024-06-05', value: 30, direction: 'down' }
    ])
  })
})

describe('snapToLoadedBar', () => {
  const dates = ['2024-06-03', '2024-06-04', '2024-06-06']

  it('returns null for an empty series', () => {
    expect(snapToLoadedBar('2024-06-03', [])).toBeNull()
  })

  it('returns the exact date when a bar exists', () => {
    expect(snapToLoadedBar('2024-06-04', dates)).toBe('2024-06-04')
  })

  it('snaps to the nearer neighbor across a gap', () => {
    // 06-05 is a weekend/holiday gap between 06-04 and 06-06; equidistant, so it prefers the earlier bar.
    expect(snapToLoadedBar('2024-06-05', dates)).toBe('2024-06-04')
  })

  it('returns null before the first loaded bar', () => {
    expect(snapToLoadedBar('2024-06-01', dates)).toBeNull()
  })

  it('returns null after the last loaded bar', () => {
    expect(snapToLoadedBar('2024-06-10', dates)).toBeNull()
  })
})

describe('mapNotesToMarkers', () => {
  const bars = [
    makeBar({ trade_date: '2024-06-03' }),
    makeBar({ trade_date: '2024-06-04' })
  ]

  it('places a note anchored to a loaded bar', () => {
    const note = makeNote({ start_date: '2024-06-03' })
    const { markers, outsideRange } = mapNotesToMarkers([note], bars)
    expect(outsideRange).toEqual([])
    expect(markers).toEqual([
      {
        id: 'note-1',
        kind: 'note',
        time: '2024-06-03',
        position: 'belowBar',
        shape: 'circle',
        text: 'Looks cheap here.'
      }
    ])
  })

  it('lists a note outside the loaded range separately', () => {
    const note = makeNote({ id: 'note-2', start_date: '2020-01-01' })
    const { markers, outsideRange } = mapNotesToMarkers([note], bars)
    expect(markers).toEqual([])
    expect(outsideRange).toEqual([note])
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
        id: '1',
        kind: 'event',
        time: '2024-06-04',
        position: 'aboveBar',
        shape: 'square',
        text: '4-for-1 split'
      }
    ])
  })

  it('lists an event outside the loaded range separately', () => {
    const event = makeEvent({ id: 2, event_date: '2030-01-01' })
    const { markers, outsideRange } = mapEventsToMarkers([event], bars)
    expect(markers).toEqual([])
    expect(outsideRange).toEqual([event])
  })
})
