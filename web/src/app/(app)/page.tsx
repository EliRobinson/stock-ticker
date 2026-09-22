import type { Metadata } from 'next'
import { Suspense } from 'react'

import { MarketContainer } from '@/components/containers/market-container'
import { AfterHydration } from '@/components/shared/after-hydration'

import MarketLoading from './loading'

export const metadata: Metadata = { title: 'Market' }

export default function MarketPage() {
  return (
    <Suspense fallback={<MarketLoading />}>
      <AfterHydration fallback={<MarketLoading />}>
        <MarketContainer />
      </AfterHydration>
    </Suspense>
  )
}
