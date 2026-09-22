import type { Metadata } from 'next'

import { CompanyContainer } from '@/components/containers/company-container'
import { AfterHydration } from '@/components/shared/after-hydration'

import CompanyLoading from './loading'

export const metadata: Metadata = { title: 'Company' }

export default async function CompanyPage({
  params
}: {
  params: Promise<{ cik: string }>
}) {
  const { cik } = await params
  return (
    <AfterHydration fallback={<CompanyLoading />}>
      <CompanyContainer cik={decodeURIComponent(cik)} />
    </AfterHydration>
  )
}
