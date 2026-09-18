'use client'

import { useForm } from '@tanstack/react-form'
import { CalendarDays } from 'lucide-react'
import { useEffect, useId, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
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
import { Textarea } from '@/components/ui/textarea'
import type { CompanyOption } from '@/lib/company'
import { shiftDate } from '@/lib/dates'
import { formatDateShort } from '@/lib/format'
import type { NoteDraft } from '@/hooks/useNotes'

import { noteDialogCopy as copy } from './copy'

export type { NoteDraft }

const WHOLE_MARKET = '__market__'
const MIN_DATE = '1990-01-01'

/** A blank Note for a Company (or the whole market) on one date. */
export function emptyDraft(cik: string | null, date: string): NoteDraft {
  return { cik, start_date: date, end_date: date, body: '' }
}

const toIso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const fromIso = (s: string) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y!, (m ?? 1) - 1, d ?? 1)
}

// The API's PUT /notes/{id} rules (system design §5), so a Note that passes
// here is not rejected by the server for its shape.
export function validateNote(draft: NoteDraft, today: string) {
  const errors: Partial<Record<'body' | 'start_date' | 'end_date', string>> = {}
  const max = shiftDate(today, { years: 1 })
  const body = draft.body.trim()
  if (body.length === 0) errors.body = copy.errors.bodyEmpty
  else if (body.length > 10_000) errors.body = copy.errors.bodyLong
  if (!draft.start_date) errors.start_date = copy.errors.startMissing
  else if (draft.start_date < MIN_DATE || draft.start_date > max)
    errors.start_date = copy.errors.outOfRange
  if (draft.end_date) {
    if (draft.start_date && draft.end_date < draft.start_date)
      errors.end_date = copy.errors.endBefore
    else if (draft.end_date > max) errors.end_date = copy.errors.outOfRange
  }
  return errors
}

function DateField({
  id,
  label,
  value,
  onChange,
  error
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className='flex min-w-0 flex-1 flex-col gap-[5px]'>
      <Label htmlFor={id} className='text-muted-foreground text-xs font-normal'>
        {label}
      </Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            type='button'
            variant='outline'
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-error` : undefined}
            className='bg-secondary border-input text-md tabular aria-invalid:border-destructive justify-between font-sans font-normal'
          >
            {value ? formatDateShort(value) : copy.pickDate}
            <CalendarDays
              aria-hidden='true'
              className='text-muted-foreground'
              strokeWidth={1.5}
            />
          </Button>
        </PopoverTrigger>
        <PopoverContent align='start' className='w-auto p-0'>
          <Calendar
            mode='single'
            selected={value ? fromIso(value) : undefined}
            defaultMonth={value ? fromIso(value) : undefined}
            captionLayout='dropdown'
            onSelect={(d) => {
              onChange(d ? toIso(d) : '')
              setOpen(false)
            }}
          />
        </PopoverContent>
      </Popover>
      {error && (
        <p id={`${id}-error`} className='text-destructive text-xs'>
          {error}
        </p>
      )}
    </div>
  )
}

export function NoteDialog({
  open,
  onOpenChange,
  ...form
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
} & Omit<NoteFormProps, 'onCancel' | 'onSaved'>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='touch:bottom-0 touch:top-auto touch:translate-y-0 bg-background gap-2.5 p-3.5 shadow-lg sm:max-w-[440px]'>
        {open && (
          <NoteForm
            {...form}
            onCancel={() => onOpenChange(false)}
            onSaved={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

export interface NoteFormProps {
  initial: NoteDraft
  companies?: CompanyOption[]
  /** The Company is set by where the Note was started (a Company chart);
   * the dates stay editable. */
  lockCompany?: boolean
  origin?: 'range' | 'date'
  today: string
  onSave: (draft: NoteDraft) => Promise<unknown>
  onCancel: () => void
  onSaved?: () => void
  inDialog?: boolean
}

// The form stays open, with its text, until the save succeeds. A failed
// save shows why and keeps everything typed.
export function NoteForm({
  initial,
  companies = [],
  lockCompany = false,
  origin,
  today,
  onSave,
  onCancel,
  onSaved,
  inDialog = true
}: NoteFormProps) {
  const id = useId()
  const [saveError, setSaveError] = useState<string | null>(null)
  const form = useForm({
    defaultValues: initial,
    validators: {
      onSubmit: ({ value }) => {
        const errors = validateNote(value, today)
        return Object.keys(errors).length ? { fields: errors } : undefined
      }
    },
    onSubmit: async ({ value }) => {
      setSaveError(null)
      try {
        await onSave({
          ...value,
          body: value.body.trim(),
          end_date: value.end_date || value.start_date
        })
        onSaved?.()
      } catch {
        setSaveError(copy.saveFailed)
      }
    }
  })
  // A new starting point (another chart date, another Note to edit) starts
  // a fresh form.
  const initialKey = `${initial.id}|${initial.cik}|${initial.start_date}|${initial.end_date}`
  const [seenKey, setSeenKey] = useState(initialKey)
  if (seenKey !== initialKey) {
    setSeenKey(initialKey)
    setSaveError(null)
  }
  useEffect(() => {
    form.reset(initial)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialKey])
  const companyLabel = companies.find((c) => c.cik === initial.cik)?.label

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        form.handleSubmit().catch(() => {})
      }}
      className='flex flex-col gap-2.5'
    >
      <div className='flex flex-col gap-1 text-left'>
        {inDialog ? (
          <DialogTitle className='text-[20px] leading-tight'>
            {initial.id ? copy.editTitle : copy.newTitle}
          </DialogTitle>
        ) : (
          <h2 className='font-heading m-0 text-[20px] font-semibold leading-tight'>
            {initial.id ? copy.editTitle : copy.newTitle}
          </h2>
        )}
        {lockCompany ? (
          <div className='flex flex-wrap items-center gap-2 text-xs'>
            <Badge variant='accent'>{companyLabel ?? copy.wholeMarket}</Badge>
            {origin && (
              <span className='text-muted-foreground'>
                {origin === 'range' ? copy.fromRange : copy.fromDate}
              </span>
            )}
          </div>
        ) : null}
        {inDialog && (
          <DialogDescription className='sr-only'>
            {copy.newTitle}
          </DialogDescription>
        )}
      </div>

      {!lockCompany && (
        <form.Field name='cik'>
          {(field) => (
            <div className='flex flex-col gap-[5px]'>
              <Label
                htmlFor={`${id}-cik`}
                className='text-muted-foreground text-xs font-normal'
              >
                {copy.company}
              </Label>
              <Select
                value={field.state.value ?? WHOLE_MARKET}
                onValueChange={(v) =>
                  field.handleChange(v === WHOLE_MARKET ? null : v)
                }
              >
                <SelectTrigger id={`${id}-cik`} className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={WHOLE_MARKET}>
                    {copy.wholeMarket}
                  </SelectItem>
                  {companies.map((c) => (
                    <SelectItem key={c.cik} value={c.cik}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </form.Field>
      )}

      <div className='flex gap-2.5 max-sm:flex-col'>
        <form.Field name='start_date'>
          {(field) => (
            <DateField
              id={`${id}-start`}
              label={copy.start}
              value={field.state.value}
              onChange={field.handleChange}
              error={field.state.meta.errors[0] as string | undefined}
            />
          )}
        </form.Field>
        <form.Field name='end_date'>
          {(field) => (
            <DateField
              id={`${id}-end`}
              label={copy.end}
              value={field.state.value ?? ''}
              onChange={field.handleChange}
              error={field.state.meta.errors[0] as string | undefined}
            />
          )}
        </form.Field>
      </div>

      <form.Field name='body'>
        {(field) => {
          const error = field.state.meta.errors[0] as string | undefined
          return (
            <div className='flex flex-col gap-[5px]'>
              <Label
                htmlFor={`${id}-body`}
                className='text-muted-foreground text-xs font-normal'
              >
                {copy.body}
              </Label>
              <Textarea
                id={`${id}-body`}
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                rows={5}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? `${id}-body-error` : undefined}
                className='min-h-26'
              />
              {error && (
                <p id={`${id}-body-error`} className='text-destructive text-xs'>
                  {error}
                </p>
              )}
            </div>
          )
        }}
      </form.Field>

      {saveError && (
        <p role='alert' className='text-destructive text-xs'>
          {saveError}
        </p>
      )}

      <div className='flex flex-row justify-end gap-2'>
        <Button type='button' variant='outline' onClick={onCancel}>
          {copy.cancel}
        </Button>
        <form.Subscribe selector={(s) => s.isSubmitting}>
          {(submitting) => (
            <Button
              type='submit'
              disabled={submitting}
              className='touch:min-h-12'
            >
              {submitting ? copy.saving : copy.save}
            </Button>
          )}
        </form.Subscribe>
      </div>
    </form>
  )
}
