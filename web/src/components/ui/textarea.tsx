import * as React from 'react'
import { cn } from '@/lib/utils'

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot='textarea'
      className={cn(
        'field-sizing-content border-input bg-secondary text-md caret-brand placeholder:text-muted-foreground hover:border-foreground/45 focus-visible:border-ring focus-visible:outline-ring aria-invalid:border-destructive flex min-h-16 w-full border px-2.5 py-1.5 outline-none transition-colors focus-visible:outline-2 focus-visible:outline-offset-0 disabled:cursor-not-allowed disabled:opacity-45',
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
