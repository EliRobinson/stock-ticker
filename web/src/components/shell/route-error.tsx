'use client'

import { Button } from '@/components/ui/button'

import { StatusAlert } from '../shared/feedback'
import { boundaryCopy as copy } from './copy'

export function RouteError({
  error,
  retry
}: {
  error: Error & { digest?: string }
  retry: () => void
}) {
  return (
    <div className='p-3.5'>
      <StatusAlert
        title={copy.title}
        action={
          <Button
            variant='destructive'
            size='sm'
            onClick={retry}
            className='font-sans text-xs font-normal'
          >
            {copy.retry}
          </Button>
        }
      >
        {error.message && process.env.NODE_ENV !== 'production'
          ? error.message
          : copy.body}
      </StatusAlert>
    </div>
  )
}
