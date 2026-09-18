export type NumericInput = string | number | null | undefined

/** What every formatter shows for a missing value. */
export const EMPTY = '—'
/** The Unicode minus sign (U+2212), not a hyphen - the brief and Claude
 * Design both use it for negative price/percent chrome. */
const MINUS = '−'

/** The market clock and every Trading Day are dated in New York time
 * (CONTEXT.md) - used everywhere a real timestamp (not a bare calendar
 * date - see calendarDateParts) needs to show in market time. */
export const NY_TZ = 'America/New_York'
const MARKET_TIME_ZONE = NY_TZ

/** The one parser for "a decimal-string-or-number-or-null from the API" -
 * shared with market-table.ts instead of a second copy there. */
export function toNumber(value: NumericInput): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

/** The empty-or-invalid guard every timestamp formatter needs, in one
 * place, instead of a `!value` + `new Date` + `isNaN` copy in each one. */
function parseInstant(value: string | null | undefined): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const MONTH_ABBREVIATIONS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec'
]

/**
 * A Trading Day, Note start/end date, and Event date are bare `YYYY-MM-DD`
 * with no time of day (CONTEXT.md) - `new Date('2024-09-17')` parses that
 * as UTC midnight, and formatting it in any zone behind UTC (including
 * America/New_York) rolls it back to the previous day's evening. A pure
 * calendar date has no instant-in-time to convert between zones, so this
 * reads its year/month/day directly off the string instead of going
 * through Date + timeZone math at all.
 */
function calendarDateParts(
  value: string
): { year: number; month: number; day: number } | null {
  if (!DATE_ONLY_PATTERN.test(value)) return null
  const [year, month, day] = value.split('-').map(Number)
  if (year === undefined || month === undefined || day === undefined) {
    return null
  }
  return { year, month, day }
}

export type Direction = 'up' | 'down' | 'flat'

/** Rounds to `precision` decimals before deciding the sign - a value that
 * rounds to 0 there (e.g. -0.001 at the default 2 decimals) is flat, not
 * down. Every signed formatter below (and chart-data's volume direction)
 * calls this, so a delta's text and its arrow/color can never disagree. */
export function directionOf(value: NumericInput, precision = 2): Direction {
  const n = toNumber(value)
  if (n === null) return 'flat'
  const rounded = Number(n.toFixed(precision))
  if (rounded === 0) return 'flat'
  return rounded > 0 ? 'up' : 'down'
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

export interface FormatSignedFixedOptions {
  prefix?: string
  suffix?: string
}

/** formatChange and formatPercent are both "sign it from the rounded
 * value, fix to 2 decimals, wrap in a prefix/suffix" - this is the one
 * implementation, so the two can't quietly diverge on how they round or
 * sign. */
function formatSignedFixed(
  value: NumericInput,
  { prefix = '', suffix = '' }: FormatSignedFixedOptions = {}
): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const direction = directionOf(n)
  const rounded = Number(Math.abs(n).toFixed(2))
  const sign = direction === 'flat' ? '' : direction === 'up' ? '+' : MINUS
  return `${sign}${prefix}${rounded.toFixed(2)}${suffix}`
}

export function formatChange(value: NumericInput): string {
  return formatSignedFixed(value, { prefix: '$' })
}

export function formatPercent(value: NumericInput): string {
  return formatSignedFixed(value, { suffix: '%' })
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
 * every other tier doesn't need it. Kept separate from VOLUME_TIERS even
 * though the shapes match - a share-volume tier table and a dollar-value
 * one change for unrelated reasons.
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

export interface FormatTieredOptions {
  prefix?: string
}

/** formatMarketCap and formatVolume are both "sign it (never a signed
 * zero), pick a tier, round within it" over their own tier table - this is
 * the one implementation; the tables themselves stay separate (see
 * MARKET_CAP_TIERS). */
function formatTiered(
  value: NumericInput,
  tiers: ScaleTier[],
  fallbackDecimals: number,
  { prefix = '' }: FormatTieredOptions = {}
): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const abs = Math.abs(n)
  const isZero = tieredIsZero(abs, tiers, fallbackDecimals)
  const sign = isZero ? '' : n < 0 ? MINUS : ''
  return `${sign}${prefix}${tieredMagnitude(abs, tiers, fallbackDecimals)}`
}

export function formatMarketCap(value: NumericInput): string {
  return formatTiered(value, MARKET_CAP_TIERS, 2, { prefix: '$' })
}

export function formatVolume(value: NumericInput): string {
  return formatTiered(value, VOLUME_TIERS, 0)
}

export function formatDate(value: string | null | undefined): string {
  const calendarDate = value ? calendarDateParts(value) : null
  if (calendarDate) {
    const { year, month, day } = calendarDate
    return `${MONTH_ABBREVIATIONS[month - 1]} ${day}, ${year}`
  }
  const date = parseInstant(value)
  if (!date) return EMPTY
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC'
  }).format(date)
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parseInstant(value)
  if (!date) return EMPTY
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  }).format(date)
}

/** Times shown next to the market clock - "Data as of", a Quote's
 * observed_at - use MARKET_TIME_ZONE explicitly rather than the viewer's
 * local zone, with the zone name (EDT/EST) printed so it's never ambiguous. */
export function formatDateTimeET(value: string | null | undefined): string {
  const date = parseInstant(value)
  if (!date) return EMPTY
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: MARKET_TIME_ZONE,
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
  const date = parseInstant(value)
  if (!date) return EMPTY
  const time = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: seconds ? '2-digit' : undefined,
    timeZone: MARKET_TIME_ZONE
  }).format(date)
  return `${time} ET`
}

/** "17 Sep 2024" - day-month-year, always a 3-letter month. `en-GB`'s short
 * month is "Sept" for September specifically, so a real timestamp's parts
 * are pulled from `en-US` (reliably 3 letters year-round) and joined here
 * instead of trusting a locale's day-first ordering. A bare calendar date
 * never goes through Intl/timeZone at all - see calendarDateParts. */
export function formatDateShort(value: string | null | undefined): string {
  const calendarDate = value ? calendarDateParts(value) : null
  if (calendarDate) {
    const { year, month, day } = calendarDate
    return `${day} ${MONTH_ABBREVIATIONS[month - 1]} ${year}`
  }
  const date = parseInstant(value)
  if (!date) return EMPTY
  const parts = new Intl.DateTimeFormat('en-US', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: MARKET_TIME_ZONE
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
 * is decided (via directionOf) from `n` rounded to that same precision, so
 * a value that rounds to zero (e.g. -0.001 at the default 2 decimals)
 * reads as flat, not "0.00 ↓". Pass a matching `precision` alongside a
 * custom formatter with different rounding (e.g. formatMarketCap's
 * variable decimals).
 */
export function formatSigned(
  value: NumericInput,
  formatter: (n: number) => string = (n) => n.toFixed(2),
  precision = 2
): SignedFormat {
  const n = toNumber(value)
  if (n === null) return { text: EMPTY, direction: 'flat', arrow: '' }
  const direction = directionOf(n, precision)
  const text = formatter(Math.abs(n))
  return { text, direction, arrow: ARROWS[direction] }
}

/** "1,183": a whole count with thousands separators. */
export function formatInteger(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  return Math.round(n).toLocaleString('en-US')
}

/** "$5.00": a dollar amount with cents, for spend readouts. */
export function formatUsd(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  return `$${n.toFixed(2)}`
}

/** "11:42:02": a New York wall-clock time with seconds and no AM/PM, for
 * the ingest pill's "last run". */
export function formatClock(value: string | null | undefined): string {
  const date = parseInstant(value)
  if (!date) return EMPTY
  const parts = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZone: MARKET_TIME_ZONE
  }).formatToParts(date)
  return parts
    .filter(
      (p) => p.type === 'hour' || p.type === 'minute' || p.type === 'second'
    )
    .map((p) => p.value)
    .join(':')
}

/** "5 Aug – 12 Sep 2024" for a same-year range, "19 Feb 2020 – 23 Mar 2021"
 * across years, and one date when start and end match. Bare calendar dates
 * (a Note's span, a chart range). */
export function formatDateRange(start: string, end: string): string {
  if (start === end) return formatDateShort(start)
  const a = calendarDateParts(start)
  const b = calendarDateParts(end)
  if (a && b && a.year === b.year) {
    return `${a.day} ${MONTH_ABBREVIATIONS[a.month - 1]} \u2013 ${formatDateShort(end)}`
  }
  return `${formatDateShort(start)} \u2013 ${formatDateShort(end)}`
}
