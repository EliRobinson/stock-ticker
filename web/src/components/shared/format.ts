// Display formatting the design needs that `@/lib/format` (#8) doesn't produce yet:
// bare prices with separators, U+2212 minus, ↑/↓ arrows, 1-decimal Market Cap,
// and "11:42:07 AM ET" / "17 Sep 2024" styles (design frame S7).
// TODO(#8): drop each shim once #8 ships the matching formatter (requested).

import { directionOf, formatQuoteAge, formatVolume } from '@/lib/format'
import type { Direction, NumericInput } from '@/lib/format'

export { formatQuoteAge as formatAge, formatVolume }
export type { Direction, NumericInput }

export function toNumber(value: NumericInput): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

export const direction = directionOf

const NY = 'America/New_York'
const MINUS = '−'

export function formatPrice(input: NumericInput): string {
  const value = toNumber(input)
  if (value == null) return '—'
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })
}

export function formatSignedPercent(input: NumericInput): string {
  const value = toNumber(input)
  if (value == null) return '—'
  const sign = value > 0 ? '+' : value < 0 ? MINUS : ''
  return `${sign}${Math.abs(value).toFixed(2)}%`
}

export function formatSignedMoney(input: NumericInput): string {
  const value = toNumber(input)
  if (value == null) return '—'
  const sign = value > 0 ? '+' : value < 0 ? MINUS : ''
  return `${sign}$${Math.abs(value).toFixed(2)}`
}

function compact(value: number): string {
  const units: [number, string][] = [
    [1e12, 'T'],
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'K']
  ]
  for (const [size, unit] of units) {
    if (Math.abs(value) >= size) {
      return `${(value / size).toFixed(unit === 'T' ? 2 : 1)}${unit}`
    }
  }
  return value.toFixed(0)
}

export function formatMarketCap(input: NumericInput): string {
  const value = toNumber(input)
  if (value == null) return '—'
  return `$${compact(value)}`
}

export function formatTimeET(iso: string, withSeconds = false): string {
  const t = new Date(iso).toLocaleTimeString('en-US', {
    timeZone: NY,
    hour: withSeconds ? '2-digit' : 'numeric',
    minute: '2-digit',
    second: withSeconds ? '2-digit' : undefined,
    hour12: true
  })
  return `${t} ET`
}

function dateParts(iso: string) {
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00Z`) : new Date(iso)
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: iso.length === 10 ? 'UTC' : NY,
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  }).formatToParts(d)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  return { day: get('day'), month: get('month'), year: get('year') }
}

// "17 Sep 2024": day first, as the design board writes dates.
export function formatDate(iso: string): string {
  const { day, month, year } = dateParts(iso)
  return `${day} ${month} ${year}`
}

export function formatShortDate(iso: string): string {
  const { day, month } = dateParts(iso)
  return `${day} ${month}`
}

export function formatDateRange(start: string, end: string): string {
  if (start === end) return formatDate(start)
  const sy = start.slice(0, 4)
  const ey = end.slice(0, 4)
  return sy === ey
    ? `${formatShortDate(start)} – ${formatDate(end)}`
    : `${formatDate(start)} – ${formatDate(end)}`
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`
}

export function formatClock(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: NY,
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true
  }).formatToParts(new Date(iso))
  return parts
    .filter((p) => p.type !== 'dayPeriod' && p.type !== 'literal')
    .map((p) => p.value)
    .join(':')
}
