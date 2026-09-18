import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'
import { Slot } from 'radix-ui'

const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-md border font-heading text-md leading-tight font-semibold whitespace-nowrap transition-colors outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-45 aria-disabled:pointer-events-none aria-disabled:opacity-45 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          'border-primary bg-primary text-primary-foreground hover:bg-primary/90 active:bg-primary/80',
        destructive:
          'border-current bg-transparent text-[inherit] hover:bg-foreground/7',
        outline:
          'border-border bg-transparent hover:bg-foreground/7 active:bg-foreground/14',
        secondary:
          'border-border bg-secondary text-secondary-foreground hover:bg-foreground/7',
        ghost:
          'border-transparent px-1 text-brand-strong hover:bg-brand/10 active:bg-brand/18',
        link: 'border-transparent text-brand-strong underline-offset-3 hover:underline'
      },
      size: {
        default: 'min-h-9 px-3 py-1.5',
        xs: "min-h-6 gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: 'min-h-8 gap-1.5 px-2.5 py-1',
        lg: 'min-h-11 px-4',
        icon: 'size-9',
        'icon-xs': "size-6 [&_svg:not([class*='size-'])]:size-3",
        'icon-sm': 'size-8',
        'icon-lg': 'size-10'
      }
    },
    defaultVariants: {
      variant: 'default',
      size: 'default'
    }
  }
)

function Button({
  className,
  variant = 'default',
  size = 'default',
  asChild = false,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : 'button'

  return (
    <Comp
      data-slot='button'
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
