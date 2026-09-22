import type { Metadata } from 'next'

import { MarketContainer } from '@/components/containers/market-container'
import { AfterHydration } from '@/components/shared/after-hydration'

import MarketLoading from './loading'

export const metadata: Metadata = { title: 'Market' }

export default function MarketPage() {
  return (
    <AfterHydration fallback={<MarketLoading />}>
      <MarketContainer />
    </AfterHydration>
  )
}
