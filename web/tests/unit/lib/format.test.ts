import { describe, expect, it } from 'vitest'
import {
  directionOf,
  formatChange,
  formatDate,
  formatDateTimeET,
  formatMarketCap,
  formatPercent,
  formatPrice,
  formatQuoteAge,
  formatSigned,
  formatVolume
} from '@/lib/format'

describe('formatPrice', () => {
  it('formats a decimal string with two places', () => {
    expect(formatPrice('142.5')).toBe('$142.50')
  })

  it('formats a number', () => {
    expect(formatPrice(9.999)).toBe('$10.00')
  })

  it('renders null as an em dash', () => {
    expect(formatPrice(null)).toBe('—')
  })
})

describe('formatChange', () => {
  it('signs a positive change', () => {
    expect(formatChange('1.23')).toBe('+$1.23')
  })

  it('signs a negative change', () => {
    expect(formatChange('-1.23')).toBe('-$1.23')
  })

  it('has no sign for zero', () => {
    expect(formatChange(0)).toBe('$0.00')
  })
})

describe('formatPercent', () => {
  it('signs a positive percent', () => {
    expect(formatPercent('2.5')).toBe('+2.50%')
  })

  it('signs a negative percent', () => {
    expect(formatPercent('-2.5')).toBe('-2.50%')
  })
})

describe('formatMarketCap', () => {
  it.each([
    [2_910_000_000_000, '$2.91T'],
    [503_200_000_000, '$503.20B'],
    [12_400_000, '$12.40M'],
    [8_500, '$8.50K'],
    [999, '$999.00']
  ])('formats %d as %s', (value, expected) => {
    expect(formatMarketCap(value)).toBe(expected)
  })

  it('renders null as an em dash', () => {
    expect(formatMarketCap(null)).toBe('—')
  })
})

describe('formatVolume', () => {
  it.each([
    [12_300_000, '12.3M'],
    [503_200, '503.2K'],
    [820, '820']
  ])('formats %d as %s', (value, expected) => {
    expect(formatVolume(value)).toBe(expected)
  })
})

describe('formatDate', () => {
  it('formats an ISO date', () => {
    expect(formatDate('2024-06-03')).toBe('Jun 3, 2024')
  })

  it('renders a missing date as an em dash', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
  })

  it('renders an invalid date as an em dash', () => {
    expect(formatDate('not-a-date')).toBe('—')
  })
})

describe('directionOf', () => {
  it.each([
    ['5', 'up'],
    ['-5', 'down'],
    ['0', 'flat'],
    [null, 'flat']
  ] as const)('classifies %s as %s', (value, expected) => {
    expect(directionOf(value)).toBe(expected)
  })
})

describe('formatSigned', () => {
  it('carries an up arrow for a positive value', () => {
    expect(formatSigned(3.456, (n) => n.toFixed(1))).toEqual({
      text: '3.5',
      direction: 'up',
      arrow: '▲'
    })
  })

  it('carries a down arrow for a negative value', () => {
    expect(formatSigned(-3.456, (n) => n.toFixed(1))).toEqual({
      text: '3.5',
      direction: 'down',
      arrow: '▼'
    })
  })

  it('has no arrow for a flat value', () => {
    expect(formatSigned(0)).toEqual({
      text: '0.00',
      direction: 'flat',
      arrow: ''
    })
  })
})

describe('formatDateTimeET', () => {
  it('renders in America/New_York with a zone abbreviation', () => {
    // 15:00 UTC in June is 11:00 EDT.
    expect(formatDateTimeET('2024-06-03T15:00:00.000Z')).toBe(
      'Jun 3, 2024, 11:00 AM EDT'
    )
  })

  it('renders a missing value as an em dash', () => {
    expect(formatDateTimeET(null)).toBe('—')
  })
})

describe('formatQuoteAge', () => {
  it.each([
    [0, '0s'],
    [45_000, '45s'],
    [90_000, '1m'],
    [3_540_000, '59m'],
    [3_600_000, '1h'],
    [3_660_000, '1h 1m'],
    [7_200_000, '2h']
  ])('formats %dms as %s', (ms, expected) => {
    expect(formatQuoteAge(ms)).toBe(expected)
  })

  it('clamps a negative age to 0', () => {
    expect(formatQuoteAge(-500)).toBe('0s')
  })
})
