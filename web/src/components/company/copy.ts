import { sharedCopy } from '../shared/copy'

// Every user-facing string on the Company screen and the Note dialog.
// Chrome copy: the fact, then the consequence, then the action (AGENTS.md).

export const companyCopy = {
  listing: 'Listing',
  stats: {
    last: 'Last',
    lastClose: 'Last close',
    change: 'Day change',
    marketCap: 'Market cap',
    range52: '52-week range',
    dayRange: 'Day range',
    fromFiling: (date: string) => `from filing dated ${date}`,
    approx: sharedCopy.capApprox,
    capUnavailable: sharedCopy.capUnavailable
  },
  rangeLabel: 'Chart range',
  customRange: 'Custom range',
  chartType: 'Chart type',
  line: 'Line',
  candles: 'Candles',
  events: 'Events',
  eventKinds: 'Event kinds',
  presetDisabled: 'Not enough history loaded for this range',
  legendNote: 'Note · yours',
  legendEvent: 'Event · sourced fact',
  legendKinds: (on: string[]) =>
    on.length ? `${on.join(', ')} on` : 'No Event kinds on',
  candleHint:
    'Candle bodies use the same gain and loss colors as the change cell',
  chartAria: (name: string, mode: string) =>
    `${name} ${mode === 'candles' ? 'adjusted OHLC' : 'adjusted close'}`,
  historyStarts: (date: string) =>
    `${sharedCopy.historyStarts(date)}. “Max” starts there.`,
  backfill: (loaded: number, expected: number) =>
    `History loading, showing ${loaded.toLocaleString('en-US')} of an expected ${expected.toLocaleString('en-US')} Trading Days.`,
  chartErrorTitle: 'Price history is unavailable',
  chartErrorBody:
    'The database connection failed. Stats and markers cannot load.',
  companyErrorTitle: 'This Company could not load',
  companyErrorBody: 'The database connection failed. Try again.',
  retry: 'Try again',
  noBarsTitle: (ticker: string) => `No price history for ${ticker} yet`,
  noBarsBody:
    'Ingest has not loaded Daily Bars for this Listing. The chart fills in when it does.',
  tabs: {
    notes: (n: number) => `Notes · ${n}`,
    events: (n: number) => `Events · ${n}`,
    label: 'Notes and Events'
  },
  noNotes: (name: string) => `No Notes on ${name}`,
  noNotesBody: 'Click a date on the chart to add one.',
  noEvents: 'No Events on record',
  noEventsBody: 'No sourced Events for this Company yet.',
  singleDate: sharedCopy.singleDate,
  range: sharedCopy.range,
  outsideRange: sharedCopy.outsideRange,
  panelHint:
    'Click an item to highlight its marker. Click a date on the chart, or drag across a range, to add a Note.',
  newNote: sharedCopy.newNote,
  eventKindLabels: {
    split: 'Split',
    reverse_split: 'Reverse split',
    cash_dividend: 'Dividend',
    symbol_change: 'Ticker change',
    spin_off: 'Spin-off',
    filing_10k: '10-K',
    filing_10q: '10-Q',
    filing_8k: '8-K',
    index_added: 'Added to S&P 500'
  } as Record<string, string>,
  eventToggles: [
    { id: 'splits', label: 'Splits', kinds: ['split', 'reverse_split'] },
    { id: '8k', label: '8-K', kinds: ['filing_8k'] },
    { id: 'dividends', label: 'Dividends', kinds: ['cash_dividend'] },
    { id: 'tickers', label: 'Ticker changes', kinds: ['symbol_change'] },
    { id: 'spinoffs', label: 'Spin-offs', kinds: ['spin_off'] },
    { id: '10k', label: '10-K', kinds: ['filing_10k'] },
    { id: '10q', label: '10-Q', kinds: ['filing_10q'] },
    { id: 'index', label: 'Date added to S&P 500', kinds: ['index_added'] }
  ]
} as const
