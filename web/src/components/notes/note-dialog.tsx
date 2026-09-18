'use client'

import { useForm } from '@tanstack/react-form'
import { CalendarDays } from 'lucide-react'
import { useId, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
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
import { cn } from '@/lib/utils'

import { noteDialogCopy as copy } from '../company/copy'
import { formatDate, formatDateRange } from '../shared/format'

export interface NoteDraft {
  id?: string
  cik: string | null
  start_date: string
  end_date: string
  body: string
}

function Slotless({
  asChild,
  ...props
}: React.ComponentProps<'div'> & { asChild?: boolean }) {
  if (asChild && props.children) return <>{props.children}</>
  return <div {...props} />
}

export interface CompanyOption {
  cik: string
  label: string
}

const WHOLE_MARKET = '__market__'
const MIN_DATE = '1990-01-01'

function maxDate(today: string) {
  const d = new Date(`${today}T12:00:00Z`)
  d.setUTCFullYear(d.getUTCFullYear() + 1)
  return d.toISOString().slice(0, 10)
}

const toIso = (d: Date) =>
  new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
    .toISOString()
    .slice(0, 10)
const fromIso = (s: string) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y!, (m ?? 1) - 1, d ?? 1)
}

// Validation mirrors the API's PUT /notes/{id} rules (system design §5), so a
// Note that passes here is not rejected by the server for its shape.
export function validateNote(draft: NoteDraft, today: string) {
  const errors: Partial<Record<'body' | 'start_date' | 'end_date', string>> = {}
  const body = draft.body.trim()
  if (body.length === 0) errors.body = copy.errors.bodyEmpty
  else if (body.length > 10_000) errors.body = copy.errors.bodyLong
  if (!draft.start_date) errors.start_date = copy.errors.startMissing
  else if (draft.start_date < MIN_DATE || draft.start_date > maxDate(today)) {
    errors.start_date = copy.errors.outOfRange
  }
  if (draft.end_date) {
    if (draft.start_date && draft.end_date < draft.start_date) {
      errors.end_date = copy.errors.endBefore
    } else if (draft.end_date > maxDate(today)) {
      errors.end_date = copy.errors.outOfRange
    }
  }
  return errors
}

function DateField({
  id,
  label,
  value,
  onChange,
  error,
  optional = false
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  optional?: boolean
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
            className='bg-secondary text-md tabular aria-invalid:border-destructive justify-between font-sans font-normal'
          >
            {value ? formatDate(value) : optional ? '—' : copy.pickDate}
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
  initial,
  companies,
  lockCompany = false,
  origin,
  today,
  onSave,
  saveError = null
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  initial: NoteDraft
  companies?: CompanyOption[]
  lockCompany?: boolean
  origin?: 'range' | 'date'
  today: string
  onSave: (draft: NoteDraft) => void
  saveError?: string | null
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='touch:bottom-0 touch:top-auto touch:translate-y-0 bg-background gap-2.5 p-3.5 shadow-lg sm:max-w-[440px]'>
        {open && (
          <NoteForm
            initial={initial}
            companies={companies}
            lockCompany={lockCompany}
            origin={origin}
            today={today}
            onSave={onSave}
            onCancel={() => onOpenChange(false)}
            saveError={saveError}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

export function NoteForm({
  initial,
  companies = [],
  lockCompany,
  origin,
  today,
  onSave,
  onCancel,
  saveError,
  inDialog = true
}: {
  inDialog?: boolean
  initial: NoteDraft
  companies?: CompanyOption[]
  lockCompany?: boolean
  origin?: 'range' | 'date'
  today: string
  onSave: (draft: NoteDraft) => void
  onCancel: () => void
  saveError?: string | null
}) {
  const id = useId()
  const form = useForm({
    defaultValues: initial,
    validators: {
      onSubmit: ({ value }) => {
        const errors = validateNote(value, today)
        return Object.keys(errors).length ? { fields: errors } : undefined
      }
    },
    onSubmit: ({ value }) =>
      onSave({
        ...value,
        body: value.body.trim(),
        end_date: value.end_date || value.start_date
      })
  })
  const companyLabel = companies.find((c) => c.cik === initial.cik)?.label
  const Header = inDialog ? DialogHeader : 'div'
  const Title = inDialog ? DialogTitle : 'h2'
  const Description = inDialog ? DialogDescription : Slotless

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        form.handleSubmit().catch(() => {})
      }}
      className='flex flex-col gap-2.5'
    >
      <Header className='flex flex-col gap-1 text-left'>
        <Title className='font-heading m-0 text-[20px] font-semibold leading-tight'>
          {initial.id ? copy.editTitle : copy.newTitle}
        </Title>
        {lockCompany ? (
          <Description asChild>
            <div className='flex flex-wrap items-center gap-2 text-xs'>
              <Badge variant='accent'>{companyLabel ?? copy.wholeMarket}</Badge>
              <Badge variant='default' className='tabular'>
                {formatDateRange(
                  initial.start_date,
                  initial.end_date || initial.start_date
                )}
              </Badge>
              {origin && (
                <span className='text-muted-foreground'>
                  {origin === 'range' ? copy.fromRange : copy.fromDate}
                </span>
              )}
            </div>
          </Description>
        ) : (
          <Description className='sr-only'>{copy.newTitle}</Description>
        )}
      </Header>

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

      {!lockCompany && (
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
                value={field.state.value}
                onChange={field.handleChange}
                error={field.state.meta.errors[0] as string | undefined}
                optional
              />
            )}
          </form.Field>
        </div>
      )}

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
              className={cn('touch:min-h-12')}
            >
              {submitting ? copy.saving : copy.save}
            </Button>
          )}
        </form.Subscribe>
      </div>
    </form>
  )
}
