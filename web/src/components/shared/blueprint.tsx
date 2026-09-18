import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

const CORNERS = ['tl', 'tr', 'bl', 'br'] as const

interface BlueprintProps extends ComponentProps<'div'> {
  corners?: boolean
}

// The Industry design system's frame: square, hairline-bordered, with
// registration-mark corners. The corners are decoration only.
export function Blueprint({
  corners = true,
  className,
  children,
  ...props
}: BlueprintProps) {
  return (
    <div className={cn('blueprint', className)} {...props}>
      {corners &&
        CORNERS.map((c) => (
          <i
            key={c}
            aria-hidden='true'
            className='blueprint-corner'
            data-corner={c}
          />
        ))}
      {children}
    </div>
  )
}
