import type { MarketResponse, MarketRow } from '@/lib/api'

// A September 2024 session, as drawn in the Claude Design board (frame G1).
export const FIXTURE_NOW = '2024-09-17T15:42:07Z'
export const NEXT_CLOSE = '2024-09-17T20:00:00Z'
export const NEXT_OPEN = '2024-09-18T13:30:00Z'

type Seed = [
  symbol: string,
  cik: string,
  name: string,
  sector: string,
  price: number,
  changePct: number,
  change: number,
  marketCap: number | null,
  volume: number
]

const T = 1e12
const B = 1e9
const M = 1e6

const SEEDS: Seed[] = [
  [
    'AAPL',
    '0000320193',
    'Apple Inc.',
    'Information Technology',
    227.52,
    0.83,
    1.87,
    3.44 * T,
    48.2 * M
  ],
  [
    'MSFT',
    '0000789019',
    'Microsoft Corporation',
    'Information Technology',
    415.26,
    -0.41,
    -1.71,
    3.09 * T,
    18.4 * M
  ],
  [
    'NVDA',
    '0001045810',
    'NVIDIA Corporation',
    'Information Technology',
    124.92,
    2.14,
    2.62,
    3.07 * T,
    241.6 * M
  ],
  [
    'AMZN',
    '0001018724',
    'Amazon.com, Inc.',
    'Consumer Discretionary',
    186.33,
    1.05,
    1.94,
    1.95 * T,
    34.1 * M
  ],
  [
    'GOOGL',
    '0001652044',
    'Alphabet Inc. Class A',
    'Communication Services',
    164.76,
    0.52,
    0.85,
    2.02 * T,
    21.7 * M
  ],
  [
    'META',
    '0001326801',
    'Meta Platforms, Inc. Class A',
    'Communication Services',
    561.35,
    -0.28,
    -1.58,
    1.42 * T,
    11.2 * M
  ],
  [
    'BRK.B',
    '0001067983',
    'Berkshire Hathaway Inc. Class B',
    'Financials',
    462.1,
    0.11,
    0.51,
    996.4 * B,
    3.1 * M
  ],
  [
    'LLY',
    '0000059478',
    'Eli Lilly and Company',
    'Health Care',
    905.42,
    -1.23,
    -11.28,
    860.1 * B,
    2.4 * M
  ],
  [
    'AVGO',
    '0001730168',
    'Broadcom Inc.',
    'Information Technology',
    162.44,
    3.02,
    4.76,
    757.8 * B,
    29.8 * M
  ],
  [
    'XOM',
    '0000034088',
    'Exxon Mobil Corporation',
    'Energy',
    117.32,
    0,
    0,
    519.4 * B,
    14.6 * M
  ],
  [
    'GOOG',
    '0001652044',
    'Alphabet Inc. Class C',
    'Communication Services',
    166.14,
    0.49,
    0.81,
    2.02 * T,
    15.3 * M
  ],
  [
    'TSLA',
    '0001318605',
    'Tesla, Inc.',
    'Consumer Discretionary',
    227.87,
    0.31,
    0.7,
    728.1 * B,
    66.3 * M
  ],
  [
    'JPM',
    '0000019617',
    'JPMorgan Chase & Co.',
    'Financials',
    210.8,
    -0.62,
    -1.31,
    603.9 * B,
    8.2 * M
  ],
  [
    'UNH',
    '0000731766',
    'UnitedHealth Group Incorporated',
    'Health Care',
    581.02,
    0.44,
    2.55,
    534.7 * B,
    2.9 * M
  ],
  [
    'V',
    '0001403161',
    'Visa Inc.',
    'Financials',
    283.4,
    0.18,
    0.51,
    553.2 * B,
    5.4 * M
  ],
  [
    'MA',
    '0001141391',
    'Mastercard Incorporated',
    'Financials',
    494.9,
    0.27,
    1.33,
    459.1 * B,
    2.1 * M
  ],
  [
    'PG',
    '0000080424',
    'The Procter & Gamble Company',
    'Consumer Staples',
    174.2,
    -0.35,
    -0.61,
    410.9 * B,
    5.8 * M
  ],
  [
    'JNJ',
    '0000200406',
    'Johnson & Johnson',
    'Health Care',
    164.5,
    0.12,
    0.2,
    395.9 * B,
    5.6 * M
  ],
  [
    'HD',
    '0000354950',
    'The Home Depot, Inc.',
    'Consumer Discretionary',
    393.1,
    1.41,
    5.47,
    390.2 * B,
    3.3 * M
  ],
  [
    'COST',
    '0000909832',
    'Costco Wholesale Corporation',
    'Consumer Staples',
    911.3,
    -0.52,
    -4.76,
    404.1 * B,
    1.6 * M
  ],
  [
    'ABBV',
    '0001551152',
    'AbbVie Inc.',
    'Health Care',
    193.2,
    0.84,
    1.61,
    341.5 * B,
    4.7 * M
  ],
  [
    'MRK',
    '0000310158',
    'Merck & Co., Inc.',
    'Health Care',
    117.6,
    -0.19,
    -0.22,
    297.9 * B,
    6.9 * M
  ],
  [
    'WMT',
    '0000104169',
    'Walmart Inc.',
    'Consumer Staples',
    80.9,
    0.37,
    0.3,
    650.3 * B,
    13.8 * M
  ],
  [
    'NFLX',
    '0001065280',
    'Netflix, Inc.',
    'Communication Services',
    697.1,
    0.92,
    6.35,
    299.8 * B,
    2.6 * M
  ],
  [
    'KO',
    '0000021344',
    'The Coca-Cola Company',
    'Consumer Staples',
    71.6,
    -0.08,
    -0.06,
    308.4 * B,
    11.9 * M
  ],
  [
    'PEP',
    '0000077476',
    'PepsiCo, Inc.',
    'Consumer Staples',
    175.4,
    -0.44,
    -0.78,
    240.9 * B,
    4.1 * M
  ],
  [
    'ADBE',
    '0000796343',
    'Adobe Inc.',
    'Information Technology',
    525.7,
    -1.02,
    -5.42,
    233.1 * B,
    3.8 * M
  ],
  [
    'CRM',
    '0001108524',
    'Salesforce, Inc.',
    'Information Technology',
    257.3,
    1.66,
    4.2,
    246.0 * B,
    6.1 * M
  ],
  [
    'ORCL',
    '0001341439',
    'Oracle Corporation',
    'Information Technology',
    167.7,
    0.72,
    1.2,
    464.8 * B,
    9.4 * M
  ],
  [
    'AMD',
    '0000002488',
    'Advanced Micro Devices, Inc.',
    'Information Technology',
    152.1,
    1.93,
    2.88,
    246.2 * B,
    37.2 * M
  ],
  [
    'CSCO',
    '0000858877',
    'Cisco Systems, Inc.',
    'Information Technology',
    51.2,
    0.39,
    0.2,
    205.1 * B,
    17.3 * M
  ],
  [
    'INTC',
    '0000050863',
    'Intel Corporation',
    'Information Technology',
    21.8,
    2.83,
    0.6,
    93.2 * B,
    104.5 * M
  ],
  [
    'BAC',
    '0000070858',
    'Bank of America Corporation',
    'Financials',
    39.7,
    -0.9,
    -0.36,
    308.5 * B,
    36.2 * M
  ],
  [
    'WFC',
    '0000072971',
    'Wells Fargo & Company',
    'Financials',
    55.1,
    -0.54,
    -0.3,
    188.0 * B,
    15.1 * M
  ],
  [
    'GS',
    '0000886982',
    'The Goldman Sachs Group, Inc.',
    'Financials',
    486.3,
    0.22,
    1.07,
    153.2 * B,
    1.9 * M
  ],
  [
    'CVX',
    '0000093410',
    'Chevron Corporation',
    'Energy',
    142.9,
    -0.33,
    -0.47,
    257.7 * B,
    6.4 * M
  ],
  [
    'COP',
    '0001163165',
    'ConocoPhillips',
    'Energy',
    106.1,
    -0.71,
    -0.76,
    124.3 * B,
    5.2 * M
  ],
  [
    'OXY',
    '0000797468',
    'Occidental Petroleum Corporation',
    'Energy',
    54.9,
    -1.12,
    -0.62,
    51.5 * B,
    8.8 * M
  ],
  [
    'NEE',
    '0000753308',
    'NextEra Energy, Inc.',
    'Utilities',
    83.6,
    0.57,
    0.47,
    171.8 * B,
    8.3 * M
  ],
  [
    'DUK',
    '0001326160',
    'Duke Energy Corporation',
    'Utilities',
    118.4,
    0.25,
    0.3,
    91.4 * B,
    2.8 * M
  ],
  [
    'SO',
    '0000092122',
    'The Southern Company',
    'Utilities',
    89.2,
    0.16,
    0.14,
    97.7 * B,
    3.9 * M
  ],
  [
    'LIN',
    '0001707925',
    'Linde plc',
    'Materials',
    477.9,
    0.41,
    1.95,
    228.8 * B,
    1.4 * M
  ],
  [
    'SHW',
    '0000089800',
    'The Sherwin-Williams Company',
    'Materials',
    381.0,
    1.08,
    4.07,
    96.0 * B,
    1.2 * M
  ],
  [
    'CAT',
    '0000018230',
    'Caterpillar Inc.',
    'Industrials',
    364.8,
    1.52,
    5.46,
    177.1 * B,
    2.6 * M
  ],
  [
    'GE',
    '0000040545',
    'GE Aerospace',
    'Industrials',
    180.4,
    0.64,
    1.15,
    196.2 * B,
    4.8 * M
  ],
  [
    'GEV',
    '0001996810',
    'GE Vernova Inc.',
    'Industrials',
    244.1,
    2.41,
    5.74,
    null,
    3.2 * M
  ],
  [
    'HON',
    '0000773840',
    'Honeywell International Inc.',
    'Industrials',
    206.5,
    -0.21,
    -0.43,
    134.3 * B,
    2.9 * M
  ],
  [
    'UPS',
    '0001090727',
    'United Parcel Service, Inc.',
    'Industrials',
    128.3,
    -0.47,
    -0.61,
    109.6 * B,
    3.7 * M
  ],
  [
    'UAL',
    '0000100517',
    'United Airlines Holdings, Inc.',
    'Industrials',
    50.8,
    2.26,
    1.12,
    16.7 * B,
    9.6 * M
  ],
  [
    'NCLH',
    '0001513761',
    'Norwegian Cruise Line Holdings Ltd.',
    'Consumer Discretionary',
    19.4,
    1.73,
    0.33,
    8.5 * B,
    12.1 * M
  ],
  [
    'CCL',
    '0000815097',
    'Carnival Corporation & plc',
    'Consumer Discretionary',
    17.6,
    1.44,
    0.25,
    22.9 * B,
    21.6 * M
  ],
  [
    'MGM',
    '0000789570',
    'MGM Resorts International',
    'Consumer Discretionary',
    37.9,
    0.8,
    0.3,
    11.9 * B,
    3.1 * M
  ],
  [
    'NVR',
    '0000906163',
    'NVR, Inc.',
    'Consumer Discretionary',
    8214.3,
    -0.62,
    -51.23,
    26.3 * B,
    0.02 * M
  ],
  [
    'NI',
    '0001111711',
    'NiSource Inc.',
    'Utilities',
    33.11,
    0.3,
    0.1,
    15.5 * B,
    3.4 * M
  ],
  [
    'AMT',
    '0001053507',
    'American Tower Corporation',
    'Real Estate',
    237.6,
    0.49,
    1.16,
    111.1 * B,
    1.8 * M
  ],
  [
    'PLD',
    '0001045609',
    'Prologis, Inc.',
    'Real Estate',
    127.4,
    0.35,
    0.44,
    118.0 * B,
    3.2 * M
  ],
  [
    'VLTO',
    '0001967680',
    'Veralto Corporation',
    'Industrials',
    112.3,
    0.19,
    0.21,
    27.8 * B,
    1.1 * M
  ],
  [
    'KVUE',
    '0001944048',
    'Kenvue Inc.',
    'Consumer Staples',
    22.4,
    -0.27,
    -0.06,
    42.9 * B,
    13.7 * M
  ],
  [
    'SOLV',
    '0001964738',
    'Solventum Corporation',
    'Health Care',
    68.2,
    1.18,
    0.8,
    null,
    1.6 * M
  ],
  [
    'TSM',
    '0001046179',
    'Taiwan Semiconductor Manufacturing Company Limited',
    'Information Technology',
    170.4,
    1.37,
    2.3,
    883.7 * B,
    14.2 * M
  ]
]

const RECENT_LISTINGS: Record<string, string> = {
  GEV: '2024-03-27',
  VLTO: '2023-10-02',
  KVUE: '2023-05-04',
  SOLV: '2024-04-01'
}

const ageSecondsBySymbol = (i: number) => 12 + (i % 5)

export function buildMarketRows(now = FIXTURE_NOW): MarketRow[] {
  const nowMs = Date.parse(now)
  return SEEDS.map(
    ([symbol, cik, name, sector, price, pct, change, cap, volume], i) => {
      const firstBarDate = RECENT_LISTINGS[symbol] ?? '2018-01-02'
      return {
        symbol,
        cik,
        name,
        sector,
        price: price.toFixed(2),
        observed_at: new Date(
          nowMs - ageSecondsBySymbol(i) * 1000
        ).toISOString(),
        prev_close: (price - change).toFixed(2),
        change: change.toFixed(2),
        change_pct: pct.toFixed(2),
        volume: Math.round(volume),
        market_cap: cap == null ? null : cap.toFixed(0),
        market_cap_is_approx:
          symbol === 'GOOGL' || symbol === 'GOOG' || symbol === 'BRK.B',
        first_bar_date: firstBarDate,
        backfill_completed_at: `${firstBarDate}T20:00:00Z`,
        is_primary: symbol !== 'GOOG'
      }
    }
  )
}

export const marketOpen: MarketResponse = {
  server_time: FIXTURE_NOW,
  market_clock: { is_open: true, next_open: NEXT_OPEN, next_close: NEXT_CLOSE },
  listings: buildMarketRows()
}

const STALE_MINUTES = [4, 14, 22, 9, 31]

export const marketStale: MarketResponse = {
  ...marketOpen,
  listings: marketOpen.listings.map((r, i) => ({
    ...r,
    observed_at: new Date(
      Date.parse(FIXTURE_NOW) - (STALE_MINUTES[i % 5] ?? 4) * 60_000
    ).toISOString()
  }))
}

export const marketApiDown: MarketResponse = {
  ...marketOpen,
  listings: marketOpen.listings.map((r) => ({
    ...r,
    observed_at: '2024-09-17T13:58:14Z'
  }))
}

// 11h 12m after the 16 Sep close, before pre-market opens.
export const CLOSED_NOW = '2024-09-17T07:12:00Z'
export const marketClosed: MarketResponse = {
  server_time: CLOSED_NOW,
  market_clock: {
    is_open: false,
    next_open: '2024-09-17T13:30:00Z',
    next_close: '2024-09-17T20:00:00Z'
  },
  listings: marketOpen.listings.map((r) => ({
    ...r,
    observed_at: '2024-09-16T20:00:00Z'
  }))
}

export const marketBackfill: MarketResponse = {
  ...marketOpen,
  listings: marketOpen.listings.map((r, i) =>
    i % 3 === 0
      ? r
      : {
          ...r,
          first_bar_date: null,
          backfill_completed_at: null,
          prev_close: null,
          change: null,
          change_pct: null,
          market_cap: null
        }
  )
}

export const marketPartial: MarketResponse = {
  ...marketOpen,
  listings: marketOpen.listings.map((r) => {
    if (r.symbol === 'MSFT') return { ...r, market_cap: null }
    if (r.symbol === 'AMZN') {
      return {
        ...r,
        first_bar_date: '2021-03-12',
        change: null,
        change_pct: null
      }
    }
    return r
  })
}

export const marketEmpty: MarketResponse = { ...marketOpen, listings: [] }
