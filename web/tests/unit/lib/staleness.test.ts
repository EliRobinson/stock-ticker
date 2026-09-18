import { describe, expect, it } from 'vitest'
import {
  STALE_THRESHOLD_MS,
  getMarketStatus,
  getQuoteAgeMs,
  getQuoteStaleness,
  isQuoteStale
} from '@/lib/staleness'

const SERVER_TIME = '2024-06-03T15:00:00.000Z'

describe('getQuoteAgeMs', () => {
  it('returns 0 for a null observation', () => {
    expect(getQuoteAgeMs(null, SERVER_TIME)).toBe(0)
  })

  it('returns the elapsed milliseconds since observed_at', () => {
    const observedAt = '2024-06-03T14:59:00.000Z'
    expect(getQuoteAgeMs(observedAt, SERVER_TIME)).toBe(60 * 1000)
  })

  it('clamps a future observed_at to 0', () => {
    const observedAt = '2024-06-03T15:01:00.000Z'
    expect(getQuoteAgeMs(observedAt, SERVER_TIME)).toBe(0)
  })
})

describe('isQuoteStale', () => {
  it('is stale when there has never been an observation', () => {
    expect(isQuoteStale(null, SERVER_TIME)).toBe(true)
  })

  it('is fresh right at the threshold', () => {
    const observedAt = new Date(
      new Date(SERVER_TIME).getTime() - STALE_THRESHOLD_MS
    ).toISOString()
    expect(isQuoteStale(observedAt, SERVER_TIME)).toBe(false)
  })

  it('is stale just past the threshold', () => {
    const observedAt = new Date(
      new Date(SERVER_TIME).getTime() - STALE_THRESHOLD_MS - 1
    ).toISOString()
    expect(isQuoteStale(observedAt, SERVER_TIME)).toBe(true)
  })

  it('is fresh for a recent observation', () => {
    const observedAt = '2024-06-03T14:59:30.000Z'
    expect(isQuoteStale(observedAt, SERVER_TIME)).toBe(false)
  })
})

describe('getQuoteStaleness', () => {
  it('combines age and staleness', () => {
    const observedAt = '2024-06-03T14:59:00.000Z'
    expect(getQuoteStaleness(observedAt, SERVER_TIME)).toEqual({
      ageMs: 60 * 1000,
      isStale: false
    })
  })
})

describe('getMarketStatus', () => {
  it('is unknown with no clock', () => {
    expect(getMarketStatus(null)).toBe('unknown')
  })

  it('is open when the clock says open', () => {
    expect(getMarketStatus({ is_open: true })).toBe('open')
  })

  it('is closed when the clock says closed', () => {
    expect(getMarketStatus({ is_open: false })).toBe('closed')
  })
})
