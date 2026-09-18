export type NumericInput = string | number | null | undefined

const EMPTY = '—'

function toNumber(value: NumericInput): number | null {
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

export function formatPrice(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  return `$${n.toFixed(2)}`
}

export function formatChange(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}$${Math.abs(n).toFixed(2)}`
}

export function formatPercent(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}${Math.abs(n).toFixed(2)}%`
}

const MARKET_CAP_SUFFIXES: Array<[number, string]> = [
  [1e12, 'T'],
  [1e9, 'B'],
  [1e6, 'M'],
  [1e3, 'K']
]

export function formatMarketCap(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  for (const [threshold, suffix] of MARKET_CAP_SUFFIXES) {
    if (abs >= threshold) {
      return `${sign}$${(abs / threshold).toFixed(2)}${suffix}`
    }
  }
  return `${sign}$${abs.toFixed(2)}`
}

export function formatVolume(value: NumericInput): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  for (const [threshold, suffix] of MARKET_CAP_SUFFIXES) {
    if (abs >= threshold) {
      return `${sign}${(abs / threshold).toFixed(1)}${suffix}`
    }
  }
  return `${sign}${Math.round(abs)}`
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

/** A short "how long ago" label for a Quote's age, not a duration a screen
 * reader would want spelled out - this is chrome next to a price, not prose. */
export function formatQuoteAge(ageMs: number): string {
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
  up: '▲',
  down: '▼',
  flat: ''
}

export function formatSigned(
  value: NumericInput,
  formatter: (n: number) => string = (n) => n.toFixed(2)
): SignedFormat {
  const n = toNumber(value)
  const direction = n === null ? 'flat' : directionOf(n)
  const text = n === null ? EMPTY : formatter(Math.abs(n))
  return { text, direction, arrow: ARROWS[direction] }
}
