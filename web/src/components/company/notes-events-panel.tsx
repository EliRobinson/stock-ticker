'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { MarketEvent, Note } from '@/lib/api'
import { eventMarkerId } from '@/lib/chart-data'
import { formatDateRange, formatDateShort } from '@/lib/format'
import { cn } from '@/lib/utils'

import { ClampedText } from '../shared/clamped-text'
import { sharedCopy } from '../shared/copy'
import { EmptyState } from '../shared/feedback'
import { SafeMarkdown } from '../shared/markdown'
import { companyCopy as copy } from './copy'

export type PanelTab = 'notes' | 'events'

export interface PanelItem {
  id: string
  start: string
  end: string
}

const itemCls =
  'border-border hover:bg-hover focus-visible:outline-ring flex w-full cursor-pointer border text-left focus-visible:outline-2 focus-visible:outline-offset-2'

// Notes and Events for this Company (design C1/C2 side panel). An item not
// on the loaded history reads "Outside chart range"; clicking any other item
// highlights its marker and, if needed, widens the chart to show it.
export function NotesEventsPanel({
  companyName,
  notes,
  events,
  outsideIds,
  highlightedId,
  onSelectItem,
  onNewNote,
  tab,
  onTabChange
}: {
  companyName: string
  notes: Note[]
  events: MarketEvent[]
  outsideIds: ReadonlySet<string>
  highlightedId: string | null
  onSelectItem: (item: PanelItem | null) => void
  onNewNote: () => void
  tab: PanelTab
  onTabChange: (tab: PanelTab) => void
}) {
  const sortedNotes = [...notes].sort((a, b) =>
    b.start_date.localeCompare(a.start_date)
  )
  const sortedEvents = [...events].sort((a, b) =>
    b.event_date.localeCompare(a.event_date)
  )
  const select = (item: PanelItem) =>
    onSelectItem(highlightedId === item.id ? null : item)
  const triggerCls =
    'border-border data-[state=active]:bg-primary data-[state=active]:text-primary-foreground h-auto min-h-8 flex-none rounded-none border-0 border-l px-3 py-[7px] text-sm font-normal first:border-l-0 data-[state=active]:shadow-none'

  return (
    <aside
      aria-label={copy.tabs.label}
      className='border-border @max-stack:border-t @max-stack:border-l-0 flex min-w-0 flex-col border-l'
    >
      <Tabs
        value={tab}
        onValueChange={(v) => onTabChange(v as PanelTab)}
        className='flex min-h-0 flex-1 flex-col gap-0'
      >
        <div className='flex items-center gap-2 p-3'>
          <TabsList
            aria-label={copy.tabs.label}
            className='border-border h-auto gap-0 border bg-transparent p-0'
          >
            <TabsTrigger value='notes' className={triggerCls}>
              {copy.tabs.notes(notes.length)}
            </TabsTrigger>
            <TabsTrigger value='events' className={triggerCls}>
              {copy.tabs.events(events.length)}
            </TabsTrigger>
          </TabsList>
          <Button
            variant='outline'
            size='sm'
            onClick={onNewNote}
            className='ml-auto font-sans text-xs font-normal'
          >
            {copy.newNote}
          </Button>
        </div>

        <TabsContent value='notes' className='flex min-h-0 flex-col'>
          {notes.length === 0 ? (
            <EmptyState
              size='sm'
              title={copy.noNotes(companyName)}
              body={copy.noNotesBody}
            />
          ) : (
            <ul className='m-0 flex list-none flex-col gap-2.5 overflow-auto px-3 pb-3'>
              {sortedNotes.map((n) => {
                const outside = outsideIds.has(n.id)
                const active = highlightedId === n.id
                return (
                  <li key={n.id}>
                    <div
                      role='button'
                      tabIndex={0}
                      aria-pressed={active}
                      aria-disabled={outside || undefined}
                      onClick={() =>
                        !outside &&
                        select({
                          id: n.id,
                          start: n.start_date,
                          end: n.end_date
                        })
                      }
                      onKeyDown={(e) => {
                        if ((e.key === 'Enter' || e.key === ' ') && !outside) {
                          e.preventDefault()
                          select({
                            id: n.id,
                            start: n.start_date,
                            end: n.end_date
                          })
                        }
                      }}
                      className={cn(
                        itemCls,
                        'flex-col gap-1 px-2.5 py-[9px]',
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
                      <ClampedText
                        length={n.body.length}
                        className='text-xs leading-[1.5]'
                      >
                        <SafeMarkdown>{n.body}</SafeMarkdown>
                      </ClampedText>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </TabsContent>

        <TabsContent value='events' className='flex min-h-0 flex-col'>
          {events.length === 0 ? (
            <EmptyState
              size='sm'
              title={copy.noEvents}
              body={copy.noEventsBody}
            />
          ) : (
            <ul className='m-0 flex list-none flex-col gap-2 overflow-auto px-3 pb-3'>
              {sortedEvents.map((e) => {
                const id = eventMarkerId(e)
                const outside = outsideIds.has(id)
                const active = highlightedId === id
                return (
                  <li key={e.id}>
                    <button
                      type='button'
                      aria-pressed={active}
                      aria-disabled={outside || undefined}
                      onClick={() =>
                        !outside &&
                        select({ id, start: e.event_date, end: e.event_date })
                      }
                      className={cn(
                        itemCls,
                        'items-baseline gap-2 px-2.5 py-2',
                        active && 'border-brand bg-selected'
                      )}
                    >
                      <span className='tabular whitespace-nowrap text-xs font-bold'>
                        {formatDateShort(e.event_date)}
                      </span>
                      <Badge variant='accent'>
                        {copy.eventKindLabels[e.kind] ?? e.kind}
                      </Badge>
                      <span className='text-muted-foreground ml-auto truncate text-xs'>
                        {outside ? sharedCopy.outsideRange : e.title}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </TabsContent>
      </Tabs>
      <p className='text-muted-foreground text-2xs mx-3 mb-3 mt-auto text-pretty pt-3'>
        {copy.panelHint}
      </p>
    </aside>
  )
}
