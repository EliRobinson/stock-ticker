'use client'

import { Info } from 'lucide-react'
import type { ReactNode } from 'react'

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'
import type { Bar, CompanyDetail, MarketRow } from '@/lib/api'
import { formatDateShort, formatMarketCap, formatPrice } from '@/lib/format'

import { ChangeCell, ExplainedDash, QuoteCell } from '../shared/cells'
import { Kicker } from '../shared/feedback'
import { companyCopy as copy } from './copy'

function Stat({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className='min-w-0'>
      <dt>
        <Kicker>{label}</Kicker>
      </dt>
      <dd className='m-0'>{children}</dd>
    </div>
  )
}

const range = (
  low: string | null | undefined,
  high: string | null | undefined
) =>
  `${formatPrice(low, { currency: false })} – ${formatPrice(high, { currency: false })}`

// Last, Market Cap (with its filing date), 52-week and day range (design C1).
export function CompanyStats({
  company,
  quote,
  quoteAgeMs,
  stale,
  isOpen,
  lastBar
}: {
  company: CompanyDetail
  quote: MarketRow | null
  quoteAgeMs: number | null
  stale: boolean
  isOpen: boolean
  lastBar: Bar | undefined
}) {
  const cap = company.market_cap
  const filing = cap
    ? copy.stats.fromFiling(formatDateShort(cap.shares_as_of))
    : null
  return (
    <dl className='tabular gap-x-6.5 @max-toolbar:grid @max-toolbar:grid-cols-2 m-0 flex flex-wrap gap-y-2.5'>
      <Stat label={isOpen ? copy.stats.last : copy.stats.lastClose}>
        {quote ? (
          <span className={stale ? 'flex flex-col' : 'text-2xl font-bold'}>
            <QuoteCell
              price={quote.price}
              ageMs={quoteAgeMs}
              state={stale ? 'stale' : isOpen ? 'fresh' : 'closed'}
              size='lg'
            />{' '}
            <ChangeCell
              pct={quote.change_pct}
              abs={quote.change}
              stale={stale}
              className='text-md font-normal'
            />
          </span>
        ) : (
          <span className='text-2xl font-bold'>{'—'}</span>
        )}
      </Stat>
      <Stat
        label={
          <span className='inline-flex items-center gap-1'>
            {copy.stats.marketCap}
            {filing && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type='button' aria-label={filing}>
                    <Info
                      aria-hidden='true'
                      className='size-[13px]'
                      strokeWidth={1.8}
                    />
                  </button>
                </TooltipTrigger>
                <TooltipContent>
                  {filing}
                  {cap?.is_approx && (
                    <span className='block'>{copy.stats.approx}</span>
                  )}
                </TooltipContent>
              </Tooltip>
            )}
          </span>
        }
      >
        {cap ? (
          <>
            <span className='text-2xl font-bold'>
              {cap.is_approx && <span aria-hidden='true'>{'≈'}</span>}
              {formatMarketCap(cap.market_cap)}
            </span>
            <span className='text-muted-foreground text-2xs block'>
              {filing}
            </span>
          </>
        ) : (
          <ExplainedDash
            reason={copy.stats.capUnavailable}
            className='text-2xl font-bold'
          />
        )}
      </Stat>
      <Stat label={copy.stats.range52}>
        <span className='text-2xl font-bold'>
          {range(company.week_52_low, company.week_52_high)}
        </span>
      </Stat>
      <Stat label={copy.stats.dayRange}>
        <span className='text-2xl font-bold'>
          {lastBar ? range(lastBar.low, lastBar.high) : '—'}
        </span>
      </Stat>
    </dl>
  )
}
