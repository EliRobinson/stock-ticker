'use client'

import type { SortingState, VisibilityState } from '@tanstack/react-table'
import { EllipsisVertical, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
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
import { cn } from '@/lib/utils'

import { EmptyState, StatusAlert } from '../shared/feedback'
import { formatDate, formatTimeET } from '../shared/format'
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
  forceTouchList?: boolean
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
function autoVisibility(width: number): VisibilityState {
  return {
    sector: width >= 1100,
    volume: width >= 1100,
    market_cap: width >= 860,
    name: width >= 520,
    observed_at: width >= 520,
    change: false
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
  forceTouchList,
  className
}: MarketScreenProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const width = useElementWidth(rootRef)
  const touchQuery = useMediaQuery(TOUCH_PHONE)
  const touch = forceTouchList ?? touchQuery
  const [draft, setDraft] = useState(query)
  const [userColumns, setUserColumns] = useState<VisibilityState>({})

  const [seenQuery, setSeenQuery] = useState(query)
  if (query !== seenQuery) {
    setSeenQuery(query)
    setDraft(query)
  }
  useEffect(() => {
    if (draft === query) return
    const t = setTimeout(() => onQueryChange(draft), 150)
    return () => clearTimeout(t)
  }, [draft, query, onQueryChange])

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
  const columnVisibility = useMemo(
    () => ({ ...autoVisibility(width), ...userColumns }),
    [width, userColumns]
  )
  const anyStale = rows.some((r) => r.stale)
  const labels = useMemo(
    () =>
      quotesProblem?.kind === 'api-down'
        ? {
            price: copy.columnLabels.priceStale,
            age: copy.columnLabels.age,
            widePrice: true
          }
        : market && !market.market_clock?.is_open
          ? {
              price: copy.columnLabels.priceClosed,
              age: copy.columnLabels.ageClosed
            }
          : {
              price: copy.columnLabels.price,
              age: copy.columnLabels.age,
              widePrice: anyStale
            },
    [market, quotesProblem, anyStale]
  )

  const table = useMarketTable({
    rows,
    query,
    sector,
    sorting,
    onSortingChange,
    columnVisibility,
    labels
  })
  const shown = table.getRowModel().rows.length
  const total = rows.length
  const firstRun = !loading && market != null && total === 0
  const noMatches = !loading && total > 0 && shown === 0

  const clearFilters = () => {
    setDraft('')
    onQueryChange('')
    onSectorChange(null)
  }

  return (
    <div
      ref={rootRef}
      className={cn('@container flex h-full min-h-0 flex-col', className)}
    >
      <div className='@max-[560px]:px-2.5 @max-[560px]:py-2 flex flex-wrap items-center gap-2.5 px-4 py-3'>
        <div className='w-70 @max-[560px]:min-w-0 @max-[560px]:flex-1 relative max-w-full'>
          <Search
            aria-hidden='true'
            strokeWidth={1.5}
            className='text-muted-foreground pointer-events-none absolute left-2.5 top-2.5 size-[15px]'
          />
          <Input
            ref={searchRef}
            type='search'
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={copy.searchPlaceholder}
            aria-label={copy.searchLabel}
            className='touch:min-h-11 pl-[30px]'
          />
        </div>
        <Select
          value={sector ?? ALL_SECTORS}
          onValueChange={(v) => onSectorChange(v === ALL_SECTORS ? null : v)}
        >
          <SelectTrigger
            aria-label={copy.sectorLabel}
            className='w-47.5 @max-[560px]:hidden'
          >
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
        <span
          role='status'
          aria-live='polite'
          className='text-muted-foreground tabular @max-[560px]:hidden text-xs'
        >
          {loading ? copy.loading : copy.count(total, shown)}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant='outline'
              aria-label={copy.columns}
              className='@max-[560px]:size-9 @max-[560px]:p-0 ml-auto font-sans text-sm font-normal'
            >
              <span className='@max-[560px]:hidden'>{copy.columns}</span>
              <EllipsisVertical
                aria-hidden='true'
                className='@min-[560px]:hidden'
                strokeWidth={1.5}
              />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end' className='w-48'>
            <DropdownMenuLabel className='text-2xs text-muted-foreground font-normal uppercase tracking-[0.08em]'>
              {copy.optionalColumns}
            </DropdownMenuLabel>
            {MENU_COLUMNS.map((c) => (
              <DropdownMenuCheckboxItem
                key={c.id}
                checked={columnVisibility[c.id] !== false}
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

      {quotesProblem?.kind === 'api-down' && !firstRun && (
        <StatusAlert title={copy.apiDownTitle} className='mx-4 mb-3'>
          {copy.apiDownBody}
          {quotesProblem.lastUpdated &&
            copy.apiDownUpdated(
              formatTimeET(quotesProblem.lastUpdated, true),
              formatDate(quotesProblem.lastUpdated)
            )}
        </StatusAlert>
      )}
      {quotesProblem?.kind === 'missing-key' && (
        <StatusAlert title={copy.missingKeyTitle} className='mx-4 mb-3'>
          Quotes cannot load. Set <code className='text-xs'>ALPACA_KEY_ID</code>{' '}
          and <code className='text-xs'>ALPACA_SECRET_KEY</code> in{' '}
          <code className='text-xs'>.env</code> and restart the app.
        </StatusAlert>
      )}

      {firstRun ? (
        <EmptyState mark title={copy.firstRunTitle} body={copy.firstRunBody} />
      ) : noMatches ? (
        <EmptyState
          title={copy.noMatchTitle(query)}
          body={copy.noMatchBody}
          action={
            <Button
              variant='outline'
              className='touch:min-h-11'
              onClick={clearFilters}
            >
              {copy.clearFilters}
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
