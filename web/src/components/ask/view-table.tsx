'use client'

import { useRef } from 'react'

import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table'
import type { TableViewSpec } from '@/lib/chat'
import {
  EMPTY,
  formatDateShort,
  formatInteger,
  formatMarketCap,
  formatPrice,
  toNumber
} from '@/lib/format'
import { cn } from '@/lib/utils'

import { ChangeCell } from '../shared/cells'
import { useElementWidth } from '../shared/use-media'

type ViewColumn = TableViewSpec['columns'][number]

const isPercent = (col: ViewColumn) =>
  col.format === 'percent' || col.format === 'fraction_as_percent'

function percentOf(col: ViewColumn, value: unknown): number | null {
  const n = toNumber(value as string | number | null)
  if (n === null) return null
  return col.format === 'fraction_as_percent' ? n * 100 : n
}

function cellText(col: ViewColumn, value: unknown): string {
  if (value == null || value === '') return EMPTY
  const input = value as string | number
  switch (col.format) {
    case 'number':
      return formatPrice(input, { currency: false })
    case 'currency':
      return formatPrice(input)
    case 'integer':
      return formatInteger(input)
    case 'compact_currency':
      return formatMarketCap(input)
    case 'date':
    case 'datetime':
      return formatDateShort(String(value))
    default:
      return String(value)
  }
}

// The Market table's styling, not virtualized (results are capped small).
// Values render as text, never HTML (system design §7). Percent columns
// carry sign and arrow like every change on the app.
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
        <TableHeader>
          <TableRow>
            {cols.map((c, i) => (
              <TableHead
                key={c.key}
                scope='col'
                className={i === 0 ? 'text-left' : 'text-right'}
              >
                {c.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {spec.rows.map((row, r) => (
            <TableRow key={r} className='hover:bg-transparent'>
              {cols.map((c, i) => {
                const value = row[c.key]
                return (
                  <TableCell
                    key={c.key}
                    className={cn(
                      i === 0 ? 'text-left font-bold' : 'text-right'
                    )}
                  >
                    {isPercent(c) ? (
                      <ChangeCell pct={percentOf(c, value)} />
                    ) : (
                      cellText(c, value)
                    )}
                  </TableCell>
                )
              })}
            </TableRow>
          ))}
        </TableBody>
      </table>
    </div>
  )
}
