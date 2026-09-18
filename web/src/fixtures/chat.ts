import type { ChatUIMessage as AskMessage } from '@/lib/chat'

import { buildBars } from './company'

const COVID_SQL = `select symbol,
       first_value(adj_close) over w as start_px,
       last_value(adj_close)  over w as end_px
  from ai.daily_bars
 where trade_date between '2020-02-19' and '2020-03-23'
window w as (partition by symbol order by trade_date
             rows between unbounded preceding and unbounded following)
 order by end_px / start_px asc
 limit 10;`

const user = (id: string, text: string): AskMessage => ({
  id,
  role: 'user',
  parts: [{ type: 'text', text }]
})

export const chatTableAnswer: AskMessage[] = [
  user('u1', 'Which companies fell most when COVID struck?'),
  {
    id: 'a1',
    role: 'assistant',
    parts: [
      {
        type: 'tool-run_sql',
        toolCallId: 't1',
        state: 'output-available',
        input: { sql: COVID_SQL, purpose: 'Queried daily_bars · 503 Listings' },
        output: {
          result_id: 'r1',
          columns: [],
          rows: [],
          row_count: 503,
          row_count_is_capped: false,
          truncated: false
        }
      },
      {
        type: 'text',
        state: 'done',
        text: 'Between 19 Feb and 23 Mar 2020 the index fell 33.9%. The steepest single-name drawdowns were cruise, airline and energy:'
      },
      {
        type: 'data-view',
        id: 'v1',
        data: {
          kind: 'table',
          id: 'v1',
          title: 'Worst drawdowns, 19 Feb – 23 Mar 2020',
          columns: [
            { key: 'symbol', label: 'Symbol', format: 'text' },
            { key: 'start_px', label: '19 Feb', format: 'number' },
            { key: 'end_px', label: '23 Mar', format: 'number' },
            { key: 'change_pct', label: 'Change', format: 'percent' }
          ],
          rows: [
            {
              symbol: 'NCLH',
              start_px: 56.29,
              end_px: 8.05,
              change_pct: -85.7
            },
            { symbol: 'CCL', start_px: 45.71, end_px: 8.8, change_pct: -80.75 },
            {
              symbol: 'MGM',
              start_px: 33.28,
              end_px: 7.14,
              change_pct: -78.55
            },
            {
              symbol: 'OXY',
              start_px: 45.28,
              end_px: 11.15,
              change_pct: -75.38
            },
            {
              symbol: 'UAL',
              start_px: 78.55,
              end_px: 21.31,
              change_pct: -72.87
            }
          ]
        }
      }
    ]
  }
]

const monthly = buildBars('AAPL')
  .filter((b) => b.trade_date >= '2020-01-02')
  .filter((_, i, all) => i % 21 === 0 || i === all.length - 1)
  .map((b) => ({ trade_date: b.trade_date, adj_close: Number(b.adj_close) }))

export const chatChartAnswer: AskMessage[] = [
  user('u2', 'AAPL adjusted close since 2020'),
  {
    id: 'a2',
    role: 'assistant',
    parts: [
      {
        type: 'tool-run_sql',
        toolCallId: 't2',
        state: 'output-available',
        input: {
          sql: "select trade_date, adj_close\n  from ai.daily_bars\n where symbol = 'AAPL' and trade_date >= '2020-01-02'\n order by trade_date;",
          purpose: 'Queried daily_bars · AAPL'
        },
        output: {
          result_id: 'r2',
          columns: [],
          rows: [],
          row_count: 1182,
          row_count_is_capped: false,
          truncated: false
        }
      },
      {
        type: 'text',
        state: 'done',
        text: 'From 73.10 on 2 Jan 2020 to 227.52 on 17 Sep 2024, a 211.2% total return on adjusted close.'
      },
      {
        type: 'data-view',
        id: 'v2',
        data: {
          kind: 'timeseries',
          id: 'v2',
          title: 'AAPL adjusted close',
          x: 'trade_date',
          series: [{ key: 'adj_close', label: 'AAPL' }],
          y_format: 'number',
          rows: monthly
        }
      }
    ]
  }
]

export const chatStreaming: AskMessage[] = [
  user('u3', 'Top 10 Companies by Market Cap, 2020–2021'),
  {
    id: 'a3',
    role: 'assistant',
    parts: [
      {
        type: 'tool-run_sql',
        toolCallId: 't3a',
        state: 'output-available',
        input: {
          sql: 'select count(*) from ai.listings;',
          purpose: 'Resolved 503 Listings'
        },
        output: {
          result_id: 'r3a',
          columns: [],
          rows: [[503]],
          row_count: 1,
          row_count_is_capped: false,
          truncated: false
        }
      },
      {
        type: 'tool-run_sql',
        toolCallId: 't3b',
        state: 'output-available',
        input: {
          sql: 'select * from ai.market_caps limit 1;',
          purpose: 'Read market_cap snapshots'
        },
        output: {
          result_id: 'r3b',
          columns: [],
          rows: [],
          row_count: 503,
          row_count_is_capped: false,
          truncated: false
        }
      },
      {
        type: 'tool-run_sql',
        toolCallId: 't3c',
        state: 'input-available',
        input: {
          sql: "select * from ai.daily_bars where trade_date between '2020-01-02' and '2021-12-31';",
          purpose: 'Querying daily_bars, 2020-01-02 → 2021-12-31'
        }
      },
      {
        type: 'text',
        state: 'streaming',
        text: 'Through 2020 and 2021 the top of the index held steady: the same five names held the top five in every quarter, with Tesla the only'
      }
    ]
  }
]

export const chatBackendDown: AskMessage[] = [
  user('u4', 'Top 10 by Market Cap, 2021')
]

export const chatQueryFailed: AskMessage[] = [
  user('u5', 'Which of my notes mention buybacks near a split?'),
  {
    id: 'a5',
    role: 'assistant',
    parts: [
      {
        type: 'tool-run_sql',
        toolCallId: 't5',
        state: 'output-error',
        input: {
          sql: "select n.id, n.body from ai.notes n\n  join ai.events e on e.cik = n.cik\n where e.kind = 'split' and n.body ilike '%buyback%'\n   and abs(n.start_date - e.event_date) <= 5;",
          purpose: 'Joined Notes to split Events'
        },
        errorText: 'column n.start_date does not exist'
      }
    ]
  }
]
