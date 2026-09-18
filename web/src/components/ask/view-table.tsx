'use client'

import { useRef } from 'react'

import type { TableViewSpec } from '@/lib/chat'
import { cn } from '@/lib/utils'

import { ChangeCell } from '../shared/cells'
import {
  formatDate,
  formatMarketCap,
  formatPrice,
  formatSignedPercent,
  toNumber
} from '../shared/format'
import { useElementWidth } from '../shared/use-media'

type ViewColumn = TableViewSpec['columns'][number]

const CHANGE_LIKE = /change|return|drawdown|pct|move/i

function percentOf(col: ViewColumn, value: unknown): number | null {
  const n = toNumber(value as string | number | null)
  if (n == null) return null
  return col.format === 'fraction_as_percent' ? n * 100 : n
}

function cellText(col: ViewColumn, value: unknown): string {
  if (value == null || value === '') return '\u2014'
  switch (col.format) {
    case 'number':
    case 'currency':
      return formatPrice(value as string | number)
    case 'integer': {
      const n = toNumber(value as string | number)
      return n == null ? String(value) : n.toLocaleString('en-US')
    }
    case 'compact_currency':
      return formatMarketCap(value as string | number)
    case 'percent':
    case 'fraction_as_percent':
      return formatSignedPercent(percentOf(col, value))
    case 'date':
    case 'datetime':
      return formatDate(String(value))
    default:
      return String(value)
  }
}

// Same table styling as the Market screen, not virtualized (results are small).
// Values render as text, never HTML (system design §7).
export function ViewTable({ spec }: { spec: TableViewSpec }) {
  const ref = useRef<HTMLDivElement>(null)
  const width = useElementWidth(ref, 380)
  const cols =
    width < 340 && spec.columns.length > 2
      ? [spec.columns[0]!, spec.columns[spec.columns.length - 1]!]
      : spec.columns

  return (
    <div ref={ref} className='w-full overflow-x-auto'>
      <table className='tabular w-full border-collapse text-xs'>
        <caption className='sr-only'>{spec.title}</caption>
        <thead>
          <tr className='border-border border-b'>
            {cols.map((c, i) => (
              <th
                key={c.key}
                scope='col'
                className={cn(
                  'text-muted-foreground text-2xs p-[6.8px] font-normal uppercase tracking-[0.08em]',
                  i === 0 ? 'text-left' : 'text-right'
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((row, r) => (
            <tr key={r} className='border-rowline border-b'>
              {cols.map((c, i) => {
                const value = row[c.key] ?? null
                return (
                  <td
                    key={c.key}
                    className={cn(
                      'whitespace-nowrap p-[6.8px]',
                      i === 0 ? 'text-left font-bold' : 'text-right'
                    )}
                  >
                    {(c.format === 'percent' ||
                      c.format === 'fraction_as_percent') &&
                    CHANGE_LIKE.test(`${c.key} ${c.label}`) ? (
                      <ChangeCell pct={percentOf(c, value)} />
                    ) : (
                      cellText(c, value)
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
