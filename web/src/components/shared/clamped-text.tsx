'use client'

import { useState } from 'react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { sharedCopy } from './copy'

// Long Note bodies clamp to three lines with a Read more that expands in
// place (brief: Company side list, Notes list).
export function ClampedText({
  children,
  length,
  lines = 3,
  className
}: {
  children: ReactNode
  length: number
  lines?: 2 | 3
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const long = length > (lines === 3 ? 140 : 90)
  return (
    <div>
      <div
        className={cn(
          'text-pretty [&_p]:m-0',
          !open && (lines === 3 ? 'line-clamp-3' : 'line-clamp-2'),
          className
        )}
      >
        {children}
      </div>
      {long && (
        <Button
          variant='ghost'
          size='xs'
          aria-expanded={open}
          onClick={(e) => {
            e.stopPropagation()
            setOpen(!open)
          }}
          className='mt-1 min-h-6 px-0 font-sans text-xs font-normal'
        >
          {open ? sharedCopy.showLess : sharedCopy.readMore}
        </Button>
      )}
    </div>
  )
}
