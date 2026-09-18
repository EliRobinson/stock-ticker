import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { Suspense } from 'react'

import { StatesBoard } from '@/components/dev/states-board'

export const metadata: Metadata = { title: 'State board' }

// Dev-only: every state from fixtures, for checking against the Claude Design
// board and for PR screenshots. Production builds answer 404.
export default function StatesPage() {
  if (process.env.NODE_ENV === 'production') notFound()
  return (
    <Suspense>
      <StatesBoard />
    </Suspense>
  )
}
