// A Trading Day is dated in New York time (CONTEXT.md).
export function todayInNewYork(now = new Date()): string {
  return now.toLocaleDateString('en-CA', { timeZone: 'America/New_York' })
}
