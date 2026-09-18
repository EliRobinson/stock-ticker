'use client'

import { CircleAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover'

import type { MarketClock } from '@/lib/api'
import { formatClock, formatTimeET, formatUsd } from '@/lib/format'
import { cn } from '@/lib/utils'

import { shellCopy } from '../shell/copy'
import { sessionLabel, sessionOf } from './market-session'

export function MarketStatusPill({
  clock,
  serverTime,
  className
}: {
  clock: MarketClock | null | undefined
  serverTime: string
  className?: string
}) {
  const session = sessionOf(clock, serverTime)
  const variant =
    session === 'open'
      ? 'open'
      : session === 'pre' || session === 'after'
        ? 'amber-outline'
        : 'closed'
  return (
    <Badge
      role='status'
      variant={variant}
      className={className}
      data-session={session}
    >
      {session === 'open' && (
        <span aria-hidden='true' className='block size-1.5 bg-current' />
      )}
      {sessionLabel(clock, serverTime)}
    </Badge>
  )
}

export type IngestHealth = 'ok' | 'degraded' | 'failing'

export interface IngestDetail {
  lastRunAt: string | null
  summary: string
}

const HEALTH_VARIANT = {
  ok: 'default',
  degraded: 'amber',
  failing: 'bad'
} as const

export function IngestHealthPill({
  health,
  detail,
  compact = false,
  className
}: {
  health: IngestHealth
  detail?: IngestDetail
  compact?: boolean
  className?: string
}) {
  const label = shellCopy.status.ingest(health)
  const text =
    !compact && health === 'ok' && detail?.lastRunAt
      ? `${label} · ${shellCopy.status.ingestLastRun(formatClock(detail.lastRunAt))}`
      : label
  const pill = (
    <Badge
      variant={HEALTH_VARIANT[health]}
      className={cn(detail && 'cursor-pointer', className)}
    >
      {health === 'failing' && (
        <CircleAlert
          aria-hidden='true'
          className='size-[13px]'
          strokeWidth={1.8}
        />
      )}
      {text}
    </Badge>
  )
  if (!detail) return <span role='status'>{pill}</span>
  return (
    <Popover>
      <PopoverTrigger
        className='focus-visible:outline-ring focus-visible:outline-2 focus-visible:outline-offset-2'
        aria-label={shellCopy.status.ingestShowRun(label)}
      >
        {pill}
      </PopoverTrigger>
      <PopoverContent
        align='start'
        className='tabular w-auto max-w-80 p-[9px_10px] text-xs'
      >
        <strong className='font-heading text-md block font-semibold'>
          {detail.lastRunAt
            ? shellCopy.status.ingestLastRunAt(
                formatTimeET(detail.lastRunAt, { seconds: true })
              )
            : shellCopy.status.ingestNoRun}
        </strong>
        <span className='text-muted-foreground'>{detail.summary}</span>
      </PopoverContent>
    </Popover>
  )
}

export function AiSpendPill({
  spendUsd,
  limitUsd,
  className
}: {
  spendUsd: number
  limitUsd: number
  className?: string
}) {
  const spent = spendUsd >= limitUsd
  return (
    <Badge
      variant={spent ? 'amber' : 'default'}
      className={cn('tabular', className)}
      title={shellCopy.status.aiSpendHint}
    >
      {spent
        ? shellCopy.status.aiSpent
        : shellCopy.status.aiSpend(formatUsd(spendUsd), formatUsd(limitUsd))}
    </Badge>
  )
}
