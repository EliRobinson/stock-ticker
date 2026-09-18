import { describe, expect, it } from 'vitest'
import { barsKeys } from '@/hooks/useBars'

describe('barsKeys.list', () => {
  it('produces the same key whether timeframe is omitted or given as the default', () => {
    const omitted = barsKeys.list('AAPL', {})
    const explicit = barsKeys.list('AAPL', { timeframe: '1d' })
    expect(omitted).toEqual(explicit)
  })

  it('produces the same key whether from/to are omitted or explicitly undefined', () => {
    const omitted = barsKeys.list('AAPL', {})
    const explicitUndefined = barsKeys.list('AAPL', {
      from: undefined,
      to: undefined
    })
    expect(omitted).toEqual(explicitUndefined)
  })

  it('produces a different key for a different symbol', () => {
    expect(barsKeys.list('AAPL', {})).not.toEqual(barsKeys.list('MSFT', {}))
  })

  it('produces a different key for a different date range', () => {
    expect(barsKeys.list('AAPL', { from: '2024-01-01' })).not.toEqual(
      barsKeys.list('AAPL', { from: '2023-01-01' })
    )
  })
})
