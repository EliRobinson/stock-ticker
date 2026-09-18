'use client'

import type { ReactNode } from 'react'

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

import {
  direction,
  formatAge,
  formatPrice,
  formatSignedMoney,
  formatSignedPercent
} from './format'
import type { NumericInput } from './format'
import { marketCopy } from '../market/copy'

const DIR_TEXT = {
  up: 'text-up',
  down: 'text-down',
  flat: 'text-flat'
} as const

const ARROW = { up: '↑ ', down: '↓ ', flat: '' } as const

export function changeText(pct: NumericInput, abs?: NumericInput): string {
  const dir = direction(pct)
  const head = `${ARROW[dir]}${formatSignedPercent(pct)}`
  if (abs === undefined) return head
  return `${head} (${formatSignedMoney(abs)})`
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
  const dir = direction(pct)
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

// Price with tabular numerals; a Stale Quote drops emphasis and carries its age (S1).
export function QuoteCell({
  price,
  ageMs,
  state,
  className
}: {
  price: NumericInput
  ageMs: number | null
  state: QuoteState
  className?: string
}) {
  if (state === 'stale' && ageMs != null) {
    const age = formatAge(ageMs)
    return (
      <span
        className={cn('tabular text-stale', className)}
        aria-description={marketCopy.quoteAge(age)}
      >
        {formatPrice(price)}
        <span className='text-2xs'>{` · ${marketCopy.ageOld(age)}`}</span>
      </span>
    )
  }
  return <span className={cn('tabular', className)}>{formatPrice(price)}</span>
}

// A missing value whose reason is known: a dash plus the reason on hover or focus.
export function ExplainedDash({
  reason,
  className
}: {
  reason: string
  className?: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          aria-label={reason}
          className={cn(
            'text-muted-foreground cursor-help border-b border-dotted border-current',
            className
          )}
        >
          {'—'}
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
