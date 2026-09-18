import { describe, expect, it } from 'vitest'

import {
  companyOption,
  companyOptionsFromMarket,
  primaryListing
} from '@/lib/company'
import { shiftDate, todayInNewYork, weekdaysBetween } from '@/lib/dates'
import { companyHref, ROUTES } from '@/lib/routes'

describe('dates', () => {
  it('reads today in New York, not UTC', () => {
    expect(todayInNewYork(new Date('2024-09-18T02:00:00Z'))).toBe('2024-09-17')
  })
  it('shifts calendar dates by months and years', () => {
    expect(shiftDate('2024-09-17', { months: -1 })).toBe('2024-08-17')
    expect(shiftDate('2024-09-17', { years: -5 })).toBe('2019-09-17')
  })
  it('counts weekdays inclusively', () => {
    expect(weekdaysBetween('2024-09-16', '2024-09-22')).toBe(5)
  })
})

describe('company', () => {
  it('prefers the primary Listing, else the first', () => {
    expect(
      primaryListing([
        { symbol: 'GOOG', is_primary: false },
        { symbol: 'GOOGL', is_primary: true }
      ])?.symbol
    ).toBe('GOOGL')
    expect(primaryListing([{ symbol: 'X', is_primary: false }])?.symbol).toBe(
      'X'
    )
  })
  it('labels a Company by symbol and name', () => {
    expect(
      companyOption({ cik: '1', symbol: 'AAPL', name: 'Apple Inc.' })
    ).toEqual({
      cik: '1',
      label: 'AAPL · Apple Inc.'
    })
  })
  it('lists each Company once from Market rows, by its busiest Listing', () => {
    const options = companyOptionsFromMarket([
      { cik: '9', symbol: 'GOOG', name: 'Alphabet Inc. Class C', volume: 15 },
      { cik: '9', symbol: 'GOOGL', name: 'Alphabet Inc. Class A', volume: 21 },
      { cik: '1', symbol: 'AAPL', name: 'Apple Inc.', volume: 48 }
    ])
    expect(options.map((o) => o.label)).toEqual([
      'AAPL · Apple Inc.',
      'GOOGL · Alphabet Inc. Class A'
    ])
  })
})

describe('routes', () => {
  it('builds Company links', () => {
    expect(companyHref('0000320193')).toBe('/companies/0000320193')
    expect(ROUTES.notes).toBe('/notes')
  })
})
