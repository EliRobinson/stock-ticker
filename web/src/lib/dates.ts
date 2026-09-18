import { NY_TZ } from './format'

/** The first Trading Day the ingest backfills (system design §1, F1). A
 * Listing whose history starts later has partial history. */
export const HISTORY_START = '2018-01-02'

/** Today's Trading Day date in New York time (CONTEXT.md), as YYYY-MM-DD. */
export function todayInNewYork(now: Date = new Date()): string {
  return now.toLocaleDateString('en-CA', { timeZone: NY_TZ })
}

function toUtcNoon(date: string): Date {
  return new Date(`${date}T12:00:00Z`)
}

/** Calendar arithmetic on bare YYYY-MM-DD dates, done at UTC noon so no time
 * zone can roll the day. */
export function shiftDate(
  date: string,
  { months = 0, years = 0 }: { months?: number; years?: number }
): string {
  const d = toUtcNoon(date)
  d.setUTCFullYear(d.getUTCFullYear() + years, d.getUTCMonth() + months)
  return d.toISOString().slice(0, 10)
}

/** Weekdays in [from, to]: an upper bound on Trading Days (it counts
 * holidays), used to size a partial-history banner. */
export function weekdaysBetween(from: string, to: string): number {
  let n = 0
  const end = toUtcNoon(to).getTime()
  for (let t = toUtcNoon(from).getTime(); t <= end; t += 86_400_000) {
    const dow = new Date(t).getUTCDay()
    if (dow !== 0 && dow !== 6) n++
  }
  return n
}
