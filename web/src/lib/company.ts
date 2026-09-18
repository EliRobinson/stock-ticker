import type { CompanyDetail } from './api'

type ListingLike = { symbol: string; is_primary: boolean }

/** The Listing that stands for a Company (GOOGL for Alphabet): the one the
 * API marks primary, else the first. The one rule every screen uses. */
export function primaryListing<T extends ListingLike>(
  listings: readonly T[]
): T | undefined {
  return listings.find((l) => l.is_primary) ?? listings[0]
}

export function primarySymbol(
  company: Pick<CompanyDetail, 'listings'>
): string | undefined {
  return primaryListing(company.listings)?.symbol
}

export interface CompanyOption {
  cik: string
  label: string
}

/** "AAPL · Apple Inc.": how a Company appears in pickers and tags. */
export function companyOption(row: {
  cik: string
  symbol: string
  name: string
}): CompanyOption {
  return { cik: row.cik, label: `${row.symbol} · ${row.name}` }
}

/** One option per Company from Market rows. MarketRow has no is_primary
 * yet, so the row with the Company's highest volume stands in for it (the
 * primary class trades most for every multi-class issuer in the index). */
export function companyOptionsFromMarket(
  rows: readonly {
    cik: string
    symbol: string
    name: string
    volume: number | null
  }[]
): CompanyOption[] {
  const best = new Map<string, (typeof rows)[number]>()
  for (const row of rows) {
    const current = best.get(row.cik)
    if (!current || (row.volume ?? 0) > (current.volume ?? 0))
      best.set(row.cik, row)
  }
  return [...best.values()]
    .sort((a, b) => a.symbol.localeCompare(b.symbol))
    .map(companyOption)
}
