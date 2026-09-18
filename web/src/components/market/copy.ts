import { sharedCopy } from '../shared/copy'

// Every user-facing string on the Market screen, in one place for review.

export const marketCopy = {
  searchLabel: 'Search Listings',
  searchPlaceholder: sharedCopy.tickerOrName,
  sectorLabel: 'Sector filter',
  sector: 'Sector',
  allSectors: 'All sectors',
  loading: 'Loading Listings…',
  count: (total: number, shown: number) => `${total} Listings · ${shown} shown`,
  columns: 'Columns',
  filters: 'Filters and columns',
  optionalColumns: 'Optional columns',
  columnLabels: {
    symbol: sharedCopy.ticker,
    name: 'Company',
    sector: 'Sector',
    price: 'Last',
    priceClosed: 'Last close',
    priceStale: 'Last (stale)',
    change: 'Day change',
    marketCap: 'Market cap',
    volume: 'Volume',
    age: 'Quote age',
    ageClosed: 'Since close'
  },
  tableLabel: 'Constituent list',
  apiDownTitle: 'Quotes are unavailable',
  apiDownBody: 'The Alpaca connection is down.',
  apiDownUpdated: (time: string, date: string) =>
    ` Prices last updated ${time}, ${date}.`,
  missingKeyTitle: 'No Alpaca API key is configured',
  firstRunTitle: 'No Listings loaded',
  firstRunBody:
    'Ingest has not completed a first run. Start it from the terminal, or wait for the scheduled run.',
  noMatchTitle: (query: string) =>
    query ? `No Listings match “${query}”` : 'No Listings match these filters',
  noMatchBody: 'Clear the search or adjust the sector filter.',
  searchChip: (query: string) => `“${query}”`
} as const
