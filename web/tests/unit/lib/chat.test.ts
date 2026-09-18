import { describe, expect, it } from 'vitest'
import { isDataViewPart, parseViewSpec } from '@/lib/chat'

describe('parseViewSpec', () => {
  it('accepts a valid table spec', () => {
    const data = {
      kind: 'table',
      id: 'view-1',
      title: 'Top movers',
      columns: [
        { key: 'symbol', label: 'Symbol', format: null },
        { key: 'change_pct', label: 'Change %', format: 'fraction_as_percent' }
      ],
      rows: [{ symbol: 'AAPL', change_pct: 0.05 }]
    }
    const result = parseViewSpec(data)
    expect(result.success).toBe(true)
  })

  it('accepts a valid timeseries spec', () => {
    const data = {
      kind: 'timeseries',
      id: 'view-2',
      title: 'Price history',
      x: 'trade_date',
      series: [{ key: 'close', label: 'Close' }],
      y_format: 'currency',
      rows: [{ trade_date: '2024-06-03', close: 190.12 }]
    }
    expect(parseViewSpec(data).success).toBe(true)
  })

  it('rejects an unknown kind', () => {
    const result = parseViewSpec({ kind: 'pie', id: 'v', title: 't' })
    expect(result.success).toBe(false)
  })

  it('rejects a timeseries spec with no series', () => {
    const data = {
      kind: 'timeseries',
      id: 'view-3',
      title: 'Empty',
      x: 'trade_date',
      series: [],
      y_format: null,
      rows: []
    }
    expect(parseViewSpec(data).success).toBe(false)
  })

  it('rejects a table spec missing required fields', () => {
    expect(parseViewSpec({ kind: 'table' }).success).toBe(false)
  })
})

describe('isDataViewPart', () => {
  it('accepts a data-view part', () => {
    expect(
      isDataViewPart({ type: 'data-view', id: 'v', data: {} } as never)
    ).toBe(true)
  })

  it('rejects a text part', () => {
    expect(isDataViewPart({ type: 'text', text: 'hello' } as never)).toBe(false)
  })
})
