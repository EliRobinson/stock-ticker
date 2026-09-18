import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useState } from 'react'
import {
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type Row,
  type SortingState
} from '@tanstack/react-table'
import {
  defaultMarketFilterState,
  marketFilterStateToSearchParams,
  marketTableColumns,
  parseMarketFilterState,
  searchFilterFn,
  sectorFilterFn
} from '@/lib/market-table'
import type { MarketRow } from '@/lib/api'

function makeRow(overrides: Partial<MarketRow>): MarketRow {
  return {
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
    backfill_completed_at: '2018-01-02',
    is_primary: true,
    ...overrides
  }
}

function makeFilterRow(overrides: Partial<MarketRow>): Row<MarketRow> {
  const original = makeRow(overrides)
  return {
    original,
    getValue: (columnId: string) => original[columnId as keyof MarketRow]
  } as unknown as Row<MarketRow>
}

const noopAddMeta = () => {}

describe('searchFilterFn', () => {
  it('matches on symbol', () => {
    expect(
      searchFilterFn(makeFilterRow({}), 'symbol', 'aap', noopAddMeta)
    ).toBe(true)
  })

  it('matches on company name', () => {
    expect(
      searchFilterFn(makeFilterRow({}), 'symbol', 'apple', noopAddMeta)
    ).toBe(true)
  })

  it('rejects a non-matching query', () => {
    expect(
      searchFilterFn(makeFilterRow({}), 'symbol', 'msft', noopAddMeta)
    ).toBe(false)
  })

  it('matches everything for an empty query', () => {
    expect(searchFilterFn(makeFilterRow({}), 'symbol', '', noopAddMeta)).toBe(
      true
    )
  })

  it('is case-insensitive', () => {
    expect(
      searchFilterFn(makeFilterRow({}), 'symbol', 'APPLE', noopAddMeta)
    ).toBe(true)
  })
})

describe('sectorFilterFn', () => {
  const row = makeFilterRow({ sector: 'Technology' })

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

function useSortedTestTable(data: MarketRow[], initialSorting: SortingState) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting)
  return useReactTable({
    data,
    columns: marketTableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel()
  })
}

function sortedSymbols(rows: { original: MarketRow }[]): string[] {
  return rows.map((row) => row.original.symbol)
}

describe('marketTableColumns sorting (via getSortedRowModel)', () => {
  it('sorts a null price last when ascending', () => {
    const data = [
      makeRow({ symbol: 'A', price: null }),
      makeRow({ symbol: 'B', price: '50' }),
      makeRow({ symbol: 'C', price: '10' })
    ]
    const { result } = renderHook(() =>
      useSortedTestTable(data, [{ id: 'price', desc: false }])
    )
    expect(sortedSymbols(result.current.getSortedRowModel().rows)).toEqual([
      'C',
      'B',
      'A'
    ])
  })

  it('sorts a null price last when descending too - not first', () => {
    const data = [
      makeRow({ symbol: 'A', price: null }),
      makeRow({ symbol: 'B', price: '50' }),
      makeRow({ symbol: 'C', price: '10' })
    ]
    const { result } = renderHook(() =>
      useSortedTestTable(data, [{ id: 'price', desc: true }])
    )
    expect(sortedSymbols(result.current.getSortedRowModel().rows)).toEqual([
      'B',
      'C',
      'A'
    ])
  })

  it('sorts volume (an integer column) numerically', () => {
    const data = [
      makeRow({ symbol: 'A', volume: 9000 }),
      makeRow({ symbol: 'B', volume: 100 })
    ]
    const { result } = renderHook(() =>
      useSortedTestTable(data, [{ id: 'volume', desc: false }])
    )
    expect(sortedSymbols(result.current.getSortedRowModel().rows)).toEqual([
      'B',
      'A'
    ])
  })

  it('sorts a never-quoted row (observed_at null) last in both directions', () => {
    const data = [
      makeRow({ symbol: 'A', observed_at: null }),
      makeRow({ symbol: 'B', observed_at: '2024-06-04T00:00:00.000Z' })
    ]
    const asc = renderHook(() =>
      useSortedTestTable(data, [{ id: 'observed_at', desc: false }])
    )
    expect(sortedSymbols(asc.result.current.getSortedRowModel().rows)).toEqual([
      'B',
      'A'
    ])
    const desc = renderHook(() =>
      useSortedTestTable(data, [{ id: 'observed_at', desc: true }])
    )
    expect(sortedSymbols(desc.result.current.getSortedRowModel().rows)).toEqual(
      ['B', 'A']
    )
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

  it('accepts anything structurally shaped like URLSearchParams', () => {
    const fakeSearchParams = {
      get: (key: string) => (key === 'q' ? 'apple' : null)
    }
    expect(parseMarketFilterState(fakeSearchParams)).toEqual({
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
