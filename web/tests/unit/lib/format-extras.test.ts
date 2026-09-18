import { describe, expect, it } from 'vitest'

import {
  EMPTY,
  formatClock,
  formatDateRange,
  formatInteger,
  formatUsd
} from '@/lib/format'

describe('formatDateRange', () => {
  it.each([
    ['2024-09-17', '2024-09-17', '17 Sep 2024'],
    ['2024-08-05', '2024-09-12', '5 Aug – 12 Sep 2024'],
    ['2020-02-19', '2021-03-23', '19 Feb 2020 – 23 Mar 2021']
  ])('%s to %s reads %s', (start, end, expected) => {
    expect(formatDateRange(start, end)).toBe(expected)
  })
})

describe('formatClock', () => {
  it('shows New York wall time with seconds and no AM/PM', () => {
    expect(formatClock('2024-09-17T15:42:02Z')).toBe('11:42:02')
  })
  it('shows the empty mark for a missing time', () => {
    expect(formatClock(null)).toBe(EMPTY)
  })
})

describe('formatInteger and formatUsd', () => {
  it('groups thousands and rounds', () => {
    expect(formatInteger(1183.4)).toBe('1,183')
    expect(formatInteger('503')).toBe('503')
    expect(formatInteger(null)).toBe(EMPTY)
  })
  it('prints dollars with cents', () => {
    expect(formatUsd(5)).toBe('$5.00')
    expect(formatUsd('1.237')).toBe('$1.24')
  })
})
