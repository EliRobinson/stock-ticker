'use client'

import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Event, Note } from '@/lib/api'
import { cn } from '@/lib/utils'

import { EmptyState } from '../shared/feedback'
import { formatDate, formatDateRange } from '../shared/format'
import { Segmented } from '../shared/segmented'
import { companyCopy as copy } from './copy'

export function ClampedText({
  text,
  lines = 3,
  className
}: {
  text: string
  lines?: 2 | 3
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const long = text.length > (lines === 3 ? 140 : 90)
  return (
    <div>
      <p
        className={cn(
          'm-0 text-pretty text-xs leading-[1.5]',
          !open && (lines === 3 ? 'line-clamp-3' : 'line-clamp-2'),
          className
        )}
      >
        {text}
      </p>
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
          {open ? copy.showLess : copy.readMore}
        </Button>
      )}
    </div>
  )
}

export function NotesEventsPanel({
  companyName,
  notes,
  events,
  outsideNoteIds,
  visibleRange,
  highlightedId,
  onHighlight,
  onNewNote,
  initialTab = 'notes'
}: {
  companyName: string
  notes: Note[]
  events: Event[]
  outsideNoteIds: Set<string>
  visibleRange: { from: string; to: string } | null
  highlightedId: string | null
  onHighlight: (id: string | null) => void
  onNewNote: () => void
  initialTab?: 'notes' | 'events'
}) {
  const [tab, setTab] = useState<'notes' | 'events'>(initialTab)
  const inView = (d: string) =>
    !visibleRange || (d >= visibleRange.from && d <= visibleRange.to)
  const sortedNotes = [...notes].sort((a, b) =>
    b.start_date.localeCompare(a.start_date)
  )
  const sortedEvents = [...events].sort((a, b) =>
    b.event_date.localeCompare(a.event_date)
  )

  return (
    <aside
      aria-label={copy.tabs.label}
      className='border-border @max-[900px]:border-t @max-[900px]:border-l-0 flex min-w-0 flex-col border-l'
    >
      <div className='flex items-center gap-2 p-3'>
        <Segmented
          label={copy.tabs.label}
          value={tab}
          onValueChange={setTab}
          options={[
            { value: 'notes', label: copy.tabs.notes(notes.length) },
            { value: 'events', label: copy.tabs.events(events.length) }
          ]}
        />
        <Button
          variant='outline'
          size='sm'
          onClick={onNewNote}
          className='ml-auto font-sans text-xs font-normal'
        >
          {copy.newNote}
        </Button>
      </div>

      {tab === 'notes' ? (
        notes.length === 0 ? (
          <EmptyState
            size='sm'
            title={copy.noNotes(companyName)}
            body={copy.noNotesBody}
          />
        ) : (
          <ul className='m-0 flex list-none flex-col gap-2.5 overflow-auto px-3 pb-3'>
            {sortedNotes.map((n) => {
              const outside = outsideNoteIds.has(n.id) || !inView(n.start_date)
              const active = highlightedId === n.id
              return (
                <li key={n.id}>
                  <div
                    role='button'
                    tabIndex={0}
                    aria-pressed={active}
                    onClick={() => onHighlight(active ? null : n.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onHighlight(active ? null : n.id)
                      }
                    }}
                    className={cn(
                      'border-border hover:bg-hover focus-visible:outline-ring flex cursor-pointer flex-col gap-1 border px-2.5 py-[9px] focus-visible:outline-2 focus-visible:outline-offset-2',
                      active && 'border-brand bg-selected'
                    )}
                  >
                    <div className='flex items-baseline gap-2'>
                      <span className='tabular text-xs font-bold'>
                        {formatDateRange(n.start_date, n.end_date)}
                      </span>
                      <span className='text-muted-foreground text-2xs ml-auto'>
                        {outside
                          ? copy.outsideRange
                          : n.start_date === n.end_date
                            ? copy.singleDate
                            : copy.range}
                      </span>
                    </div>
                    <ClampedText text={n.body} />
                  </div>
                </li>
              )
            })}
          </ul>
        )
      ) : events.length === 0 ? (
        <EmptyState size='sm' title={copy.noEvents} body={copy.noEventsBody} />
      ) : (
        <ul className='m-0 flex list-none flex-col gap-2 overflow-auto px-3 pb-3'>
          {sortedEvents.map((e) => {
            const id = `event-${e.id}`
            const active = highlightedId === id
            return (
              <li key={e.id}>
                <button
                  type='button'
                  aria-pressed={active}
                  onClick={() => onHighlight(active ? null : id)}
                  className={cn(
                    'border-border hover:bg-hover focus-visible:outline-ring flex w-full items-baseline gap-2 border px-2.5 py-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2',
                    active && 'border-brand bg-selected'
                  )}
                >
                  <span className='tabular whitespace-nowrap text-xs font-bold'>
                    {formatDate(e.event_date)}
                  </span>
                  <Badge variant='accent'>
                    {copy.eventKindLabels[e.kind] ?? e.kind}
                  </Badge>
                  <span className='text-muted-foreground ml-auto truncate text-xs'>
                    {inView(e.event_date) ? e.title : copy.outsideRange}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <p className='text-muted-foreground text-2xs mx-3 mb-3 mt-auto text-pretty pt-3'>
        {copy.panelHint}
      </p>
    </aside>
  )
}
