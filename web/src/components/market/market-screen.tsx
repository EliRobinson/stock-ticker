'use client'

import type { SortingState, VisibilityState } from '@tanstack/react-table'
import { EllipsisVertical, Search, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import type { MarketResponse } from '@/lib/api'
import { formatDateShort, formatTimeET } from '@/lib/format'
import { cn } from '@/lib/utils'

import { sharedCopy } from '../shared/copy'
import { EmptyState, StatusAlert } from '../shared/feedback'
import { useDraft } from '../shared/use-draft'
import {
  TOUCH_PHONE,
  useElementWidth,
  useMediaQuery
} from '../shared/use-media'
import { marketCopy as copy } from './copy'
import { MarketList } from './market-list'
import { SECTORS, toRowViews } from './market-rows'
import type { MarketRowView } from './market-rows'
import { MarketTable, useMarketTable } from './market-table'
import type { MarketColumnId } from './market-table'

export type QuotesProblem =
  | { kind: 'api-down'; lastUpdated: string | null }
  | { kind: 'missing-key' }
  | null

export interface MarketScreenProps {
  market: MarketResponse | null
  loading?: boolean
  quotesProblem?: QuotesProblem
  query: string
  onQueryChange: (query: string) => void
  sector: string | null
  onSectorChange: (sector: string | null) => void
  sorting: SortingState
  onSortingChange: (sorting: SortingState) => void
  onOpenCompany: (row: MarketRowView) => void
  onPrefetchCompany?: (row: MarketRowView) => void
  className?: string
}

const ALL_SECTORS = '__all__'

const MENU_COLUMNS: { id: MarketColumnId; label: string }[] = [
  { id: 'name', label: copy.columnLabels.name },
  { id: 'sector', label: copy.columnLabels.sector },
  { id: 'market_cap', label: copy.columnLabels.marketCap },
  { id: 'volume', label: copy.columnLabels.volume },
  { id: 'observed_at', label: copy.columnLabels.age }
]

// Container width decides which optional columns show (design R1, G3, M11).
// The same widths are named container sizes in app/globals.css
// (--container-compact is 520px); keep the two in step.
function autoVisibility(width: number): VisibilityState {
  return {
    sector: width >= 1100,
    volume: width >= 1100,
    market_cap: width >= 860,
    name: width >= 520,
    observed_at: width >= 520
  }
}

export function MarketScreen({
  market,
  loading = false,
  quotesProblem = null,
  query,
  onQueryChange,
  sector,
  onSectorChange,
  sorting,
  onSortingChange,
  onOpenCompany,
  onPrefetchCompany,
  className
}: MarketScreenProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const width = useElementWidth(rootRef)
  const touch = useMediaQuery(TOUCH_PHONE)
  const [userColumns, setUserColumns] = useState<VisibilityState>({})

  const [draft, typeQuery] = useDraft(query, onQueryChange)

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const typing =
        target?.closest('input, textarea, [contenteditable="true"]') != null
      if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const rows = useMemo(
    () =>
      market
        ? toRowViews(market, { forceStale: quotesProblem?.kind === 'api-down' })
        : [],
    [market, quotesProblem]
  )
  const columnVisibility: VisibilityState = useMemo(
    () => ({ ...autoVisibility(width), ...userColumns, change: false }),
    [width, userColumns]
  )
  const anyStale = rows.some((r) => r.stale)
  const compact = width < 520
  const narrow = width < 560
  const closed = market != null && !market.market_clock?.is_open
  const labels = useMemo(
    () => ({
      compact,
      ...(quotesProblem?.kind === 'api-down'
        ? {
            price: copy.columnLabels.priceStale,
            age: copy.columnLabels.age,
            widePrice: true
          }
        : closed
          ? {
              price: copy.columnLabels.priceClosed,
              age: copy.columnLabels.ageClosed
            }
          : {
              price: copy.columnLabels.price,
              age: copy.columnLabels.age,
              widePrice: anyStale
            })
    }),
    [quotesProblem, closed, anyStale, compact]
  )

  const table = useMarketTable({
    rows,
    query: draft,
    sector,
    sorting,
    onSortingChange,
    columnVisibility,
    labels
  })
  const shown = table.getRowModel().rows.length
  const total = rows.length
  const firstRun =
    !loading &&
    market != null &&
    total === 0 &&
    quotesProblem?.kind !== 'missing-key'
  const noMatches = !loading && total > 0 && shown === 0

  const clearFilters = () => {
    typeQuery('')
    onSectorChange(null)
  }

  const sectorSelect = (
    <Select
      value={sector ?? ALL_SECTORS}
      onValueChange={(v) => onSectorChange(v === ALL_SECTORS ? null : v)}
    >
      <SelectTrigger aria-label={copy.sectorLabel} className='w-47.5'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL_SECTORS}>{copy.allSectors}</SelectItem>
        {SECTORS.map((s) => (
          <SelectItem key={s} value={s}>
            {s}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  return (
    <div
      ref={rootRef}
      className={cn('flex h-full min-h-0 flex-col', className)}
    >
      <div
        className={cn(
          'flex flex-wrap items-center gap-2.5 px-4 py-3',
          narrow && 'px-2.5 py-2'
        )}
      >
        <div
          className={cn('w-70 relative max-w-full', narrow && 'min-w-0 flex-1')}
        >
          <Search
            aria-hidden='true'
            strokeWidth={1.5}
            className='text-muted-foreground pointer-events-none absolute left-2.5 top-2.5 size-[15px]'
          />
          <Input
            ref={searchRef}
            type='search'
            value={draft}
            onChange={(e) => typeQuery(e.target.value)}
            placeholder={copy.searchPlaceholder}
            aria-label={copy.searchLabel}
            className='touch:min-h-11 pl-[30px]'
          />
        </div>
        {!narrow && sectorSelect}
        <span
          role='status'
          aria-live='polite'
          className={cn(
            'text-muted-foreground tabular text-xs',
            narrow && 'sr-only'
          )}
        >
          {loading ? copy.loading : copy.count(total, shown)}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant='outline'
              aria-label={narrow ? copy.filters : copy.columns}
              className={cn(
                'ml-auto font-sans text-sm font-normal',
                narrow && 'size-9 p-0'
              )}
            >
              {narrow ? (
                <EllipsisVertical aria-hidden='true' strokeWidth={1.5} />
              ) : (
                copy.columns
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end' className='w-56'>
            {narrow && (
              <>
                <DropdownMenuLabel className='text-2xs text-muted-foreground font-normal uppercase tracking-[0.08em]'>
                  {copy.sector}
                </DropdownMenuLabel>
                <DropdownMenuRadioGroup
                  value={sector ?? ALL_SECTORS}
                  onValueChange={(v) =>
                    onSectorChange(v === ALL_SECTORS ? null : v)
                  }
                >
                  <DropdownMenuRadioItem value={ALL_SECTORS}>
                    {copy.allSectors}
                  </DropdownMenuRadioItem>
                  {SECTORS.map((s) => (
                    <DropdownMenuRadioItem key={s} value={s}>
                      {s}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuLabel className='text-2xs text-muted-foreground font-normal uppercase tracking-[0.08em]'>
              {copy.optionalColumns}
            </DropdownMenuLabel>
            {MENU_COLUMNS.map((c) => (
              <DropdownMenuCheckboxItem
                key={c.id}
                checked={columnVisibility[c.id] !== false}
                onSelect={(e) => e.preventDefault()}
                onCheckedChange={(checked) =>
                  setUserColumns((prev) => ({ ...prev, [c.id]: checked }))
                }
              >
                {c.label}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {sector && (
        <div
          className={cn(
            '-mt-1 flex flex-wrap gap-1.5 px-4 pb-2.5',
            narrow && 'px-2.5'
          )}
        >
          <Badge variant='accent' className='gap-1 pr-1'>
            {sector}
            <button
              type='button'
              aria-label={sharedCopy.removeFilter(sector)}
              onClick={() => onSectorChange(null)}
              className='hover:bg-brand/15 focus-visible:outline-ring grid size-5 place-items-center focus-visible:outline-2'
            >
              <X aria-hidden='true' className='size-3' />
            </button>
          </Badge>
        </div>
      )}

      {quotesProblem?.kind === 'api-down' && !firstRun && (
        <StatusAlert title={copy.apiDownTitle} className='mx-4 mb-3 w-auto'>
          {copy.apiDownBody}
          {quotesProblem.lastUpdated &&
            copy.apiDownUpdated(
              formatTimeET(quotesProblem.lastUpdated, { seconds: true }),
              formatDateShort(quotesProblem.lastUpdated)
            )}
        </StatusAlert>
      )}
      {quotesProblem?.kind === 'missing-key' && (
        <StatusAlert title={copy.missingKeyTitle} className='mx-4 mb-3 w-auto'>
          Quotes cannot load. Set <code className='text-xs'>ALPACA_KEY_ID</code>{' '}
          and <code className='text-xs'>ALPACA_SECRET_KEY</code> in{' '}
          <code className='text-xs'>.env</code> and restart the app.
        </StatusAlert>
      )}

      {firstRun ? (
        <EmptyState mark title={copy.firstRunTitle} body={copy.firstRunBody} />
      ) : noMatches ? (
        <EmptyState
          title={copy.noMatchTitle(draft)}
          body={copy.noMatchBody}
          action={
            <Button
              variant='outline'
              className='touch:min-h-11'
              onClick={clearFilters}
            >
              {sharedCopy.clearFilters}
            </Button>
          }
        />
      ) : touch && !loading ? (
        <MarketList
          rows={table.getRowModel().rows.map((r) => r.original)}
          onOpen={onOpenCompany}
        />
      ) : (
        <MarketTable
          table={table}
          loading={loading}
          onOpen={onOpenCompany}
          onHover={onPrefetchCompany}
        />
      )}
    </div>
  )
}
