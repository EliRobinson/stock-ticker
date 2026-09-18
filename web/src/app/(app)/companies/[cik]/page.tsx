import type { Metadata } from 'next'

import { CompanyContainer } from '@/components/containers/company-container'

export const metadata: Metadata = { title: 'Company' }

export default async function CompanyPage({
  params
}: {
  params: Promise<{ cik: string }>
}) {
  const { cik } = await params
  return <CompanyContainer cik={decodeURIComponent(cik)} />
}
