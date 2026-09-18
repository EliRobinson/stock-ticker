'use client'

import { NotesScreen } from './notes-screen'

const noop = () => {}

export function NotesSkeleton() {
  return (
    <NotesScreen
      notes={[]}
      loading
      companies={[]}
      symbolByCik={{}}
      today=''
      onSave={noop}
      onDelete={noop}
    />
  )
}
