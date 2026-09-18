'use client'

import { MarketScreen } from './market-screen'

const noop = () => {}

export function MarketScreenSkeleton() {
  return (
    <MarketScreen
      market={null}
      loading
      query=''
      onQueryChange={noop}
      sector={null}
      onSectorChange={noop}
      sorting={[]}
      onSortingChange={noop}
      onOpenCompany={noop}
    />
  )
}
