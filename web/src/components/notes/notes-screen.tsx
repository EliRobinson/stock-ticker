'use client'

import { EllipsisVertical } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import type { Note } from '@/lib/api'
import type { CompanyOption } from '@/lib/company'
import { formatDateRange } from '@/lib/format'

import { ClampedText } from '../shared/clamped-text'
import { sharedCopy } from '../shared/copy'
import { EmptyState, SkeletonBar, StatusAlert } from '../shared/feedback'
import { SafeMarkdown } from '../shared/markdown'
import { useDraft } from '../shared/use-draft'
import { notesCopy as copy } from './copy'
import { NoteDialog, emptyDraft } from './note-dialog'
import type { NoteDraft } from './note-dialog'

const ALL = '__all__'
export const MARKET_FILTER = '__market__'

export interface NotesFilters {
  /** A cik, MARKET_FILTER for whole-market Notes, or null for all. */
  company: string | null
  from: string | null
  to: string | null
  q: string
}

export const noFilters: NotesFilters = {
  company: null,
  from: null,
  to: null,
  q: ''
}

export function filterNotes(notes: Note[], f: NotesFilters): Note[] {
  const q = f.q.trim().toLowerCase()
  return notes
    .filter((n) =>
      f.company === null
        ? true
        : f.company === MARKET_FILTER
          ? n.cik == null
          : n.cik === f.company
    )
    .filter((n) => (f.from ? n.end_date >= f.from : true))
    .filter((n) => (f.to ? n.start_date <= f.to : true))
    .filter((n) => (q ? n.body.toLowerCase().includes(q) : true))
    .sort((a, b) => b.start_date.localeCompare(a.start_date))
}

const toIso = (d?: Date) =>
  d
    ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    : null
const toDate = (s: string | null) => {
  if (!s) return undefined
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y!, (m ?? 1) - 1, d ?? 1)
}

export interface NotesScreenProps {
  notes: Note[]
  loading?: boolean
  error?: boolean
  companies: CompanyOption[]
  symbolByCik: Record<string, string>
  today: string
  filters: NotesFilters
  onFiltersChange: (filters: Partial<NotesFilters>) => void
  onSave: (draft: NoteDraft) => Promise<unknown>
  onDelete: (note: Note) => void
}

export function NotesScreen({
  notes,
  loading = false,
  error = false,
  companies,
  symbolByCik,
  today,
  filters,
  onFiltersChange,
  onSave,
  onDelete
}: NotesScreenProps) {
  const [dialog, setDialog] = useState<NoteDraft | null>(null)
  const [query, setQuery] = useDraft(filters.q, (q) => onFiltersChange({ q }))
  const shown = useMemo(
    () => filterNotes(notes, { ...filters, q: query }),
    [notes, filters, query]
  )
  const filtered =
    filters.company !== null ||
    filters.from !== null ||
    filters.to !== null ||
    query.trim() !== ''
  const openNew = () => setDialog(emptyDraft(null, today))

  return (
    <div className='@container flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3.5'>
      <div className='flex items-center gap-2.5'>
        <h1 className='m-0 text-3xl'>{copy.title}</h1>
        {!loading && !error && (
          <span role='status' className='text-muted-foreground tabular text-xs'>
            {copy.count(notes.length, shown.length)}
          </span>
        )}
        <Button
          className='touch:min-h-12 ml-auto'
          disabled={error}
          aria-disabled={error || undefined}
          onClick={openNew}
        >
          {copy.newNote}
        </Button>
      </div>

      {error ? (
        <StatusAlert title={copy.errorTitle}>{copy.errorBody}</StatusAlert>
      ) : (
        <div className='@max-toolbar:flex-col flex flex-wrap gap-2'>
          <Select
            value={filters.company ?? ALL}
            onValueChange={(v) =>
              onFiltersChange({ company: v === ALL ? null : v })
            }
          >
            <SelectTrigger
              aria-label={copy.companyFilter}
              className='w-47.5 @max-toolbar:w-full'
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{copy.allCompanies}</SelectItem>
              <SelectItem value={MARKET_FILTER}>{copy.wholeMarket}</SelectItem>
              {companies.map((c) => (
                <SelectItem key={c.cik} value={c.cik}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant='outline'
                aria-label={copy.dateFilter}
                className='tabular @max-toolbar:w-full font-sans text-sm font-normal'
              >
                {filters.from
                  ? formatDateRange(filters.from, filters.to ?? filters.from)
                  : copy.anyDate}
              </Button>
            </PopoverTrigger>
            <PopoverContent align='start' className='w-auto p-0'>
              <Calendar
                mode='range'
                selected={
                  filters.from
                    ? { from: toDate(filters.from), to: toDate(filters.to) }
                    : undefined
                }
                onSelect={(r) =>
                  onFiltersChange({
                    from: toIso(r?.from),
                    to: toIso(r?.to ?? r?.from)
                  })
                }
                captionLayout='dropdown'
              />
              {filters.from && (
                <div className='border-border border-t p-2'>
                  <Button
                    variant='ghost'
                    size='sm'
                    onClick={() => onFiltersChange({ from: null, to: null })}
                  >
                    {copy.clearDates}
                  </Button>
                </div>
              )}
            </PopoverContent>
          </Popover>
          <Input
            type='search'
            aria-label={copy.search}
            placeholder={copy.search}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className='w-50 @max-toolbar:w-full'
          />
        </div>
      )}

      {loading ? (
        <div
          role='status'
          aria-label={copy.loading}
          className='flex flex-col gap-2.5'
        >
          {Array.from({ length: 6 }, (_, i) => (
            <div
              key={i}
              className='border-border flex h-[58px] flex-col gap-1.5 border p-2'
            >
              <SkeletonBar className='w-30 h-[9px]' />
              <SkeletonBar className='h-[9px] w-4/5' />
            </div>
          ))}
        </div>
      ) : error ? null : notes.length === 0 ? (
        <EmptyState
          title={copy.emptyTitle}
          body={copy.emptyBody}
          action={<Button onClick={openNew}>{copy.newNote}</Button>}
        />
      ) : shown.length === 0 && filtered ? (
        <EmptyState
          title={copy.noMatchTitle}
          body={copy.noMatchBody}
          action={
            <Button
              variant='outline'
              onClick={() => {
                setQuery('')
                onFiltersChange(noFilters)
              }}
            >
              {sharedCopy.clearFilters}
            </Button>
          }
        />
      ) : (
        <ul className='m-0 flex list-none flex-col gap-2.5 p-0'>
          {shown.map((n) => (
            <li key={n.id}>
              <NoteCard
                note={n}
                symbol={n.cik ? (symbolByCik[n.cik] ?? n.cik) : null}
                onEdit={() =>
                  setDialog({
                    id: n.id,
                    cik: n.cik,
                    start_date: n.start_date,
                    end_date: n.end_date,
                    body: n.body
                  })
                }
                onDelete={() => onDelete(n)}
              />
            </li>
          ))}
        </ul>
      )}

      <NoteDialog
        open={dialog != null}
        onOpenChange={(o) => !o && setDialog(null)}
        initial={dialog ?? emptyDraft(null, today)}
        companies={companies}
        today={today}
        onSave={onSave}
      />
    </div>
  )
}

export function NoteCard({
  note,
  symbol,
  onEdit,
  onDelete
}: {
  note: Note
  symbol: string | null
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <article className='border-border flex gap-3 border px-3 py-2.5'>
      <div className='min-w-0 flex-1'>
        <div className='mb-1 flex flex-wrap items-baseline gap-2'>
          <span className='tabular text-sm font-bold'>
            {formatDateRange(note.start_date, note.end_date)}
          </span>
          {symbol ? (
            <Badge variant='accent'>{symbol}</Badge>
          ) : (
            <Badge variant='default'>{copy.wholeMarket}</Badge>
          )}
          <span className='text-muted-foreground text-2xs'>
            {note.start_date === note.end_date
              ? sharedCopy.singleDate
              : sharedCopy.range}
          </span>
        </div>
        <ClampedText
          length={note.body.length}
          className='text-sm leading-[1.55]'
        >
          <SafeMarkdown>{note.body}</SafeMarkdown>
        </ClampedText>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant='outline'
            size='icon'
            aria-label={copy.actions}
            className='touch:size-11 flex-none self-start'
          >
            <EllipsisVertical aria-hidden='true' strokeWidth={1.5} />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end'>
          <DropdownMenuItem onSelect={onEdit}>{copy.edit}</DropdownMenuItem>
          <DropdownMenuItem onSelect={onDelete}>{copy.delete}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </article>
  )
}
