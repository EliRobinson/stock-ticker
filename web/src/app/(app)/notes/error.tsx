'use client'

import { RouteError } from '@/components/shell/route-error'

export default function NotesError(props: {
  error: Error & { digest?: string }
  retry: () => void
}) {
  return <RouteError {...props} />
}
