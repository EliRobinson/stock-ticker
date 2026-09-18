'use client'

import { NotesScreen, noFilters } from './notes-screen'

const noop = () => {}
const noSave = async () => {}

export function NotesSkeleton() {
  return (
    <NotesScreen
      notes={[]}
      loading
      companies={[]}
      symbolByCik={{}}
      today=''
      filters={noFilters}
      onFiltersChange={noop}
      onSave={noSave}
      onDelete={noop}
    />
  )
}
