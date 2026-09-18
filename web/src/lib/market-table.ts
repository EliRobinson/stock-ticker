import type { ColumnDef, FilterFn, SortingFn } from '@tanstack/react-table'
import type { MarketRow } from './api'

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

/**
 * Numeric columns (`price`, `change`, `market_cap`, ...) arrive as decimal
 * strings, and can be null before a Listing has a Quote. Nulls sort last
 * regardless of sort direction, so an unpriced row never jumps to the top
 * of a descending sort.
 */
export const numericStringSortingFn: SortingFn<MarketRow> = (
  rowA,
  rowB,
  columnId
) => {
  const a = toNumber(rowA.getValue<string | number | null>(columnId))
  const b = toNumber(rowB.getValue<string | number | null>(columnId))
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return a - b
}

export const searchFilterFn: FilterFn<MarketRow> = (
  row,
  _columnId,
  filterValue: string
) => {
  const query = filterValue.trim().toLowerCase()
  if (query === '') return true
  const { symbol, name } = row.original
  return (
    symbol.toLowerCase().includes(query) || name.toLowerCase().includes(query)
  )
}

/**
 * `observed_at` sorts last-priced-first by default (nulls, meaning never
 * quoted, sort last in either direction) so the UI can offer "sort by
 * staleness" without a separate age column - age itself depends on the
 * parent /market response's server_time, which isn't on MarketRow.
 */
export const nullableDateStringSortingFn: SortingFn<MarketRow> = (
  rowA,
  rowB,
  columnId
) => {
  const a = rowA.getValue<string | null>(columnId)
  const b = rowB.getValue<string | null>(columnId)
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return a < b ? -1 : a > b ? 1 : 0
}

export const sectorFilterFn: FilterFn<MarketRow> = (
  row,
  _columnId,
  filterValue: string | string[]
) => {
  const sectors = Array.isArray(filterValue) ? filterValue : [filterValue]
  const active = sectors.filter((s) => s !== '')
  if (active.length === 0) return true
  return active.includes(row.original.sector)
}

export const marketTableColumns: ColumnDef<MarketRow>[] = [
  {
    id: 'symbol',
    accessorKey: 'symbol',
    header: 'Symbol',
    filterFn: searchFilterFn
  },
  {
    id: 'name',
    accessorKey: 'name',
    header: 'Company',
    filterFn: searchFilterFn
  },
  {
    id: 'sector',
    accessorKey: 'sector',
    header: 'Sector',
    filterFn: sectorFilterFn
  },
  {
    id: 'price',
    accessorKey: 'price',
    header: 'Price',
    sortingFn: numericStringSortingFn
  },
  {
    id: 'change',
    accessorKey: 'change',
    header: 'Change',
    sortingFn: numericStringSortingFn
  },
  {
    id: 'change_pct',
    accessorKey: 'change_pct',
    header: 'Change %',
    sortingFn: numericStringSortingFn
  },
  {
    id: 'volume',
    accessorKey: 'volume',
    header: 'Volume',
    sortingFn: numericStringSortingFn
  },
  {
    id: 'observed_at',
    accessorKey: 'observed_at',
    header: 'Quote time',
    sortingFn: nullableDateStringSortingFn
  },
  {
    id: 'market_cap',
    accessorKey: 'market_cap',
    header: 'Market Cap',
    sortingFn: numericStringSortingFn
  }
]

export const marketSortableColumnIds = new Set(
  marketTableColumns
    .map((column) => column.id)
    .filter((id): id is string => Boolean(id))
)

export interface MarketFilterState {
  q: string
  sector: string | null
  sort: { id: string; desc: boolean } | null
}

export const defaultMarketFilterState: MarketFilterState = {
  q: '',
  sector: null,
  sort: null
}

export function parseMarketFilterState(
  searchParams: URLSearchParams | Record<string, string | undefined>
): MarketFilterState {
  const get = (key: string): string | null => {
    if (searchParams instanceof URLSearchParams) return searchParams.get(key)
    return searchParams[key] ?? null
  }

  const q = get('q') ?? ''
  const sector = get('sector')
  const sortParam = get('sort')

  let sort: MarketFilterState['sort'] = null
  if (sortParam) {
    const desc = sortParam.startsWith('-')
    const id = desc ? sortParam.slice(1) : sortParam
    if (marketSortableColumnIds.has(id)) {
      sort = { id, desc }
    }
  }

  return { q, sector: sector && sector !== '' ? sector : null, sort }
}

export function marketFilterStateToSearchParams(
  state: MarketFilterState
): URLSearchParams {
  const params = new URLSearchParams()
  if (state.q !== '') params.set('q', state.q)
  if (state.sector) params.set('sector', state.sector)
  if (state.sort)
    params.set('sort', `${state.sort.desc ? '-' : ''}${state.sort.id}`)
  return params
}
