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
  SortingState,
  VisibilityState
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'

import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'
import { formatMarketCap, formatVolume } from '@/lib/format'
import { marketColumns, searchFilterFn } from '@/lib/market-table'
import { cn } from '@/lib/utils'

import {
  ChangeCell,
  ExplainedDash,
  QuoteCell,
  TruncatedText
} from '../shared/cells'
import { sharedCopy } from '../shared/copy'
import { SkeletonBar } from '../shared/feedback'
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

export interface Labels {
  price: string
  age: string
  widePrice?: boolean
  compact?: boolean
}

interface ColumnMeta {
  width?: number
  align?: 'right'
  className?: string
  skeleton: string
}

type Cell = NonNullable<ColumnDef<MarketRowView>['cell']>

interface ColumnDisplay {
  header: string
  meta: ColumnMeta
  cell: Cell
  invertSorting?: boolean
}

function MarketCapValue({ row }: { row: MarketRowView }) {
  if (row.backfillPending) return <SkeletonBar className='w-13.5 ml-auto' />
  if (row.capNote)
    return <ExplainedDash reason={row.capNote} focusable={false} />
  if (!row.market_cap_is_approx) return <>{formatMarketCap(row.market_cap)}</>
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className='cursor-help'>
          <span aria-hidden='true'>{'≈'}</span>
          {formatMarketCap(row.market_cap)}
          <span className='sr-only'>{sharedCopy.capApprox}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className='max-w-[28ch]'>
        {sharedCopy.capApprox}
      </TooltipContent>
    </Tooltip>
  )
}

function display(labels: Labels): Record<MarketColumnId, ColumnDisplay> {
  return {
    symbol: {
      header: copy.columnLabels.symbol,
      meta: { width: labels.compact ? 66 : 84, skeleton: 'w-11' },
      cell: ({ row }) => (
        <span className='font-bold'>{row.original.symbol}</span>
      )
    },
    name: {
      header: copy.columnLabels.name,
      meta: { className: 'max-w-70', skeleton: 'w-47.5' },
      cell: ({ row }) => <TruncatedText text={row.original.name} />
    },
    sector: {
      header: copy.columnLabels.sector,
      meta: {
        width: 180,
        className: 'text-sm text-muted-foreground',
        skeleton: 'w-32'
      },
      cell: ({ row }) => (
        <span className='block truncate'>{row.original.sector}</span>
      )
    },
    price: {
      header: labels.price,
      meta: {
        width: labels.compact ? 84 : labels.widePrice ? 150 : 104,
        align: 'right',
        skeleton: 'w-13.5'
      },
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
      meta: {
        width: labels.compact ? undefined : 176,
        align: 'right',
        className: labels.compact ? 'text-xs' : undefined,
        skeleton: 'w-24'
      },
      cell: ({ row }) => {
        const r = row.original
        if (r.backfillPending) return <SkeletonBar className='w-23 ml-auto' />
        if (r.historyNote)
          return <ExplainedDash reason={r.historyNote} focusable={false} />
        return <ChangeCell pct={r.change_pct} abs={r.change} stale={r.stale} />
      }
    },
    market_cap: {
      header: copy.columnLabels.marketCap,
      meta: { width: 104, align: 'right', skeleton: 'w-14' },
      cell: ({ row }) => <MarketCapValue row={row.original} />
    },
    volume: {
      header: copy.columnLabels.volume,
      meta: {
        width: 92,
        align: 'right',
        className: 'text-muted-foreground',
        skeleton: 'w-12'
      },
      cell: ({ row }) => formatVolume(row.original.volume)
    },
    observed_at: {
      header: labels.age,
      meta: {
        width: 84,
        align: 'right',
        className: 'text-xs text-muted-foreground',
        skeleton: 'w-8'
      },
      cell: ({ row }) => row.original.ageLabel,
      // The column sorts by observed_at; youngest-first reads as "age ascending".
      invertSorting: true
    }
  }
}

// lib/market-table owns ids, accessors, sort and filter; this adds headers and
// cells. The separate `change` column is dropped: the design shows percent
// and dollar change in one cell.
function columns(labels: Labels): ColumnDef<MarketRowView>[] {
  const byId = display(labels)
  const defs = marketColumns<MarketRowView>()
  return (Object.keys(byId) as MarketColumnId[]).flatMap((id) => {
    const def = defs.find((c) => c.id === id)
    const d = byId[id]
    return def
      ? [
          {
            ...def,
            header: d.header,
            cell: d.cell,
            meta: d.meta,
            invertSorting: d.invertSorting
          }
        ]
      : []
  })
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
    globalFilterFn: searchFilterFn<MarketRowView>,
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
  // Roving tabindex: the table is one tab stop; arrows move between rows.
  const [active, setActive] = useState(0)
  const activeIndex = Math.min(active, Math.max(0, modelRows.length - 1))
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
    setActive(clamped)
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
    const moves: Record<string, number> = {
      ArrowDown: index + 1,
      ArrowUp: index - 1,
      Home: 0,
      End: modelRows.length - 1,
      PageDown: index + 10,
      PageUp: index - 10
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onOpen(row.original)
    } else if (e.key in moves) {
      e.preventDefault()
      focusRow(moves[e.key]!)
    }
  }

  return (
    <div
      ref={scrollRef}
      role='region'
      aria-label={copy.tableLabel}
      className={cn(
        'border-border min-h-0 flex-1 overflow-auto border-t',
        className
      )}
    >
      <table
        className='text-md tabular w-full table-fixed border-collapse'
        aria-rowcount={loading ? -1 : modelRows.length + 1}
      >
        <TableHeader className='bg-background sticky top-0 z-10'>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} aria-rowindex={1}>
              {group.headers.map((header) => {
                const meta = header.column.columnDef.meta as ColumnMeta
                const sorted = header.column.getIsSorted()
                return (
                  <TableHead
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
                      'p-0',
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
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {padTop > 0 && (
            <tr aria-hidden='true'>
              <td style={{ height: padTop }} colSpan={visibleColumns.length} />
            </tr>
          )}
          {loading
            ? items.map((item) => (
                <TableRow
                  key={item.key}
                  className='hover:bg-transparent'
                  style={{ height: ROW_HEIGHT }}
                >
                  {visibleColumns.map((col) => {
                    const meta = col.columnDef.meta as ColumnMeta
                    return (
                      <TableCell key={col.id}>
                        <SkeletonBar
                          className={cn(
                            'max-w-full',
                            meta.skeleton,
                            meta.align === 'right' && 'ml-auto'
                          )}
                        />
                      </TableCell>
                    )
                  })}
                </TableRow>
              ))
            : items.map((item) => {
                const row = modelRows[item.index]
                if (!row) return null
                return (
                  <TableRow
                    key={row.id}
                    data-index={item.index}
                    aria-rowindex={item.index + 2}
                    tabIndex={item.index === activeIndex ? 0 : -1}
                    onClick={() => onOpen(row.original)}
                    onMouseEnter={() => onHover?.(row.original)}
                    onFocus={() => {
                      setActive(item.index)
                      onHover?.(row.original)
                    }}
                    onKeyDown={(e) => onRowKey(e, item.index)}
                    className='focus-visible:outline-ring cursor-pointer focus-visible:outline-2 focus-visible:-outline-offset-2'
                    style={{ height: ROW_HEIGHT }}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const meta = cell.column.columnDef.meta as ColumnMeta
                      return (
                        <TableCell
                          key={cell.id}
                          className={cn(
                            'overflow-hidden',
                            meta.align === 'right' && 'text-right',
                            meta.className
                          )}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
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
        </TableBody>
      </table>
    </div>
  )
}
