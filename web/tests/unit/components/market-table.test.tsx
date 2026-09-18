import type { SortingState } from '@tanstack/react-table'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import { MarketScreen } from '@/components/market/market-screen'
import { TooltipProvider } from '@/components/ui/tooltip'
import { marketOpen } from '@/fixtures/market'

import { installBrowserMocks } from './browser-mocks'

function Harness() {
  const [query, setQuery] = useState('')
  const [sector, setSector] = useState<string | null>(null)
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'symbol', desc: false }
  ])
  return (
    <TooltipProvider>
      <MarketScreen
        market={marketOpen}
        query={query}
        onQueryChange={setQuery}
        sector={sector}
        onSectorChange={setSector}
        sorting={sorting}
        onSortingChange={setSorting}
        onOpenCompany={() => {}}
      />
    </TooltipProvider>
  )
}

const firstSymbol = () => {
  const region = screen.getByRole('region', { name: 'Constituent list' })
  const rows = within(region).getAllByRole('row').slice(1)
  return within(rows[0]!).getAllByRole('cell')[0]!.textContent
}

describe('Market table', () => {
  afterEach(cleanup)
  beforeAll(installBrowserMocks)

  it('sorts by symbol by default and flips on a header click', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(firstSymbol()).toBe('AAPL')
    const header = screen.getByRole('columnheader', { name: /symbol/i })
    expect(header).toHaveAttribute('aria-sort', 'ascending')

    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(firstSymbol()).toBe('XOM')
  })

  it('sorts by day change when that header is clicked', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const header = screen.getByRole('columnheader', { name: /day change/i })
    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(firstSymbol()).toBe('LLY')
  })

  it('filters rows by symbol or Company name as you type', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(
      screen.getByRole('searchbox', { name: 'Search Listings' }),
      'nvid'
    )
    expect(await screen.findByText('60 Listings · 1 shown')).toBeInTheDocument()
    expect(firstSymbol()).toBe('NVDA')
  })

  it('shows the no-match state and clears it', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(
      screen.getByRole('searchbox', { name: 'Search Listings' }),
      'zzap'
    )
    expect(
      await screen.findByText('No Listings match “zzap”')
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(
      await screen.findByText('60 Listings · 60 shown')
    ).toBeInTheDocument()
  })
})
