import { describe, expect, it } from 'vitest'
import {
  directionOf,
  formatChange,
  formatDate,
  formatDateShort,
  formatDateTimeET,
  formatMarketCap,
  formatPercent,
  formatPrice,
  formatQuoteAge,
  formatSigned,
  formatTimeET,
  formatVolume
} from '@/lib/format'

const MINUS = '−'

describe('formatPrice', () => {
  it('formats a decimal string with two places, $-prefixed by default', () => {
    expect(formatPrice('142.5')).toBe('$142.50')
  })

  it('formats a number', () => {
    expect(formatPrice(9.999)).toBe('$10.00')
  })

  it('groups thousands', () => {
    expect(formatPrice(8214.3)).toBe('$8,214.30')
  })

  it('omits the $ prefix when currency is false', () => {
    expect(formatPrice(8214.3, { currency: false })).toBe('8,214.30')
    expect(formatPrice(227.52, { currency: false })).toBe('227.52')
  })

  it('renders null as an em dash', () => {
    expect(formatPrice(null)).toBe('—')
  })
})

describe('formatChange', () => {
  it('signs a positive change', () => {
    expect(formatChange('1.23')).toBe('+$1.23')
  })

  it('signs a negative change with the Unicode minus', () => {
    expect(formatChange('-1.23')).toBe(`${MINUS}$1.23`)
  })

  it('has no sign for zero', () => {
    expect(formatChange(0)).toBe('$0.00')
  })

  it('never renders a signed zero for a tiny negative that rounds to 0', () => {
    expect(formatChange(-0.001)).toBe('$0.00')
  })
})

describe('formatPercent', () => {
  it('signs a positive percent', () => {
    expect(formatPercent('2.5')).toBe('+2.50%')
  })

  it('signs a negative percent with the Unicode minus', () => {
    expect(formatPercent('-2.5')).toBe(`${MINUS}2.50%`)
  })

  it('never renders a signed zero for a tiny negative that rounds to 0', () => {
    expect(formatPercent(-0.001)).toBe('0.00%')
  })
})

describe('formatMarketCap', () => {
  it.each([
    [2_910_000_000_000, '$2.91T'],
    [487_200_000_000, '$487.2B'],
    [3_400_000, '$3.4M'],
    [8_500, '$8.5K'],
    [999, '$999.00']
  ])('formats %d as %s', (value, expected) => {
    expect(formatMarketCap(value)).toBe(expected)
  })

  it('signs a negative market cap with the Unicode minus', () => {
    expect(formatMarketCap(-3_400_000)).toBe(`${MINUS}$3.4M`)
  })

  it('renders null as an em dash', () => {
    expect(formatMarketCap(null)).toBe('—')
  })

  it('never renders a signed zero for a tiny negative that rounds to 0', () => {
    expect(formatMarketCap(-0.001)).toBe('$0.00')
  })

  it('bumps to the next tier instead of overflowing to "$1000.00B"', () => {
    // 999.95B rounds to "1000.0" at the B tier's one decimal - that belongs
    // at the T tier, not displayed as a 4-digit "B" value.
    expect(formatMarketCap(999_950_000_000)).toBe('$1.00T')
  })

  it('bumps a K value to M instead of overflowing to "1000.0K"', () => {
    expect(formatMarketCap(999_950)).toBe('$1.0M')
  })

  it('has no tier to bump a T overflow into', () => {
    expect(formatMarketCap(999_999_999_999_999)).toBe('$1000.00T')
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

  it('bumps to the next tier instead of overflowing to "1000.0K"', () => {
    expect(formatVolume(999_950)).toBe('1.0M')
  })

  it('signs a negative volume with the Unicode minus', () => {
    expect(formatVolume(-503_200)).toBe(`${MINUS}503.2K`)
  })

  it('never renders a signed zero for a tiny negative that rounds to 0', () => {
    expect(formatVolume(-0.4)).toBe('0')
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
      arrow: '↑'
    })
  })

  it('carries a down arrow for a negative value', () => {
    expect(formatSigned(-3.456, (n) => n.toFixed(1))).toEqual({
      text: '3.5',
      direction: 'down',
      arrow: '↓'
    })
  })

  it('has no arrow for a flat value', () => {
    expect(formatSigned(0)).toEqual({
      text: '0.00',
      direction: 'flat',
      arrow: ''
    })
  })

  it('never shows a down arrow next to a "0.00" that rounded away from a tiny negative', () => {
    // formatChange itself already signs from the rounded value (see the
    // formatChange suite above); this is the same rule for formatSigned's
    // direction/arrow, which formatChange's text doesn't otherwise imply.
    expect(formatSigned(-0.001, (n) => n.toFixed(2))).toEqual({
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

describe('formatTimeET', () => {
  it('renders a literal ET suffix, not EDT/EST', () => {
    // 15:42:07 UTC in September is 11:42:07 EDT.
    expect(formatTimeET('2024-09-17T15:42:07.000Z')).toBe('11:42 AM ET')
  })

  it('includes seconds when asked', () => {
    expect(formatTimeET('2024-09-17T15:42:07.000Z', { seconds: true })).toBe(
      '11:42:07 AM ET'
    )
  })

  it('renders a missing value as an em dash', () => {
    expect(formatTimeET(null)).toBe('—')
  })
})

describe('formatDateShort', () => {
  it('renders day-month-year with a 3-letter month', () => {
    expect(formatDateShort('2024-09-17T15:42:07.000Z')).toBe('17 Sep 2024')
  })

  it('never renders the en-GB 4-letter "Sept"', () => {
    expect(formatDateShort('2024-09-01T12:00:00.000Z')).not.toContain('Sept')
  })

  it('renders a missing value as an em dash', () => {
    expect(formatDateShort(null)).toBe('—')
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
