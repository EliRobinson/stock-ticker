import type { ColumnDef, FilterFn } from '@tanstack/react-table'
import { toNumber } from './format'
import type { MarketRow } from './api'

/** Generic over any row that extends MarketRow, so a screen's own row view
 * model (MarketRow plus display fields) uses these without a cast. */
export function searchFilterFn<T extends MarketRow>(
  ...[row, , filterValue]: Parameters<FilterFn<T>>
): boolean {
  const query = String(filterValue ?? '')
    .trim()
    .toLowerCase()
  if (query === '') return true
  const { symbol, name } = row.original
  return (
    symbol.toLowerCase().includes(query) || name.toLowerCase().includes(query)
  )
}

export function sectorFilterFn<T extends MarketRow>(
  ...[row, , filterValue]: Parameters<FilterFn<T>>
): boolean {
  const sectors: string[] = Array.isArray(filterValue)
    ? filterValue
    : [String(filterValue ?? '')]
  const active = sectors.filter((s) => s !== '')
  if (active.length === 0) return true
  return active.includes(row.original.sector)
}

function numericColumn<T extends MarketRow>(
  id: keyof MarketRow,
  header: string
): ColumnDef<T> {
  return {
    id,
    // TanStack's `sortUndefined: 'last'` handles the null-before-Quote
    // case in one place, for both sort directions - a hand-written
    // comparator returning a fixed +1/-1 gets its sign flipped by the
    // table for a descending sort, which put nulls FIRST instead of last
    // (see #8 review). accessorFn (not accessorKey) is what lets
    // `sortUndefined` see `undefined` instead of `null`, which is the only
    // value it recognizes.
    accessorFn: (row) =>
      toNumber(row[id] as string | number | null) ?? undefined,
    header,
    sortUndefined: 'last'
  }
}

export function marketColumns<T extends MarketRow>(): ColumnDef<T>[] {
  return [
    {
      id: 'symbol',
      accessorKey: 'symbol',
      header: 'Ticker',
      filterFn: searchFilterFn<T>
    },
    {
      id: 'name',
      accessorKey: 'name',
      header: 'Company',
      filterFn: searchFilterFn<T>
    },
    {
      id: 'sector',
      accessorKey: 'sector',
      header: 'Sector',
      filterFn: sectorFilterFn<T>
    },
    numericColumn<T>('price', 'Price'),
    numericColumn<T>('change', 'Change'),
    numericColumn<T>('change_pct', 'Change %'),
    numericColumn<T>('volume', 'Volume'),
    {
      id: 'observed_at',
      // Sorts by recency; age itself depends on the parent /market
      // response's server_time, which isn't on MarketRow, so it stays a
      // sortable timestamp column rather than a synthesized "age" one.
      accessorFn: (row) => row.observed_at ?? undefined,
      header: 'Last Quote',
      sortUndefined: 'last'
    },
    numericColumn<T>('market_cap', 'Market Cap')
  ]
}

export const marketTableColumns: ColumnDef<MarketRow>[] = marketColumns()

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

/** Matches both `URLSearchParams` and Next.js's `ReadonlyURLSearchParams`
 * (from `useSearchParams()`) - either one already has `.get()`, so there's
 * no need to special-case a plain object as a second input shape. */
export interface SearchParamsLike {
  get(key: string): string | null
}

export function parseMarketFilterState(
  searchParams: SearchParamsLike
): MarketFilterState {
  const q = searchParams.get('q') ?? ''
  const sector = searchParams.get('sector')
  const sortParam = searchParams.get('sort')

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
