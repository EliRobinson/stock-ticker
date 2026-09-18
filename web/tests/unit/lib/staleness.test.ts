import { describe, expect, it } from 'vitest'
import {
  STALE_THRESHOLD_MS,
  getMarketStatus,
  getQuoteAgeMs,
  getQuoteStaleness,
  isQuoteStale,
  pollIntervalMs,
  type MarketClockLike
} from '@/lib/staleness'

const SERVER_TIME = '2024-06-03T15:00:00.000Z'

function clock(overrides: Partial<MarketClockLike>): MarketClockLike {
  return {
    is_open: true,
    next_open: '2024-06-04T13:30:00.000Z',
    next_close: '2024-06-03T20:00:00.000Z',
    ...overrides
  }
}

describe('getQuoteAgeMs', () => {
  it('is null for a null observation', () => {
    expect(getQuoteAgeMs(null, SERVER_TIME)).toBeNull()
  })

  it('returns the elapsed milliseconds since observed_at', () => {
    const observedAt = '2024-06-03T14:59:00.000Z'
    expect(getQuoteAgeMs(observedAt, SERVER_TIME)).toBe(60 * 1000)
  })

  it('clamps a future observed_at to 0', () => {
    const observedAt = '2024-06-03T15:01:00.000Z'
    expect(getQuoteAgeMs(observedAt, SERVER_TIME)).toBe(0)
  })

  it('is null for an unparseable observed_at', () => {
    expect(getQuoteAgeMs('not-a-date', SERVER_TIME)).toBeNull()
  })

  it('is null for an unparseable server_time', () => {
    expect(getQuoteAgeMs('2024-06-03T14:59:00.000Z', 'not-a-date')).toBeNull()
  })
})

describe('isQuoteStale', () => {
  it('is never stale while the market is closed, regardless of age', () => {
    expect(isQuoteStale(null, SERVER_TIME, false)).toBe(false)
    const veryOld = '2020-01-01T00:00:00.000Z'
    expect(isQuoteStale(veryOld, SERVER_TIME, false)).toBe(false)
  })

  it('is stale while open with no observation at all', () => {
    expect(isQuoteStale(null, SERVER_TIME, true)).toBe(true)
  })

  it('is stale while open with an unparseable observed_at', () => {
    expect(isQuoteStale('not-a-date', SERVER_TIME, true)).toBe(true)
  })

  it('is fresh right at the threshold while open', () => {
    const observedAt = new Date(
      new Date(SERVER_TIME).getTime() - STALE_THRESHOLD_MS
    ).toISOString()
    expect(isQuoteStale(observedAt, SERVER_TIME, true)).toBe(false)
  })

  it('is stale just past the threshold while open', () => {
    const observedAt = new Date(
      new Date(SERVER_TIME).getTime() - STALE_THRESHOLD_MS - 1
    ).toISOString()
    expect(isQuoteStale(observedAt, SERVER_TIME, true)).toBe(true)
  })

  it('is fresh for a recent observation while open', () => {
    const observedAt = '2024-06-03T14:59:30.000Z'
    expect(isQuoteStale(observedAt, SERVER_TIME, true)).toBe(false)
  })
})

describe('getQuoteStaleness', () => {
  it('combines age and staleness', () => {
    const observedAt = '2024-06-03T14:59:00.000Z'
    expect(getQuoteStaleness(observedAt, SERVER_TIME, true)).toEqual({
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
    expect(getMarketStatus(clock({ is_open: true }))).toBe('open')
  })

  it('is closed when the clock says closed', () => {
    expect(getMarketStatus(clock({ is_open: false }))).toBe('closed')
  })
})

describe('pollIntervalMs', () => {
  it('polls every 10s with no clock', () => {
    expect(pollIntervalMs(null, SERVER_TIME)).toBe(10 * 1000)
  })

  it('polls every 10s while open, with plenty of time before close', () => {
    const c = clock({
      is_open: true,
      next_close: '2024-06-03T20:00:00.000Z'
    })
    expect(pollIntervalMs(c, SERVER_TIME)).toBe(10 * 1000)
  })

  it('caps the open interval at the time remaining before close', () => {
    const c = clock({
      is_open: true,
      next_close: '2024-06-03T15:00:04.000Z'
    })
    expect(pollIntervalMs(c, SERVER_TIME)).toBe(4000)
  })

  it('floors the open interval at 1s when close has already passed', () => {
    const c = clock({
      is_open: true,
      next_close: '2024-06-03T14:59:00.000Z'
    })
    expect(pollIntervalMs(c, SERVER_TIME)).toBe(1000)
  })

  it('polls every 5min while closed, with plenty of time before open', () => {
    const c = clock({
      is_open: false,
      next_open: '2024-06-04T13:30:00.000Z'
    })
    expect(pollIntervalMs(c, SERVER_TIME)).toBe(5 * 60 * 1000)
  })

  it('caps the closed interval at the time remaining before open', () => {
    const c = clock({
      is_open: false,
      next_open: '2024-06-03T15:00:30.000Z'
    })
    expect(pollIntervalMs(c, SERVER_TIME)).toBe(30 * 1000)
  })

  it('floors the closed interval at 1s when open has already passed', () => {
    const c = clock({
      is_open: false,
      next_open: '2024-06-03T14:59:00.000Z'
    })
    expect(pollIntervalMs(c, SERVER_TIME)).toBe(1000)
  })
})
