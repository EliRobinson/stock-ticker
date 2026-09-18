'use client'

import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef } from 'react'

import { ChangeCell } from '../shared/cells'
import { SkeletonBar } from '../shared/feedback'
import { formatPrice } from '../shared/format'
import { marketCopy } from './copy'
import type { MarketRowView } from './market-rows'

const ITEM = 56

// Touch phones (design G0, M0): a 56px-row list with the two figures that
// never collapse. A stale row trades its change for its age.
export function MarketList({
  rows,
  onOpen
}: {
  rows: MarketRowView[]
  onOpen: (row: MarketRowView) => void
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ITEM,
    overscan: 8,
    initialRect: { width: 390, height: 12 * ITEM }
  })
  return (
    <div
      ref={scrollRef}
      role='list'
      aria-label={marketCopy.tableLabel}
      className='border-border min-h-0 flex-1 overflow-auto border-t'
    >
      <div className='relative' style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((item) => {
          const r = rows[item.index]
          if (!r) return null
          return (
            <button
              key={r.symbol}
              type='button'
              role='listitem'
              onClick={() => onOpen(r)}
              className='border-rowline hover:bg-hover focus-visible:outline-ring absolute inset-x-0 flex min-h-14 items-center gap-2.5 border-b px-3 py-2 text-left focus-visible:outline-2 focus-visible:-outline-offset-2'
              style={{ top: item.start, height: ITEM }}
            >
              <span className='min-w-0 flex-1'>
                <span className='block text-base font-bold'>{r.symbol}</span>
                <span className='text-muted-foreground block truncate text-xs'>
                  {r.stale ? r.ageLabel : r.name}
                </span>
              </span>
              <span className='tabular text-right'>
                <span
                  className={
                    r.stale
                      ? 'text-stale block text-base'
                      : 'block text-base font-bold'
                  }
                >
                  {formatPrice(r.price)}
                </span>
                {r.backfillPending ? (
                  <SkeletonBar className='ml-auto w-16' />
                ) : (
                  <ChangeCell
                    pct={r.change_pct}
                    stale={r.stale}
                    className='block text-xs'
                  />
                )}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
