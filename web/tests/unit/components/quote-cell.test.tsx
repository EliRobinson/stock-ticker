import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { toRowViews } from '@/components/market/market-rows'
import { ChangeCell, QuoteCell } from '@/components/shared/cells'
import {
  marketBackfill,
  marketClosed,
  marketOpen,
  marketStale
} from '@/fixtures/market'

describe('Stale Quote rendering', () => {
  afterEach(cleanup)
  it('shows a stale price with its age inline and drops emphasis', () => {
    render(<QuoteCell price='142.18' ageMs={14 * 60_000} state='stale' />)
    const cell = screen.getByText('142.18', { exact: false })
    expect(cell).toHaveTextContent('142.18 · 14m old')
    expect(cell).toHaveClass('text-stale')
    expect(cell).toHaveAttribute('aria-description', 'Quote is 14m old')
  })

  it('shows a fresh price without an age', () => {
    render(<QuoteCell price='227.52' ageMs={12_000} state='fresh' />)
    expect(screen.getByText('227.52')).not.toHaveClass('text-stale')
  })

  it('never shows a stale change in the up or down color', () => {
    render(<ChangeCell pct='-0.41' abs='-1.71' stale />)
    const cell = screen.getByText('↓ −0.41% (−$1.71)')
    expect(cell).toHaveClass('text-stale')
    expect(cell).not.toHaveClass('text-down')
  })

  it('pairs sign, arrow and color for a fresh move', () => {
    render(<ChangeCell pct='1.23' abs='3.14' />)
    const cell = screen.getByText('↑ +1.23% (+$3.14)')
    expect(cell).toHaveClass('text-up')
    expect(cell).toHaveAttribute('data-direction', 'up')
  })

  it('flags Quotes past the staleness window only while the market is open', () => {
    expect(toRowViews(marketOpen).some((r) => r.stale)).toBe(false)
    expect(toRowViews(marketStale).every((r) => r.stale)).toBe(true)
    expect(toRowViews(marketClosed).some((r) => r.stale)).toBe(false)
    expect(toRowViews(marketClosed)[0]!.ageLabel).toBe('11h 12m')
  })

  it('marks marketBackfill rows without a completed backfill as pending', () => {
    const views = toRowViews(marketBackfill)
    expect(views.some((r) => r.backfillPending)).toBe(true)
    expect(
      views
        .filter((r) => r.backfillPending)
        .every((r) => r.backfill_completed_at == null)
    ).toBe(true)
  })
})
