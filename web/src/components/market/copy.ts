// Every user-facing string on the Market screen, in one place for review.
// Chrome copy: the fact, then the consequence, then the action (AGENTS.md).

export const marketCopy = {
  searchLabel: 'Search Listings',
  searchPlaceholder: 'Symbol or Company name',
  sectorLabel: 'Sector filter',
  allSectors: 'All sectors',
  loading: 'Loading Listings…',
  count: (total: number, shown: number) => `${total} Listings · ${shown} shown`,
  columns: 'Columns',
  optionalColumns: 'Optional columns',
  columnLabels: {
    symbol: 'Symbol',
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
  clearFilters: 'Clear filters',
  historyStarts: (date: string) => `History starts ${date}`,
  capUnavailable: 'Market Cap unavailable, no filing on record.',
  quoteAge: (age: string) => `Quote is ${age} old`,
  ageOld: (age: string) => `${age} old`
} as const
