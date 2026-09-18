import type { Metadata } from 'next'

import { NotesContainer } from '@/components/containers/notes-container'

export const metadata: Metadata = { title: 'Notes' }

export default function NotesPage() {
  return <NotesContainer />
}
