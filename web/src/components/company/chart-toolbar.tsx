'use client'

import { ChevronDown } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { DateRange } from 'react-day-picker'

import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover'
import { formatDateRange } from '@/lib/format'

import { Segmented } from '../shared/segmented'
import { companyCopy as copy } from './copy'
import { PRESETS, presetFits } from './range'
import type { ChartRange, RangePreset } from './range'

export type ChartMode = 'line' | 'candles'

const toDate = (s: string) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y!, (m ?? 1) - 1, d ?? 1)
}
const toIso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

// Range presets, a custom calendar range, line/candles, and the Event-kind
// toggles (design C1/C2 toolbar).
export function ChartToolbar({
  range,
  visible,
  first,
  last,
  onRangeChange,
  mode,
  onModeChange,
  kinds,
  onKindsChange
}: {
  range: ChartRange
  visible: { from: string; to: string } | null
  first: string
  last: string
  onRangeChange: (range: ChartRange) => void
  mode: ChartMode
  onModeChange: (mode: ChartMode) => void
  kinds: string[]
  onKindsChange: (kinds: string[]) => void
}) {
  const presetOptions = useMemo(
    () =>
      PRESETS.map((p) => {
        const fits = !first || presetFits(p, first, last)
        return {
          value: p,
          label: p,
          disabled: !fits,
          title: fits ? undefined : copy.presetDisabled
        }
      }),
    [first, last]
  )
  return (
    <div className='flex flex-wrap items-center gap-2.5 px-3.5 py-3'>
      <div className='max-w-full overflow-x-auto'>
        <Segmented
          label={copy.rangeLabel}
          value={range.kind === 'preset' ? range.preset : ('' as RangePreset)}
          onValueChange={(preset) => onRangeChange({ kind: 'preset', preset })}
          options={presetOptions}
        />
      </div>
      <CustomRange
        value={visible}
        min={first}
        max={last}
        onChange={(r) => onRangeChange({ kind: 'custom', ...r })}
      />
      <Segmented
        label={copy.chartType}
        value={mode}
        onValueChange={onModeChange}
        options={[
          { value: 'line', label: copy.line },
          { value: 'candles', label: copy.candles }
        ]}
        className='ml-auto'
      />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant='outline' className='font-sans text-sm font-normal'>
            {copy.events}
            <ChevronDown
              aria-hidden='true'
              className='size-3.5'
              strokeWidth={1.8}
            />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' className='w-56'>
          <DropdownMenuLabel className='text-muted-foreground text-3xs font-normal uppercase tracking-[0.1em]'>
            {copy.eventKinds}
          </DropdownMenuLabel>
          {copy.eventToggles.map((t) => (
            <DropdownMenuCheckboxItem
              key={t.id}
              checked={kinds.includes(t.id)}
              onSelect={(e) => e.preventDefault()}
              onCheckedChange={(on) =>
                onKindsChange(
                  on ? [...kinds, t.id] : kinds.filter((k) => k !== t.id)
                )
              }
            >
              {t.label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function CustomRange({
  value,
  min,
  max,
  onChange
}: {
  value: { from: string; to: string } | null
  min: string
  max: string
  onChange: (range: { from: string; to: string }) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<DateRange | undefined>()
  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (o && value)
          setDraft({ from: toDate(value.from), to: toDate(value.to) })
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant='outline'
          aria-label={copy.customRange}
          className='tabular font-sans text-sm font-normal'
        >
          {value ? formatDateRange(value.from, value.to) : copy.customRange}
        </Button>
      </PopoverTrigger>
      <PopoverContent align='start' className='w-auto p-0'>
        <Calendar
          mode='range'
          numberOfMonths={2}
          selected={draft}
          defaultMonth={value ? toDate(value.from) : undefined}
          captionLayout='dropdown'
          disabled={
            min ? [{ before: toDate(min) }, { after: toDate(max) }] : undefined
          }
          onSelect={(r) => {
            setDraft(r)
            if (r?.from && r.to && r.from.getTime() !== r.to.getTime()) {
              onChange({ from: toIso(r.from), to: toIso(r.to) })
              setOpen(false)
            }
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
