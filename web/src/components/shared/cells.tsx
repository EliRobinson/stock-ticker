'use client'

import type { ReactNode } from 'react'

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'
import {
  directionOf,
  EMPTY,
  formatChange,
  formatPercent,
  formatPrice,
  formatQuoteAge
} from '@/lib/format'
import type { NumericInput } from '@/lib/format'
import { cn } from '@/lib/utils'

import { sharedCopy } from './copy'

const DIR_TEXT = {
  up: 'text-up',
  down: 'text-down',
  flat: 'text-flat'
} as const
const ARROW = { up: '↑ ', down: '↓ ', flat: '' } as const

/** "↑ +1.23% (+$3.14)": sign, arrow and percent, with the dollar move when given. */
export function changeText(pct: NumericInput, abs?: NumericInput): string {
  const head = `${ARROW[directionOf(pct)]}${formatPercent(pct)}`
  return abs === undefined ? head : `${head} (${formatChange(abs)})`
}

// Sign, arrow and color together: color is never the only signal (S2).
export function ChangeCell({
  pct,
  abs,
  stale = false,
  className
}: {
  pct: NumericInput
  abs?: NumericInput
  stale?: boolean
  className?: string
}) {
  const dir = directionOf(pct)
  return (
    <span
      className={cn(
        'tabular whitespace-nowrap',
        stale ? 'text-stale' : DIR_TEXT[dir],
        className
      )}
      data-direction={dir}
      data-stale={stale || undefined}
    >
      {changeText(pct, abs)}
    </span>
  )
}

export type QuoteState = 'fresh' | 'stale' | 'closed'

/** "14m old": the one way a Quote's age is written. */
export function quoteAgeText(ageMs: number | null, stale: boolean): string {
  if (ageMs === null) return EMPTY
  const age = formatQuoteAge(ageMs)
  return stale ? sharedCopy.ageOld(age) : age
}

// Price with tabular numerals; a Stale Quote drops emphasis and carries its
// age inline (S1). `lg` is the stat-row size on the Company screen.
export function QuoteCell({
  price,
  ageMs,
  state,
  size = 'sm',
  className
}: {
  price: NumericInput
  ageMs: number | null
  state: QuoteState
  size?: 'sm' | 'lg'
  className?: string
}) {
  const value = formatPrice(price, { currency: false })
  if (state === 'stale' && ageMs !== null) {
    return (
      <span
        className={cn(
          'tabular text-stale',
          size === 'lg' && 'text-2xl',
          className
        )}
        aria-description={sharedCopy.quoteAge(formatQuoteAge(ageMs))}
      >
        {value}
        <span className={size === 'lg' ? 'text-xs' : 'text-2xs'}>
          {` · ${quoteAgeText(ageMs, true)}`}
        </span>
      </span>
    )
  }
  return (
    <span
      className={cn(
        'tabular',
        size === 'lg' && 'text-2xl font-bold',
        className
      )}
    >
      {value}
    </span>
  )
}

// A missing value whose reason is known: a dash plus the reason on hover or
// focus. Inside a focusable table row the dash is not its own tab stop; the
// reason is read as part of the cell.
export function ExplainedDash({
  reason,
  focusable = true,
  className
}: {
  reason: string
  focusable?: boolean
  className?: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={focusable ? 0 : undefined}
          className={cn(
            'text-muted-foreground cursor-help border-b border-dotted border-current',
            className
          )}
        >
          <span aria-hidden='true'>{EMPTY}</span>
          <span className='sr-only'>{reason}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className='max-w-[26ch]'>{reason}</TooltipContent>
    </Tooltip>
  )
}

export function TruncatedText({
  text,
  className,
  children
}: {
  text: string
  className?: string
  children?: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('block truncate', className)}>
          {children ?? text}
        </span>
      </TooltipTrigger>
      <TooltipContent className='max-w-[30ch]'>{text}</TooltipContent>
    </Tooltip>
  )
}
