import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'
import { Slot } from 'radix-ui'

const badgeVariants = cva(
  'inline-flex w-fit shrink-0 items-center justify-center gap-1.5 overflow-hidden border border-transparent px-2.5 py-[3px] text-2xs leading-tight tracking-[0.02em] whitespace-nowrap focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3',
  {
    variants: {
      variant: {
        default: 'bg-tag-neutral text-tag-neutral-foreground',
        secondary: 'bg-tag-neutral text-tag-neutral-foreground',
        accent: 'bg-tag-accent text-tag-accent-foreground',
        outline: 'border-brand text-brand-strong',
        destructive: 'bg-pill-bad text-pill-bad-foreground',
        open: 'bg-pill-open text-pill-open-foreground',
        closed: 'bg-pill-closed text-pill-closed-foreground',
        amber: 'bg-pill-amber text-pill-amber-foreground',
        'amber-outline':
          'border-current bg-pill-amber text-pill-amber-foreground',
        bad: 'bg-pill-bad text-pill-bad-foreground',
        ghost: '',
        link: 'text-brand-strong underline-offset-3 [a&]:hover:underline'
      }
    },
    defaultVariants: {
      variant: 'default'
    }
  }
)

function Badge({
  className,
  variant = 'default',
  asChild = false,
  ...props
}: React.ComponentProps<'span'> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'span'

  return (
    <Comp
      data-slot='badge'
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
