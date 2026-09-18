'use client'

import { RouteError } from '@/components/shell/route-error'

export default function CompanyError(props: {
  error: Error & { digest?: string }
  retry: () => void
}) {
  return <RouteError {...props} />
}
