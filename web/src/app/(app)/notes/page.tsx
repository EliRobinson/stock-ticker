import type { Metadata } from 'next'

import { NotesContainer } from '@/components/containers/notes-container'
import { AfterHydration } from '@/components/shared/after-hydration'

import NotesLoading from './loading'

export const metadata: Metadata = { title: 'Notes' }

export default function NotesPage() {
  return (
    <AfterHydration fallback={<NotesLoading />}>
      <NotesContainer />
    </AfterHydration>
  )
}
