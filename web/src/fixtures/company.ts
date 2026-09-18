import type { Bar, CompanyDetail, EventsResponse, MarketEvent } from '@/lib/api'

export const LAST_TRADING_DAY = '2024-09-17'

export const apple: CompanyDetail = {
  cik: '0000320193',
  name: 'Apple Inc.',
  sector: 'Information Technology',
  sub_industry: 'Technology Hardware, Storage & Peripherals',
  headquarters: null,
  date_added: null,
  is_active: true,
  listings: [
    {
      symbol: 'AAPL',
      is_primary: true,
      is_active: true,
      first_bar_date: '2018-01-02',
      backfill_completed_at: null
    }
  ],
  market_cap: {
    market_cap: (3.44e12).toFixed(0),
    shares_as_of: '2024-06-28',
    is_approx: false
  },
  week_52_low: '164.08',
  week_52_high: '237.49',
  first_bar_date: '2018-01-02'
}

export const alphabet: CompanyDetail = {
  cik: '0001652044',
  name: 'Alphabet Inc.',
  sector: 'Communication Services',
  sub_industry: 'Interactive Media & Services',
  headquarters: null,
  date_added: null,
  is_active: true,
  listings: [
    {
      symbol: 'GOOGL',
      is_primary: true,
      is_active: true,
      first_bar_date: '2018-01-02',
      backfill_completed_at: null
    },
    {
      symbol: 'GOOG',
      is_primary: false,
      is_active: true,
      first_bar_date: '2018-01-02',
      backfill_completed_at: null
    }
  ],
  market_cap: {
    market_cap: (2.02e12).toFixed(0),
    shares_as_of: '2024-06-30',
    is_approx: true
  },
  week_52_low: '127.9',
  week_52_high: '191.75',
  first_bar_date: '2018-01-02'
}

export const solventum: CompanyDetail = {
  cik: '0001964738',
  name: 'Solventum Corporation',
  sector: 'Health Care',
  sub_industry: 'Health Care Equipment',
  headquarters: null,
  date_added: null,
  is_active: true,
  listings: [
    {
      symbol: 'SOLV',
      is_primary: true,
      is_active: true,
      first_bar_date: '2021-03-12',
      backfill_completed_at: null
    }
  ],
  market_cap: null,
  week_52_low: '31.04',
  week_52_high: '51.66',
  first_bar_date: '2021-03-12'
}

export const tsmc: CompanyDetail = {
  cik: '0001046179',
  name: 'Taiwan Semiconductor Manufacturing Company Limited',
  sector: 'Information Technology',
  sub_industry: 'Semiconductors',
  headquarters: null,
  date_added: null,
  is_active: true,
  listings: [
    {
      symbol: 'TSM',
      is_primary: true,
      is_active: true,
      first_bar_date: '2018-01-02',
      backfill_completed_at: null
    }
  ],
  market_cap: {
    market_cap: (883.7e9).toFixed(0),
    shares_as_of: '2024-06-30',
    is_approx: false
  },
  week_52_low: '84.2',
  week_52_high: '193.47',
  first_bar_date: '2018-01-02'
}

export const companies: CompanyDetail[] = [apple, alphabet, solventum, tsmc]

interface Anchor {
  date: string
  value: number
}

// Adjusted-close anchors per Company, joined by a seeded walk, so the fixture
// chart has a recognisable shape (the 2020 drawdown, the 2022 bear market).
const SHAPES: Record<string, Anchor[]> = {
  AAPL: [
    { date: '2018-01-02', value: 41.1 },
    { date: '2018-10-03', value: 55.4 },
    { date: '2019-01-03', value: 34.6 },
    { date: '2020-01-02', value: 73.1 },
    { date: '2020-02-19', value: 79.2 },
    { date: '2020-03-23', value: 55.4 },
    { date: '2020-09-01', value: 132.4 },
    { date: '2021-01-04', value: 127.2 },
    { date: '2022-01-03', value: 180.4 },
    { date: '2022-06-16', value: 129.0 },
    { date: '2023-01-03', value: 123.6 },
    { date: '2023-07-31', value: 195.1 },
    { date: '2024-01-02', value: 184.3 },
    { date: '2024-04-19', value: 164.1 },
    { date: '2024-07-15', value: 234.4 },
    { date: '2024-09-17', value: 227.52 }
  ],
  GOOGL: [
    { date: '2018-01-02', value: 53.6 },
    { date: '2019-01-03', value: 50.8 },
    { date: '2020-02-19', value: 76.0 },
    { date: '2020-03-23', value: 53.6 },
    { date: '2021-11-18', value: 149.6 },
    { date: '2022-11-03', value: 83.4 },
    { date: '2023-12-29', value: 139.7 },
    { date: '2024-07-10', value: 191.2 },
    { date: '2024-09-17', value: 164.76 }
  ],
  SOLV: [
    { date: '2021-03-12', value: 34.1 },
    { date: '2022-06-01', value: 31.9 },
    { date: '2023-09-01', value: 44.2 },
    { date: '2024-09-17', value: 48.72 }
  ],
  TSM: [
    { date: '2018-01-02', value: 36.2 },
    { date: '2020-03-23', value: 41.0 },
    { date: '2021-02-16', value: 132.1 },
    { date: '2022-10-24', value: 58.8 },
    { date: '2024-07-11', value: 193.5 },
    { date: '2024-09-17', value: 170.4 }
  ]
}

function tradingDays(from: string, to: string): string[] {
  const out: string[] = []
  const end = Date.parse(`${to}T00:00:00Z`)
  for (let t = Date.parse(`${from}T00:00:00Z`); t <= end; t += 86_400_000) {
    const d = new Date(t)
    const dow = d.getUTCDay()
    if (dow !== 0 && dow !== 6) out.push(d.toISOString().slice(0, 10))
  }
  return out
}

function seeded(seed: number) {
  let s = seed
  return () => {
    s = (s * 1103515245 + 12345) % 2147483648
    return s / 2147483648
  }
}

function interpolate(anchors: Anchor[], date: string): number {
  const t = Date.parse(date)
  for (let i = 0; i < anchors.length - 1; i++) {
    const a = anchors[i]!
    const b = anchors[i + 1]!
    const ta = Date.parse(a.date)
    const tb = Date.parse(b.date)
    if (t >= ta && t <= tb) {
      const f = (t - ta) / (tb - ta)
      return a.value + (b.value - a.value) * f
    }
  }
  return anchors[anchors.length - 1]!.value
}

export function buildBars(
  symbol: string,
  to = LAST_TRADING_DAY,
  limitDays?: number
): Bar[] {
  const shape = SHAPES[symbol] ?? SHAPES.AAPL!
  let days = tradingDays(shape[0]!.date, to)
  if (limitDays) days = days.slice(0, limitDays)
  const rnd = seeded(symbol.length * 7919 + (symbol.charCodeAt(0) || 1))
  const bars: Bar[] = days.map((date, i) => {
    const base = interpolate(shape, date)
    const wiggle =
      0.05 * Math.sin(i / 9 + symbol.length) +
      0.035 * Math.sin(i / 23 + 1.3) +
      0.025 * Math.sin(i / 61)
    const noise = base * wiggle + (rnd() - 0.5) * base * 0.015
    const close = Number(Math.max(base + noise, 1).toFixed(2))
    const open = Number((close * (1 + (rnd() - 0.5) * 0.02)).toFixed(2))
    const high = Number(
      (Math.max(open, close) * (1 + rnd() * 0.012)).toFixed(2)
    )
    const low = Number((Math.min(open, close) * (1 - rnd() * 0.012)).toFixed(2))
    const last = !limitDays && i === days.length - 1
    const finalClose = last ? shape[shape.length - 1]!.value : close
    return {
      trade_date: date,
      open: open.toFixed(2),
      high: Math.max(high, finalClose).toFixed(2),
      low: Math.min(low, finalClose).toFixed(2),
      close: finalClose.toFixed(2),
      volume: Math.round((30 + rnd() * 60) * 1e6),
      adj_close: finalClose.toFixed(2)
    }
  })
  return bars
}

const ev = (
  id: number,
  cik: string,
  symbol: string,
  eventDate: string,
  kind: MarketEvent['kind'],
  title: string
): MarketEvent => ({
  id,
  cik,
  symbol,
  event_date: eventDate,
  kind,
  title,
  details: {},
  source: kind.startsWith('filing') ? 'sec_edgar' : 'alpaca',
  source_ref: `${symbol}-${eventDate}-${kind}`
})

export const appleEvents: EventsResponse = {
  items: [
    ev(1, apple.cik, 'AAPL', '2020-08-31', 'split', '4-for-1 split'),
    ev(2, apple.cik, 'AAPL', '2022-04-28', 'filing_8k', '8-K · Q2 results'),
    ev(3, apple.cik, 'AAPL', '2023-11-03', 'filing_10k', '10-K · FY 2023'),
    ev(
      4,
      apple.cik,
      'AAPL',
      '2024-05-02',
      'filing_8k',
      '8-K · $110B buyback authorised'
    ),
    ev(5, apple.cik, 'AAPL', '2024-08-02', 'filing_10q', '10-Q · Q3 2024'),
    ev(6, apple.cik, 'AAPL', '2024-08-12', 'cash_dividend', 'Dividend $0.25'),
    ev(7, apple.cik, 'AAPL', '2019-02-08', 'cash_dividend', 'Dividend $0.73'),
    ev(8, apple.cik, 'AAPL', '2021-10-29', 'filing_10k', '10-K · FY 2021'),
    ev(9, apple.cik, 'AAPL', '2018-11-02', 'filing_8k', '8-K · Q4 2018 results')
  ],
  next_cursor: null
}

export const alphabetEvents: EventsResponse = {
  items: [
    ev(
      20,
      alphabet.cik,
      'GOOGL',
      '2022-07-15',
      'split',
      '20-for-1 split · Class A and C'
    ),
    ev(21, alphabet.cik, 'GOOGL', '2024-07-25', 'filing_10q', '10-Q · Q2 2024'),
    ev(
      22,
      alphabet.cik,
      'GOOGL',
      '2024-04-25',
      'filing_8k',
      '8-K · First dividend declared'
    ),
    ev(23, alphabet.cik, 'GOOGL', '2024-01-31', 'filing_10k', '10-K · FY 2023'),
    ev(
      24,
      alphabet.cik,
      'GOOGL',
      '2021-09-02',
      'symbol_change',
      'GOOG → GOOGL primary'
    ),
    ev(
      25,
      alphabet.cik,
      'GOOGL',
      '2020-04-03',
      'index_added',
      'Added to S&P 500'
    )
  ],
  next_cursor: null
}

export const noEvents: EventsResponse = { items: [], next_cursor: null }
