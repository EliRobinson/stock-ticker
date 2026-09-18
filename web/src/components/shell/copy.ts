// Every user-facing string in the app shell, status strip, pills and ⌘K palette.
// Chrome copy: the fact, then the consequence, then the action (AGENTS.md).

export const shellCopy = {
  brand: 'Stock Ticker',
  primaryNav: 'Primary',
  breadcrumb: 'Breadcrumb',
  nav: {
    market: 'Market',
    company: 'Company',
    notes: 'Notes',
    ask: 'Ask'
  },
  companyDisabled: 'Select a Company from the Market list',
  collapse: 'Collapse sidebar',
  expand: 'Expand sidebar',
  footer: ['Local · single user', 'DB: stock_ticker@localhost'],
  jump: 'Jump to Company',
  openAsk: 'Open Ask',
  closeAsk: 'Close Ask',
  theme: (theme: string) => `Theme: ${theme}`,
  themes: { system: 'System', light: 'Light', dark: 'Dark' },
  crumbs: {
    market: ['Market', 'Constituent list'],
    notes: ['Notes', 'All Notes'],
    company: (name: string) => ['Company', name]
  },

  status: {
    loading: 'Loading status…',
    dataAsOf: (time: string, date: string) => `Data as of ${time} · ${date}`,
    noData: 'No data yet',
    unknown: 'Status unknown',
    open: (close: string) => `Open · closes ${close}`,
    closed: (open: string) => `Closed · opens ${open}`,
    pre: (open: string) => `Pre-market · opens ${open}`,
    after: 'After-hours · closes 8:00 PM ET',
    ingest: (health: string) => `Ingest ${health}`,
    ingestLastRun: (time: string) => `last run ${time}`,
    ingestShowRun: (label: string) => `${label}. Show the last run.`,
    ingestLastRunAt: (time: string) => `Last run ${time}`,
    ingestNoRun: 'No completed run',
    ingestQuotes: (status: string) => `quotes ${status}`,
    ingestBars: (done: number, total: number) => `bars ${done}/${total}`,
    ingestFailures: (n: number) => `${n} failed runs`,
    backfill: (done: number, total: number) =>
      `History: ${done} of ${total} Listings`,
    backfillAnnounce: (pct: number) => `History ${pct}% loaded`,
    aiSpend: (spend: string, limit: string) => `AI ${spend} of ${limit}`,
    aiSpent: 'AI spend limit reached',
    aiSpendHint: 'Anthropic spend to date, against AI_SPEND_LIMIT_USD'
  },

  palette: {
    title: 'Jump to Company',
    description: 'Search by symbol or Company name.',
    placeholder: 'Symbol or Company name',
    empty: 'No Company matches.',
    move: '↑↓ move',
    open: '↵ open Company',
    anywhere: '⌘K anywhere'
  }
} as const

export const boundaryCopy = {
  title: 'This screen stopped working',
  body: 'An error stopped the screen from rendering. Try again.',
  retry: 'Try again',
  notFoundTitle: 'No Company at this address',
  notFoundBody:
    'The link does not match a Company in the Constituent List. Pick one from the Market list.',
  toMarket: 'Go to Market'
} as const
