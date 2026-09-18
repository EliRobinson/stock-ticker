import { TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

// Destructive Alert (M4, M5, C5, N4, A5): fact, then consequence, then action.
export function StatusAlert({
  title,
  children,
  icon = true,
  centered = false,
  className,
  action
}: {
  title?: string
  children?: ReactNode
  icon?: boolean
  centered?: boolean
  className?: string
  action?: ReactNode
}) {
  return (
    <Alert
      variant='destructive'
      className={cn(
        centered &&
          'min-h-45 place-content-center justify-items-center text-center',
        className
      )}
    >
      {icon && !centered && (
        <TriangleAlert aria-hidden='true' strokeWidth={1.5} />
      )}
      {title && (
        <AlertTitle className={cn(centered && 'col-span-2 text-lg')}>
          {title}
        </AlertTitle>
      )}
      <AlertDescription
        className={cn(
          centered && 'col-span-2 max-w-[44ch] justify-items-center'
        )}
      >
        {children && <div>{children}</div>}
        {action}
      </AlertDescription>
    </Alert>
  )
}

export function EmptyState({
  title,
  body,
  action,
  size = 'md',
  mark = false,
  className
}: {
  title: string
  body?: ReactNode
  action?: ReactNode
  size?: 'sm' | 'md'
  mark?: boolean
  className?: string
}) {
  return (
    <div
      className={cn(
        'grid flex-1 place-items-center p-6 text-center',
        size === 'sm' && 'p-4',
        className
      )}
    >
      <div className={size === 'md' ? 'max-w-[40ch]' : 'max-w-[30ch]'}>
        {mark && (
          <div
            aria-hidden='true'
            className='border-border mx-auto mb-3 size-[34px] border'
          />
        )}
        <p
          className={cn(
            'font-heading mb-1 font-semibold',
            size === 'md' ? 'text-[20px] leading-tight' : 'text-base'
          )}
        >
          {title}
        </p>
        {body && (
          <p
            className={cn(
              'text-muted-foreground text-pretty',
              size === 'md' ? 'text-sm' : 'text-xs',
              action && 'mb-3'
            )}
          >
            {body}
          </p>
        )}
        {action}
      </div>
    </div>
  )
}

export function SkeletonBar({ className }: { className?: string }) {
  return <Skeleton aria-hidden='true' className={cn('h-[11px]', className)} />
}

export function ProgressTrack({
  value,
  className
}: {
  value: number
  className?: string
}) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <span
      aria-hidden='true'
      className={cn('bg-track relative block h-1 flex-1', className)}
    >
      <span
        className='bg-brand absolute inset-y-0 left-0'
        style={{ width: `${pct}%` }}
      />
    </span>
  )
}

export function Kicker({
  children,
  className
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'text-muted-foreground text-2xs uppercase tracking-[0.06em]',
        className
      )}
    >
      {children}
    </div>
  )
}
