'use client'

import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable
} from '@tanstack/react-table'
import type {
  ColumnDef,
  FilterFn,
  SortingState,
  VisibilityState
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { useMemo, useRef } from 'react'
import type { KeyboardEvent } from 'react'

import { marketTableColumns, searchFilterFn } from '@/lib/market-table'
import { cn } from '@/lib/utils'

import {
  ChangeCell,
  ExplainedDash,
  QuoteCell,
  TruncatedText
} from '../shared/cells'
import { SkeletonBar } from '../shared/feedback'
import { formatMarketCap, formatVolume } from '../shared/format'
import { marketCopy as copy } from './copy'
import type { MarketRowView } from './market-rows'

export const ROW_HEIGHT = 33

export type MarketColumnId =
  | 'symbol'
  | 'name'
  | 'sector'
  | 'price'
  | 'change_pct'
  | 'market_cap'
  | 'volume'
  | 'observed_at'

export type Labels = { price: string; age: string; widePrice?: boolean }

type Cell = NonNullable<ColumnDef<MarketRowView>['cell']>

interface ColumnDisplay {
  header: string
  meta: ColumnMeta
  cell: Cell
}

function display(labels: Labels): Record<MarketColumnId, ColumnDisplay> {
  return {
    symbol: {
      header: copy.columnLabels.symbol,
      meta: { width: 84 },
      cell: ({ row }) => (
        <span className='font-bold'>{row.original.symbol}</span>
      )
    },
    name: {
      header: copy.columnLabels.name,
      meta: { className: 'max-w-70' },
      cell: ({ row }) => <TruncatedText text={row.original.name} />
    },
    sector: {
      header: copy.columnLabels.sector,
      meta: { width: 180, className: 'text-sm text-muted-foreground' },
      cell: ({ row }) => (
        <span className='block truncate'>{row.original.sector}</span>
      )
    },
    price: {
      header: labels.price,
      meta: { width: labels.widePrice ? 150 : 104, align: 'right' },
      cell: ({ row }) => (
        <QuoteCell
          price={row.original.price}
          ageMs={row.original.ageMs}
          state={
            row.original.stale
              ? 'stale'
              : row.original.closed
                ? 'closed'
                : 'fresh'
          }
        />
      )
    },
    change_pct: {
      header: copy.columnLabels.change,
      meta: { width: 176, align: 'right' },
      cell: ({ row }) => {
        const r = row.original
        if (r.backfillPending) return <SkeletonBar className='w-23 ml-auto' />
        if (r.historyNote) return <ExplainedDash reason={r.historyNote} />
        return <ChangeCell pct={r.change_pct} abs={r.change} stale={r.stale} />
      }
    },
    market_cap: {
      header: copy.columnLabels.marketCap,
      meta: { width: 104, align: 'right' },
      cell: ({ row }) => {
        const r = row.original
        if (r.backfillPending) return <SkeletonBar className='w-13.5 ml-auto' />
        if (r.capNote) return <ExplainedDash reason={r.capNote} />
        return formatMarketCap(r.market_cap)
      }
    },
    volume: {
      header: copy.columnLabels.volume,
      meta: { width: 92, align: 'right', className: 'text-muted-foreground' },
      cell: ({ row }) => formatVolume(row.original.volume)
    },
    observed_at: {
      header: labels.age,
      meta: {
        width: 84,
        align: 'right',
        className: 'text-xs text-muted-foreground'
      },
      cell: ({ row }) => row.original.ageLabel
    }
  }
}

// #8 owns the column defs (ids, accessors, sort and filter fns); this layer
// only adds headers and cells, and drops the separate `change` column because
// the design shows percent and dollar change in one cell.
function columns(labels: Labels): ColumnDef<MarketRowView>[] {
  const byId = display(labels)
  const defs = marketTableColumns as unknown as ColumnDef<MarketRowView>[]
  return (Object.keys(byId) as MarketColumnId[]).flatMap((id) => {
    const def = defs.find((c) => c.id === id)
    const d = byId[id]
    return def ? [{ ...def, header: d.header, cell: d.cell, meta: d.meta }] : []
  })
}

interface ColumnMeta {
  width?: number
  align?: 'right'
  className?: string
}

export interface MarketTableInput {
  rows: MarketRowView[]
  query: string
  sector: string | null
  sorting: SortingState
  onSortingChange: (sorting: SortingState) => void
  columnVisibility: VisibilityState
  labels: Labels
}

export type MarketTableModel = ReturnType<typeof useMarketTable>

export function useMarketTable({
  rows,
  query,
  sector,
  sorting,
  onSortingChange,
  columnVisibility,
  labels
}: MarketTableInput) {
  const defs = useMemo(() => columns(labels), [labels])
  const columnFilters = useMemo(
    () => (sector ? [{ id: 'sector', value: sector }] : []),
    [sector]
  )
  return useReactTable({
    data: rows,
    columns: defs,
    state: { sorting, globalFilter: query, columnFilters, columnVisibility },
    onSortingChange: (updater) =>
      onSortingChange(
        typeof updater === 'function' ? updater(sorting) : updater
      ),
    globalFilterFn: searchFilterFn as unknown as FilterFn<MarketRowView>,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (r) => r.symbol
  })
}

export function MarketTable({
  table,
  loading = false,
  onOpen,
  onHover,
  className
}: {
  table: MarketTableModel
  loading?: boolean
  onOpen: (row: MarketRowView) => void
  onHover?: (row: MarketRowView) => void
  className?: string
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const modelRows = table.getRowModel().rows
  const virtualizer = useVirtualizer({
    count: loading ? 20 : modelRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    initialRect: { width: 1200, height: 24 * ROW_HEIGHT }
  })
  const items = virtualizer.getVirtualItems()
  const padTop = items[0]?.start ?? 0
  const padBottom =
    virtualizer.getTotalSize() - (items[items.length - 1]?.end ?? 0)
  const visibleColumns = table.getVisibleLeafColumns()

  const focusRow = (index: number) => {
    const clamped = Math.max(0, Math.min(modelRows.length - 1, index))
    virtualizer.scrollToIndex(clamped, { align: 'auto' })
    requestAnimationFrame(() => {
      scrollRef.current
        ?.querySelector<HTMLElement>(`[data-index="${clamped}"]`)
        ?.focus()
    })
  }

  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, index: number) => {
    const row = modelRows[index]
    if (!row) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onOpen(row.original)
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      focusRow(index + 1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      focusRow(index - 1)
    }
  }

  return (
    <div
      ref={scrollRef}
      role='region'
      aria-label={copy.tableLabel}
      tabIndex={-1}
      className={cn(
        'border-border min-h-0 flex-1 overflow-auto border-t',
        className
      )}
    >
      <table
        className='text-md tabular w-full table-fixed border-collapse'
        aria-rowcount={loading ? -1 : modelRows.length + 1}
      >
        <thead className='bg-background sticky top-0 z-10'>
          {table.getHeaderGroups().map((group) => (
            <tr
              key={group.id}
              aria-rowindex={1}
              className='border-border border-b'
            >
              {group.headers.map((header) => {
                const meta = (header.column.columnDef.meta ?? {}) as ColumnMeta
                const sorted = header.column.getIsSorted()
                return (
                  <th
                    key={header.id}
                    scope='col'
                    aria-sort={
                      sorted === 'asc'
                        ? 'ascending'
                        : sorted === 'desc'
                          ? 'descending'
                          : 'none'
                    }
                    style={meta.width ? { width: meta.width } : undefined}
                    className={cn(
                      'text-muted-foreground text-2xs p-0 font-normal uppercase tracking-[0.08em]',
                      meta.align === 'right' ? 'text-right' : 'text-left'
                    )}
                  >
                    <button
                      type='button'
                      onClick={header.column.getToggleSortingHandler()}
                      className={cn(
                        'hover:text-foreground focus-visible:outline-ring inline-flex min-h-7 w-full items-center gap-1 whitespace-nowrap p-[6.8px] uppercase focus-visible:outline-2 focus-visible:-outline-offset-2',
                        meta.align === 'right' && 'justify-end'
                      )}
                    >
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                      {sorted === 'asc' && (
                        <ArrowUp
                          aria-hidden='true'
                          className='size-3.5'
                          strokeWidth={1.5}
                        />
                      )}
                      {sorted === 'desc' && (
                        <ArrowDown
                          aria-hidden='true'
                          className='size-3.5'
                          strokeWidth={1.5}
                        />
                      )}
                    </button>
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {padTop > 0 && (
            <tr aria-hidden='true'>
              <td style={{ height: padTop }} colSpan={visibleColumns.length} />
            </tr>
          )}
          {loading
            ? items.map((item) => (
                <tr
                  key={item.key}
                  className='border-rowline border-b'
                  style={{ height: ROW_HEIGHT }}
                >
                  {visibleColumns.map((col) => {
                    const meta = (col.columnDef.meta ?? {}) as ColumnMeta
                    const widths: Record<string, string> = {
                      symbol: 'w-11',
                      name: 'w-47.5',
                      sector: 'w-32',
                      price: 'w-13.5',
                      change_pct: 'w-24',
                      market_cap: 'w-14',
                      volume: 'w-12',
                      observed_at: 'w-8'
                    }
                    return (
                      <td key={col.id} className='p-[6.8px]'>
                        <SkeletonBar
                          className={cn(
                            'max-w-full',
                            widths[col.id],
                            meta.align === 'right' && 'ml-auto'
                          )}
                        />
                      </td>
                    )
                  })}
                </tr>
              ))
            : items.map((item) => {
                const row = modelRows[item.index]
                if (!row) return null
                return (
                  <tr
                    key={row.id}
                    data-index={item.index}
                    aria-rowindex={item.index + 2}
                    tabIndex={0}
                    onClick={() => onOpen(row.original)}
                    onMouseEnter={() => onHover?.(row.original)}
                    onFocus={() => onHover?.(row.original)}
                    onKeyDown={(e) => onRowKey(e, item.index)}
                    className='border-rowline hover:bg-hover focus-visible:outline-ring cursor-pointer border-b focus-visible:outline-2 focus-visible:-outline-offset-2'
                    style={{ height: ROW_HEIGHT }}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const meta = (cell.column.columnDef.meta ??
                        {}) as ColumnMeta
                      return (
                        <td
                          key={cell.id}
                          className={cn(
                            'overflow-hidden whitespace-nowrap p-[6.8px]',
                            meta.align === 'right' && 'text-right',
                            meta.className
                          )}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
          {padBottom > 0 && (
            <tr aria-hidden='true'>
              <td
                style={{ height: padBottom }}
                colSpan={visibleColumns.length}
              />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
