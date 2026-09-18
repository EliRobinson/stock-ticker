'use client'

import { EllipsisVertical } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ComponentProps } from 'react'
import type { DateRange } from 'react-day-picker'
import { Streamdown } from 'streamdown'

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
import { cn } from '@/lib/utils'

import { EmptyState, SkeletonBar, StatusAlert } from '../shared/feedback'
import { formatDateRange } from '../shared/format'
import { notesCopy as copy } from './copy'
import { NoteDialog } from './note-dialog'
import type { CompanyOption, NoteDraft } from './note-dialog'

const ALL = '__all__'
const MARKET = '__market__'

// Note bodies are the user's markdown: raw HTML and images off, https links only.
const safeMarkdown: Partial<ComponentProps<typeof Streamdown>> = {
  skipHtml: true,
  disallowedElements: ['img'],
  urlTransform: (url: string) => (url.startsWith('https://') ? url : null),
  controls: false
}

export interface NotesScreenProps {
  notes: Note[]
  loading?: boolean
  error?: boolean
  companies: CompanyOption[]
  symbolByCik: Record<string, string>
  today: string
  onSave: (draft: NoteDraft) => void
  onDelete: (note: Note) => void
  saveError?: string | null
  initialDialog?: NoteDraft | null
  initialQuery?: string
}

export function NotesScreen({
  notes,
  loading = false,
  error = false,
  companies,
  symbolByCik,
  today,
  onSave,
  onDelete,
  saveError = null,
  initialDialog = null,
  initialQuery = ''
}: NotesScreenProps) {
  const [company, setCompany] = useState<string>(ALL)
  const [range, setRange] = useState<DateRange | undefined>()
  const [query, setQuery] = useState(initialQuery)
  const [dialog, setDialog] = useState<NoteDraft | null>(initialDialog)

  const iso = (d?: Date) =>
    d
      ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      : null
  const from = iso(range?.from)
  const to = iso(range?.to ?? range?.from)

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return [...notes]
      .filter((n) =>
        company === ALL
          ? true
          : company === MARKET
            ? n.cik == null
            : n.cik === company
      )
      .filter((n) =>
        from && to ? n.end_date >= from && n.start_date <= to : true
      )
      .filter((n) => (q ? n.body.toLowerCase().includes(q) : true))
      .sort((a, b) => b.start_date.localeCompare(a.start_date))
  }, [notes, company, from, to, query])

  const filtered = company !== ALL || from != null || query.trim() !== ''
  const clear = () => {
    setCompany(ALL)
    setRange(undefined)
    setQuery('')
  }

  return (
    <div className='flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3.5'>
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
          onClick={() =>
            setDialog({ cik: null, start_date: today, end_date: '', body: '' })
          }
        >
          {copy.newNote}
        </Button>
      </div>

      {error ? (
        <StatusAlert title={copy.errorTitle}>{copy.errorBody}</StatusAlert>
      ) : (
        <div className='flex flex-wrap gap-2 max-sm:flex-col'>
          <Select value={company} onValueChange={setCompany}>
            <SelectTrigger
              aria-label={copy.companyFilter}
              className='w-47.5 max-sm:w-full'
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{copy.allCompanies}</SelectItem>
              <SelectItem value={MARKET}>{copy.wholeMarket}</SelectItem>
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
                className='tabular font-sans text-sm font-normal max-sm:w-full'
              >
                {from && to ? formatDateRange(from, to) : copy.anyDate}
              </Button>
            </PopoverTrigger>
            <PopoverContent align='start' className='w-auto p-0'>
              <Calendar
                mode='range'
                selected={range}
                onSelect={setRange}
                captionLayout='dropdown'
              />
              {range && (
                <div className='border-border border-t p-2'>
                  <Button
                    variant='ghost'
                    size='sm'
                    onClick={() => setRange(undefined)}
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
            className='w-50 max-sm:w-full'
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
          action={
            <Button
              onClick={() =>
                setDialog({
                  cik: null,
                  start_date: today,
                  end_date: '',
                  body: ''
                })
              }
            >
              {copy.newNote}
            </Button>
          }
        />
      ) : shown.length === 0 && filtered ? (
        <EmptyState
          title={copy.noMatchTitle}
          body={copy.noMatchBody}
          action={
            <Button variant='outline' onClick={clear}>
              {copy.clearFilters}
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
        initial={
          dialog ?? { cik: null, start_date: today, end_date: '', body: '' }
        }
        companies={companies}
        today={today}
        saveError={saveError}
        onSave={(draft) => {
          onSave(draft)
          setDialog(null)
        }}
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
  const [open, setOpen] = useState(false)
  const long = note.body.length > 160
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
            {note.start_date === note.end_date ? copy.singleDate : copy.range}
          </span>
        </div>
        <div
          className={cn(
            'text-sm leading-[1.55] [&_p]:m-0',
            !open && 'line-clamp-3'
          )}
        >
          <Streamdown {...safeMarkdown}>{note.body}</Streamdown>
        </div>
        {long && (
          <Button
            variant='ghost'
            size='xs'
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className='mt-1 px-0 font-sans text-xs font-normal'
          >
            {open ? copy.showLess : copy.readMore}
          </Button>
        )}
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
