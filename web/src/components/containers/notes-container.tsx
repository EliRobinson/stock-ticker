'use client'

import { useMemo } from 'react'
import { toast } from 'sonner'

import { useMarket } from '@/hooks/useMarket'
import {
  createNoteId,
  useDeleteNote,
  useNotes,
  usePutNote
} from '@/hooks/useNotes'
import type { Note } from '@/lib/api'

import { noteDialogCopy } from '../company/copy'
import { notesCopy } from '../notes/copy'
import { NotesScreen } from '../notes/notes-screen'
import { todayInNewYork } from './today'

export function NotesContainer() {
  const notes = useNotes()
  const market = useMarket()
  const putNote = usePutNote()
  const deleteNote = useDeleteNote()

  const { companies, symbolByCik } = useMemo(() => {
    const bySymbol = new Map<
      string,
      { cik: string; label: string; symbol: string }
    >()
    for (const r of market.data?.listings ?? []) {
      if (!bySymbol.has(r.cik)) {
        bySymbol.set(r.cik, {
          cik: r.cik,
          label: `${r.symbol} · ${r.name}`,
          symbol: r.symbol
        })
      }
    }
    const list = [...bySymbol.values()].sort((a, b) =>
      a.symbol.localeCompare(b.symbol)
    )
    return {
      companies: list.map(({ cik, label }) => ({ cik, label })),
      symbolByCik: Object.fromEntries(list.map((c) => [c.cik, c.symbol]))
    }
  }, [market.data])

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
            onClick: () =>
              putNote.mutate(
                {
                  id: note.id,
                  cik: note.cik,
                  start_date: note.start_date,
                  end_date: note.end_date,
                  body: note.body
                },
                { onError: () => toast.error(notesCopy.undoFailed) }
              )
          }
        })
    })
  }

  return (
    <NotesScreen
      notes={notes.data?.pages.flatMap((p) => p.items) ?? []}
      loading={notes.isPending}
      error={notes.isError}
      companies={companies}
      symbolByCik={symbolByCik}
      today={todayInNewYork()}
      saveError={putNote.isError ? noteDialogCopy.saveFailed : null}
      onSave={(draft) =>
        putNote.mutate({
          id: draft.id ?? createNoteId(),
          cik: draft.cik,
          start_date: draft.start_date,
          end_date: draft.end_date,
          body: draft.body
        })
      }
      onDelete={onDelete}
    />
  )
}
