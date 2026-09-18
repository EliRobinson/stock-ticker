'use client'

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from '@/components/ui/command'

import { changeText } from '../shared/cells'
import { directionOf as direction, formatPrice } from '@/lib/format'
import { shellCopy } from './copy'

const copy = shellCopy.palette

export interface PaletteEntry {
  cik: string
  symbol: string
  name: string
  price: string | number | null
  change_pct: string | number | null
}

const DIR = { up: 'text-up', down: 'text-down', flat: 'text-flat' } as const

export function PaletteBody({
  entries,
  onSelect
}: {
  entries: PaletteEntry[]
  onSelect: (entry: PaletteEntry) => void
}) {
  return (
    <>
      <CommandInput placeholder={copy.placeholder} aria-label={copy.title} />
      <CommandList className='max-h-[320px] p-1.5'>
        <CommandEmpty className='text-muted-foreground py-6 text-center text-sm'>
          {copy.empty}
        </CommandEmpty>
        <CommandGroup>
          {entries.map((e) => {
            const dir = direction(e.change_pct)
            return (
              <CommandItem
                key={e.symbol}
                value={`${e.symbol} ${e.name}`}
                onSelect={() => onSelect(e)}
                className='data-[selected=true]:bg-selected data-[selected=true]:border-brand text-md tabular data-[selected=true]:text-foreground min-h-10 gap-2.5 border-l-2 border-transparent px-2.5 py-2'
              >
                <span className='w-15 font-bold'>{e.symbol}</span>
                <span className='min-w-0 flex-1 truncate'>{e.name}</span>
                <span className='text-muted-foreground text-xs'>
                  {formatPrice(e.price, { currency: false })}
                </span>
                <span className={`${DIR[dir]} text-xs`}>
                  {changeText(e.change_pct)}
                </span>
              </CommandItem>
            )
          })}
        </CommandGroup>
      </CommandList>
      <div className='border-border text-muted-foreground text-2xs flex gap-3.5 border-t px-3 py-2'>
        <span>{copy.move}</span>
        <span>{copy.open}</span>
        <span>{copy.anywhere}</span>
      </div>
    </>
  )
}

// ⌘K: jump to a Company by symbol or name (design S6).
export function CommandPalette({
  open,
  onOpenChange,
  entries,
  onSelect
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  entries: PaletteEntry[]
  onSelect: (entry: PaletteEntry) => void
}) {
  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.title}
      description={copy.description}
      showCloseButton={false}
      className='border-border bg-background top-[18%] translate-y-0 gap-0 p-0 shadow-lg sm:max-w-[440px]'
    >
      <PaletteBody entries={entries} onSelect={onSelect} />
    </CommandDialog>
  )
}
