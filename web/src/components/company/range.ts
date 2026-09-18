import { shiftDate } from '@/lib/dates'

export const PRESETS = ['1M', '6M', 'YTD', '1Y', '5Y', 'Max'] as const
export type RangePreset = (typeof PRESETS)[number]

/** One chart range: a preset, or a custom span picked on the calendar. */
export type ChartRange =
  | { kind: 'preset'; preset: RangePreset }
  | { kind: 'custom'; from: string; to: string }

const DEFAULT_PRESET: RangePreset = 'Max'
export const DEFAULT_RANGE: ChartRange = {
  kind: 'preset',
  preset: DEFAULT_PRESET
}

export function presetStart(
  preset: RangePreset,
  last: string,
  first: string
): string {
  switch (preset) {
    case '1M':
      return shiftDate(last, { months: -1 })
    case '6M':
      return shiftDate(last, { months: -6 })
    case 'YTD':
      return `${last.slice(0, 4)}-01-01`
    case '1Y':
      return shiftDate(last, { years: -1 })
    case '5Y':
      return shiftDate(last, { years: -5 })
    case 'Max':
      return first
  }
}

/** A preset reaching before the loaded history is disabled, not clipped
 * (brief: Company, backfill in progress). */
export function presetFits(
  preset: RangePreset,
  first: string,
  last: string
): boolean {
  return preset === 'Max' || presetStart(preset, last, first) >= first
}

export function resolveRange(
  range: ChartRange,
  first: string,
  last: string
): { from: string; to: string } | null {
  if (!first || !last) return null
  if (range.kind === 'custom') return { from: range.from, to: range.to }
  const from = presetStart(range.preset, last, first)
  return { from: from < first ? first : from, to: last }
}

// URL form: "1Y", or "2020-01-02..2024-09-17" for a custom span.
export function parseRange(value: string | null): ChartRange {
  if (!value) return DEFAULT_RANGE
  const custom = value.match(/^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$/)
  if (custom && custom[1]! <= custom[2]!)
    return { kind: 'custom', from: custom[1]!, to: custom[2]! }
  return (PRESETS as readonly string[]).includes(value)
    ? { kind: 'preset', preset: value as RangePreset }
    : DEFAULT_RANGE
}

export function rangeToParam(range: ChartRange): string | null {
  if (range.kind === 'custom') return `${range.from}..${range.to}`
  return range.preset === DEFAULT_PRESET ? null : range.preset
}

/** The smallest custom range covering both `range` and [start, end]. */
export function widenToInclude(
  visible: { from: string; to: string },
  start: string,
  end: string
): ChartRange {
  return {
    kind: 'custom',
    from: start < visible.from ? start : visible.from,
    to: end > visible.to ? end : visible.to
  }
}
