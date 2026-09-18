'use client'

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'

export interface SegmentOption<T extends string> {
  value: T
  label: string
  disabled?: boolean
  title?: string
}

// Industry ".seg": one hairline box, options split by rules, the chosen one filled.
// The fill is --primary rather than the design's --color-accent, so the 13px
// label clears 4.5:1 in both themes (design X1, row 6).
export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  label,
  size = 'default',
  stretch = false,
  className
}: {
  value: T
  onValueChange: (value: T) => void
  options: SegmentOption<T>[]
  label: string
  size?: 'default' | 'touch'
  stretch?: boolean
  className?: string
}) {
  return (
    <ToggleGroup
      type='single'
      value={value}
      onValueChange={(v) => {
        if (v) onValueChange(v as T)
      }}
      aria-label={label}
      className={cn(
        'border-border inline-flex w-fit overflow-hidden border',
        stretch && 'flex w-full',
        className
      )}
    >
      {options.map((o) => (
        <ToggleGroupItem
          key={o.value}
          value={o.value}
          disabled={o.disabled}
          title={o.title}
          className={cn(
            'border-border h-auto min-h-8 whitespace-nowrap border-l px-3 py-[7px] text-sm font-normal first:border-l-0',
            'hover:bg-foreground/7 hover:text-foreground',
            'data-[state=on]:bg-primary data-[state=on]:text-primary-foreground',
            'focus-visible:outline-ring focus-visible:outline-2 focus-visible:-outline-offset-2',
            'disabled:opacity-45',
            size === 'touch' && 'min-h-11',
            stretch && 'flex-1 justify-center'
          )}
        >
          {o.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
