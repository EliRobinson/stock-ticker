'use client'

import { useCallback, useMemo } from 'react'
import { toast } from 'sonner'

import { useMarket } from '@/hooks/useMarket'
import { useDeleteNote, useNotes, useSaveNote } from '@/hooks/useNotes'
import type { Note } from '@/lib/api'
import { companyOptionsFromMarket } from '@/lib/company'
import { todayInNewYork } from '@/lib/dates'

import { notesCopy } from '../notes/copy'
import { NotesScreen } from '../notes/notes-screen'
import type { NotesFilters } from '../notes/notes-screen'
import { useUrlParams } from './url-state'

const FILTER_KEYS = {
  company: 'company',
  from: 'from',
  to: 'to',
  q: 'q'
} as const

// The Notes filters live in the URL (?company=&from=&to=&q=).
export function NotesContainer() {
  const notes = useNotes()
  const market = useMarket()
  const { save } = useSaveNote()
  const deleteNote = useDeleteNote()
  const { params, set } = useUrlParams()

  const filters: NotesFilters = useMemo(
    () => ({
      company: params.get(FILTER_KEYS.company),
      from: params.get(FILTER_KEYS.from),
      to: params.get(FILTER_KEYS.to),
      q: params.get(FILTER_KEYS.q) ?? ''
    }),
    [params]
  )
  const onFiltersChange = useCallback(
    (next: Partial<NotesFilters>) =>
      set(
        Object.fromEntries(
          Object.entries(next).map(([k, v]) => [k, v === '' ? null : v])
        ),
        { debounceMs: 'q' in next ? 250 : 0 }
      ),
    [set]
  )

  const companies = useMemo(
    () => companyOptionsFromMarket(market.data?.listings ?? []),
    [market.data]
  )
  const symbolByCik = useMemo(
    () =>
      Object.fromEntries(
        companies.map((c) => [c.cik, c.label.split(' · ')[0]!])
      ),
    [companies]
  )

  // Delete is immediate; Undo re-PUTs the same id inside the 5 s window
  // (system design §5), so undoing is a plain retry, not a new Note.
  const onDelete = (note: Note) => {
    deleteNote.mutate(note.id, {
      onError: () => toast.error(notesCopy.deleteFailed),
      onSuccess: () =>
        toast(notesCopy.deleted, {
          duration: 5000,
          action: {
            label: notesCopy.undo,
            onClick: () => {
              save(note).catch(() => toast.error(notesCopy.undoFailed))
            }
          }
        })
    })
  }

  return (
    <NotesScreen
      notes={notes.data ?? []}
      loading={notes.isPending}
      error={notes.isError}
      companies={companies}
      symbolByCik={symbolByCik}
      today={todayInNewYork()}
      filters={filters}
      onFiltersChange={onFiltersChange}
      onSave={save}
      onDelete={onDelete}
    />
  )
}
