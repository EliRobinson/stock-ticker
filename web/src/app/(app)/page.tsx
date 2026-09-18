import type { Metadata } from 'next'
import { Suspense } from 'react'

import { MarketContainer } from '@/components/containers/market-container'

import MarketLoading from './loading'

export const metadata: Metadata = { title: 'Market' }

export default function MarketPage() {
  return (
    <Suspense fallback={<MarketLoading />}>
      <MarketContainer />
    </Suspense>
  )
}
