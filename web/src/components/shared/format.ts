// The screens' display formatting. Numbers, times and ages come from #8's
// `@/lib/format`; the few shapes it doesn't cover yet are kept here.

import {
  directionOf,
  formatChange,
  formatDateShort,
  formatMarketCap,
  formatPercent,
  formatPrice as formatPriceWithCurrency,
  formatQuoteAge,
  formatTimeET as formatTimeETLib,
  formatVolume,
  toNumber
} from '@/lib/format'
import type { Direction, NumericInput } from '@/lib/format'

export type { Direction, NumericInput }
export {
  formatChange as formatSignedMoney,
  formatMarketCap,
  formatPercent as formatSignedPercent,
  formatQuoteAge as formatAge,
  formatVolume,
  toNumber
}

export const direction = directionOf

// Prices in tables and stat rows are bare and tabular ("227.52", "8,214.30").
export function formatPrice(value: NumericInput): string {
  return formatPriceWithCurrency(value, { currency: false })
}

export function formatTimeET(iso: string, withSeconds = false): string {
  return formatTimeETLib(iso, { seconds: withSeconds })
}

const NY = 'America/New_York'

// "17 Sep 2024": day first, as the design board writes dates.
export function formatDate(iso: string): string {
  return formatDateShort(iso)
}

// "17 Sep": the start of a same-year range.
export function formatShortDate(iso: string): string {
  return formatDateShort(iso).replace(/ \d{4}$/, '')
}

export function formatDateRange(start: string, end: string): string {
  if (start === end) return formatDate(start)
  return start.slice(0, 4) === end.slice(0, 4)
    ? `${formatShortDate(start)} – ${formatDate(end)}`
    : `${formatDate(start)} – ${formatDate(end)}`
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`
}

// "11:42:02", the ingest pill's last-run clock (design G1).
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
