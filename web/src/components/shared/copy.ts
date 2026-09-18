// Strings more than one screen uses. Screen-specific copy lives in each
// screen's own copy.ts. Chrome copy: the fact, then the consequence, then
// the action (AGENTS.md). CONTEXT.md's terms: "ticker", not "symbol".

export const sharedCopy = {
  ticker: 'Ticker',
  tickerOrName: 'Ticker or Company name',
  wholeMarket: 'Whole market',
  newNote: 'New Note',
  clearFilters: 'Clear filters',
  removeFilter: (label: string) => `Remove filter: ${label}`,
  readMore: 'Read more',
  showLess: 'Show less',
  singleDate: 'single date',
  range: 'range',
  outsideRange: 'Outside chart range',
  historyStarts: (date: string) => `History starts ${date}`,
  capUnavailable: 'Market Cap unavailable, no filing on record.',
  capApprox:
    'Approximate: a multi-class Company, valued by a seeded share rule.',
  ageOld: (age: string) => `${age} old`,
  quoteAge: (age: string) => `Quote is ${age} old`,
  viewFailed:
    'This result could not be drawn. Its data did not match the expected shape.'
} as const
