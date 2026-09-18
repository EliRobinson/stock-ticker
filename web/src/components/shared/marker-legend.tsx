import { cn } from '@/lib/utils'

export function NoteMarkerGlyph({ size = 12 }: { size?: number }) {
  const r = size / 2 - 1.5
  return (
    <svg width={size} height={size} aria-hidden='true' className='flex-none'>
      <circle cx={size / 2} cy={size / 2} r={r} className='fill-chart-note' />
    </svg>
  )
}

export function EventMarkerGlyph({ size = 12 }: { size?: number }) {
  const c = size / 2
  const e = size / 2 - 1
  return (
    <svg width={size} height={size} aria-hidden='true' className='flex-none'>
      <path
        d={`M${c} ${c - e} ${c + e} ${c} ${c} ${c + e} ${c - e} ${c}Z`}
        fill='none'
        strokeWidth={1.5}
        className='stroke-chart-event'
      />
    </svg>
  )
}

export function MarkerLegend({
  note = 'Note · yours',
  event = 'Event · sourced fact',
  hint,
  className
}: {
  note?: string
  event?: string | null
  hint?: string
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-center gap-4 text-xs', className)}>
      <span className='flex items-center gap-1.5'>
        <NoteMarkerGlyph />
        {note}
      </span>
      {event && (
        <span className='flex items-center gap-1.5'>
          <EventMarkerGlyph />
          {event}
        </span>
      )}
      {hint && <span className='text-muted-foreground'>{hint}</span>}
    </div>
  )
}
