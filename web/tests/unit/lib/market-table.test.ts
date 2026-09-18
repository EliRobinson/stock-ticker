import { describe, expect, it } from 'vitest'
import type { Row } from '@tanstack/react-table'
import {
  defaultMarketFilterState,
  marketFilterStateToSearchParams,
  nullableDateStringSortingFn,
  numericStringSortingFn,
  parseMarketFilterState,
  searchFilterFn,
  sectorFilterFn
} from '@/lib/market-table'
import type { MarketRow } from '@/lib/api'

function makeRow(overrides: Partial<MarketRow>): Row<MarketRow> {
  const original: MarketRow = {
    symbol: 'AAPL',
    cik: '0000320193',
    name: 'Apple Inc.',
    sector: 'Technology',
    price: '190.00',
    observed_at: '2024-06-03T15:00:00.000Z',
    prev_close: '188.00',
    change: '2.00',
    change_pct: '1.06',
    volume: 1_000_000,
    market_cap: '2900000000000',
    market_cap_is_approx: false,
    first_bar_date: '2018-01-02',
    ...overrides
  }
  return {
    original,
    getValue: (columnId: string) => original[columnId as keyof MarketRow]
  } as unknown as Row<MarketRow>
}

const noopAddMeta = () => {}

describe('searchFilterFn', () => {
  it('matches on symbol', () => {
    expect(searchFilterFn(makeRow({}), 'symbol', 'aap', noopAddMeta)).toBe(true)
  })

  it('matches on company name', () => {
    expect(searchFilterFn(makeRow({}), 'symbol', 'apple', noopAddMeta)).toBe(
      true
    )
  })

  it('rejects a non-matching query', () => {
    expect(searchFilterFn(makeRow({}), 'symbol', 'msft', noopAddMeta)).toBe(
      false
    )
  })

  it('matches everything for an empty query', () => {
    expect(searchFilterFn(makeRow({}), 'symbol', '', noopAddMeta)).toBe(true)
  })

  it('is case-insensitive', () => {
    expect(searchFilterFn(makeRow({}), 'symbol', 'APPLE', noopAddMeta)).toBe(
      true
    )
  })
})

describe('sectorFilterFn', () => {
  const row = makeRow({ sector: 'Technology' })

  it('matches the exact sector', () => {
    expect(sectorFilterFn(row, 'sector', 'Technology', noopAddMeta)).toBe(true)
  })

  it('rejects a different sector', () => {
    expect(sectorFilterFn(row, 'sector', 'Healthcare', noopAddMeta)).toBe(false)
  })

  it('matches any sector in a multi-select', () => {
    expect(
      sectorFilterFn(row, 'sector', ['Healthcare', 'Technology'], noopAddMeta)
    ).toBe(true)
  })

  it('matches everything with no sector selected', () => {
    expect(sectorFilterFn(row, 'sector', [], noopAddMeta)).toBe(true)
  })
})

describe('numericStringSortingFn', () => {
  it('sorts ascending by numeric value of a decimal string column', () => {
    const rowA = makeRow({ symbol: 'A', price: '10' })
    const rowB = makeRow({ symbol: 'B', price: '2' })
    expect(numericStringSortingFn(rowA, rowB, 'price')).toBeGreaterThan(0)
  })

  it('sorts a null price after any priced row, in either direction', () => {
    const rowA = makeRow({ symbol: 'A', price: null })
    const rowB = makeRow({ symbol: 'B', price: '2' })
    expect(numericStringSortingFn(rowA, rowB, 'price')).toBeGreaterThan(0)
    expect(numericStringSortingFn(rowB, rowA, 'price')).toBeLessThan(0)
  })

  it('treats two nulls as equal', () => {
    const rowA = makeRow({ symbol: 'A', price: null })
    const rowB = makeRow({ symbol: 'B', price: null })
    expect(numericStringSortingFn(rowA, rowB, 'price')).toBe(0)
  })

  it('sorts an integer column (volume) numerically', () => {
    const rowA = makeRow({ symbol: 'A', volume: 100 })
    const rowB = makeRow({ symbol: 'B', volume: 9000 })
    expect(numericStringSortingFn(rowA, rowB, 'volume')).toBeLessThan(0)
  })
})

describe('nullableDateStringSortingFn', () => {
  it('sorts chronologically', () => {
    const rowA = makeRow({
      symbol: 'A',
      observed_at: '2024-06-03T15:00:00.000Z'
    })
    const rowB = makeRow({
      symbol: 'B',
      observed_at: '2024-06-04T15:00:00.000Z'
    })
    expect(nullableDateStringSortingFn(rowA, rowB, 'observed_at')).toBeLessThan(
      0
    )
  })

  it('sorts a never-quoted row after any quoted row, in either direction', () => {
    const rowA = makeRow({ symbol: 'A', observed_at: null })
    const rowB = makeRow({
      symbol: 'B',
      observed_at: '2024-06-03T15:00:00.000Z'
    })
    expect(
      nullableDateStringSortingFn(rowA, rowB, 'observed_at')
    ).toBeGreaterThan(0)
    expect(nullableDateStringSortingFn(rowB, rowA, 'observed_at')).toBeLessThan(
      0
    )
  })

  it('treats two nulls as equal', () => {
    const rowA = makeRow({ symbol: 'A', observed_at: null })
    const rowB = makeRow({ symbol: 'B', observed_at: null })
    expect(nullableDateStringSortingFn(rowA, rowB, 'observed_at')).toBe(0)
  })
})

describe('parseMarketFilterState', () => {
  it('parses q, sector, and an ascending sort', () => {
    const params = new URLSearchParams('q=apple&sector=Technology&sort=price')
    expect(parseMarketFilterState(params)).toEqual({
      q: 'apple',
      sector: 'Technology',
      sort: { id: 'price', desc: false }
    })
  })

  it('parses a descending sort prefixed with -', () => {
    const params = new URLSearchParams('sort=-market_cap')
    expect(parseMarketFilterState(params).sort).toEqual({
      id: 'market_cap',
      desc: true
    })
  })

  it('ignores a sort id that is not a known column', () => {
    const params = new URLSearchParams('sort=not_a_column')
    expect(parseMarketFilterState(params).sort).toBeNull()
  })

  it('defaults to the empty state', () => {
    expect(parseMarketFilterState(new URLSearchParams())).toEqual(
      defaultMarketFilterState
    )
  })

  it('accepts a plain record in place of URLSearchParams', () => {
    expect(parseMarketFilterState({ q: 'apple' })).toEqual({
      q: 'apple',
      sector: null,
      sort: null
    })
  })
})

describe('marketFilterStateToSearchParams', () => {
  it('round-trips through parseMarketFilterState', () => {
    const state = {
      q: 'apple',
      sector: 'Technology',
      sort: { id: 'price', desc: true }
    }
    const params = marketFilterStateToSearchParams(state)
    expect(params.toString()).toBe('q=apple&sector=Technology&sort=-price')
    expect(parseMarketFilterState(params)).toEqual(state)
  })

  it('omits empty fields', () => {
    expect(
      marketFilterStateToSearchParams(defaultMarketFilterState).toString()
    ).toBe('')
  })
})
