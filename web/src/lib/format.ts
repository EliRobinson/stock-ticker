export type NumericInput = string | number | null | undefined

const EMPTY = '—'
/** The Unicode minus sign (U+2212), not a hyphen - the brief and Claude
 * Design both use it for negative price/percent chrome. */
const MINUS = '−'

/** The one parser for "a decimal-string-or-number-or-null from the API" -
 * shared with market-table.ts instead of a second copy there. */
export function toNumber(value: NumericInput): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

export type Direction = 'up' | 'down' | 'flat'

export function directionOf(value: NumericInput): Direction {
  const n = toNumber(value)
  if (n === null || n === 0) return 'flat'
  return n > 0 ? 'up' : 'down'
}

export interface FormatPriceOptions {
  /** @default true */
  currency?: boolean
}

/** Grouped (thousands-separated), fixed to two decimals - `{currency:
 * false}` renders the bare tabular form the Company header/chart axis use
 * ("8,214.30"), the default renders the $-prefixed form the Market table
 * uses ("$8,214.30"). */
export function formatPrice(
  value: NumericInput,
  { currency = true }: FormatPriceOptions = {}
): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const grouped = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n)
  return currency ? `$${grouped}` : grouped
}

/** Rounds first, then signs from the ROUNDED value - a value that rounds
 * to 0 (e.g. -0.001 at 2 decimals) must render as "$0.00", never
 * "−$0.00". */
export function formatChange(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const rounded = Number(Math.abs(n).toFixed(2))
  const sign = rounded === 0 ? '' : n > 0 ? '+' : MINUS
  return `${sign}$${rounded.toFixed(2)}`
}

export function formatPercent(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const rounded = Number(Math.abs(n).toFixed(2))
  const sign = rounded === 0 ? '' : n > 0 ? '+' : MINUS
  return `${sign}${rounded.toFixed(2)}%`
}

interface ScaleTier {
  threshold: number
  suffix: string
  decimals: number
}

/**
 * Trillions get two decimals, everything else gets one - matching the
 * brief's own examples ("$2.91T / $487.2B / $3.4M"): a trillion-dollar
 * Company is rare enough that the extra digit of precision is worth it,
 * every other tier doesn't need it.
 */
const MARKET_CAP_TIERS: ScaleTier[] = [
  { threshold: 1e12, suffix: 'T', decimals: 2 },
  { threshold: 1e9, suffix: 'B', decimals: 1 },
  { threshold: 1e6, suffix: 'M', decimals: 1 },
  { threshold: 1e3, suffix: 'K', decimals: 1 }
]

const VOLUME_TIERS: ScaleTier[] = [
  { threshold: 1e9, suffix: 'B', decimals: 1 },
  { threshold: 1e6, suffix: 'M', decimals: 1 },
  { threshold: 1e3, suffix: 'K', decimals: 1 }
]

/**
 * Picks a tier by magnitude, then rounds within it - but rounding can push
 * a value up past the tier's own ceiling (999.95B rounds to "1000.0B" at
 * one decimal, when it should read "1.00T"). When that happens, this
 * re-renders at the next tier up instead of ever printing a 4-digit
 * magnitude.
 */
function tieredMagnitude(
  abs: number,
  tiers: ScaleTier[],
  fallbackDecimals: number
): string {
  for (let i = 0; i < tiers.length; i++) {
    const tier = tiers[i]
    if (tier === undefined || abs < tier.threshold) continue
    const rounded = Number((abs / tier.threshold).toFixed(tier.decimals))
    const bigger = tiers[i - 1]
    if (rounded >= 1000 && bigger !== undefined) {
      const biggerRounded = (abs / bigger.threshold).toFixed(bigger.decimals)
      return `${biggerRounded}${bigger.suffix}`
    }
    return `${rounded.toFixed(tier.decimals)}${tier.suffix}`
  }
  return abs.toFixed(fallbackDecimals)
}

/** True when every digit `tieredMagnitude` would render is a rounded-away
 * zero - a matched tier is always >= roughly 1.0 in its own units, so this
 * only matters for the untiered fallback range. */
function tieredIsZero(
  abs: number,
  tiers: ScaleTier[],
  fallbackDecimals: number
): boolean {
  if (tiers.some((tier) => abs >= tier.threshold)) return false
  return Number(abs.toFixed(fallbackDecimals)) === 0
}

export function formatMarketCap(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const abs = Math.abs(n)
  const isZero = tieredIsZero(abs, MARKET_CAP_TIERS, 2)
  const sign = isZero ? '' : n < 0 ? MINUS : ''
  return `${sign}$${tieredMagnitude(abs, MARKET_CAP_TIERS, 2)}`
}

export function formatVolume(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const abs = Math.abs(n)
  const isZero = tieredIsZero(abs, VOLUME_TIERS, 0)
  const sign = isZero ? '' : n < 0 ? MINUS : ''
  return `${sign}${tieredMagnitude(abs, VOLUME_TIERS, 0)}`
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return EMPTY
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return EMPTY
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC'
  }).format(date)
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return EMPTY
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return EMPTY
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  }).format(date)
}

/** The market clock and every Trading Day are dated in New York time
 * (CONTEXT.md), so times shown next to them - "Data as of", a Quote's
 * observed_at - use America/New_York explicitly rather than the viewer's
 * local zone, with the zone name (EDT/EST) printed so it's never ambiguous. */
export function formatDateTimeET(value: string | null | undefined): string {
  if (!value) return EMPTY
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return EMPTY
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
    timeZoneName: 'short'
  }).format(date)
}

export interface FormatTimeETOptions {
  seconds?: boolean
}

/** Claude Design's clock/pill chrome ("11:42:07 AM ET") wants the literal
 * "ET" suffix, not Intl's accurate but DST-dependent EDT/EST - append it as
 * text instead of asking Intl for a zone name. */
export function formatTimeET(
  value: string | null | undefined,
  { seconds = false }: FormatTimeETOptions = {}
): string {
  if (!value) return EMPTY
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return EMPTY
  const time = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: seconds ? '2-digit' : undefined,
    timeZone: 'America/New_York'
  }).format(date)
  return `${time} ET`
}

/** "17 Sep 2024" - day-month-year, always a 3-letter month. `en-GB`'s short
 * month is "Sept" for September specifically, so this pulls parts from
 * `en-US` (reliably 3 letters year-round) and joins them itself instead of
 * trusting a locale's day-first ordering. */
export function formatDateShort(value: string | null | undefined): string {
  if (!value) return EMPTY
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return EMPTY
  const parts = new Intl.DateTimeFormat('en-US', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'America/New_York'
  }).formatToParts(date)
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  return `${part('day')} ${part('month')} ${part('year')}`
}

/** A short "how long ago" label for a Quote's age, not a duration a screen
 * reader would want spelled out - this is chrome next to a price, not
 * prose. Accepts staleness.ts's `ageMs: number | null` directly. */
export function formatQuoteAge(ageMs: number | null): string {
  if (ageMs === null) return EMPTY
  const totalSeconds = Math.max(0, Math.floor(ageMs / 1000))
  if (totalSeconds < 60) return `${totalSeconds}s`
  const totalMinutes = Math.floor(totalSeconds / 60)
  if (totalMinutes < 60) return `${totalMinutes}m`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`
}

export interface SignedFormat {
  text: string
  direction: Direction
  arrow: string
}

const ARROWS: Record<Direction, string> = {
  up: '↑',
  down: '↓',
  flat: ''
}

/**
 * `precision` must match how many decimals `formatter` renders - direction
 * is decided from `n` rounded to that same precision, so a value that
 * rounds to zero (e.g. -0.001 at the default 2 decimals) reads as flat, not
 * "0.00 ↓". Pass a matching `precision` alongside a custom formatter
 * with different rounding (e.g. formatMarketCap's variable decimals).
 */
export function formatSigned(
  value: NumericInput,
  formatter: (n: number) => string = (n) => n.toFixed(2),
  precision = 2
): SignedFormat {
  const n = toNumber(value)
  if (n === null) return { text: EMPTY, direction: 'flat', arrow: '' }
  const rounded = Number(n.toFixed(precision))
  const direction: Direction =
    rounded === 0 ? 'flat' : rounded > 0 ? 'up' : 'down'
  const text = formatter(Math.abs(n))
  return { text, direction, arrow: ARROWS[direction] }
}
