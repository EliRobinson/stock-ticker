import type { AiStatus } from '@/components/shell/status-strip'
import type { StatusResponse } from '@/lib/api'

import { CLOSED_NOW, FIXTURE_NOW, NEXT_CLOSE, NEXT_OPEN } from './market'

type Job = StatusResponse['jobs'][number]

const okJobs: Job[] = [
  {
    job: 'quotes',
    status: 'succeeded',
    finished_at: '2024-09-17T15:42:02Z',
    last_success_at: '2024-09-17T15:42:02Z',
    consecutive_failures: 0,
    error_summary: null
  },
  {
    job: 'bars_daily',
    status: 'succeeded',
    finished_at: '2024-09-16T21:05:00Z',
    last_success_at: '2024-09-16T21:05:00Z',
    consecutive_failures: 0,
    error_summary: null
  }
]

export const statusOk: StatusResponse = {
  server_time: FIXTURE_NOW,
  market_clock: { is_open: true, next_open: NEXT_OPEN, next_close: NEXT_CLOSE },
  jobs: okJobs,
  backfill: { listings_done: 503, listings_total: 503 },
  missing_keys: [],
  data_as_of: '2024-09-17T15:42:07Z',
  open_gaps: 0
}

export const statusDegraded: StatusResponse = {
  ...statusOk,
  server_time: '2024-09-17T20:32:00Z',
  market_clock: {
    is_open: false,
    next_open: NEXT_OPEN,
    next_close: '2024-09-18T20:00:00Z'
  },
  jobs: [
    {
      ...okJobs[0]!,
      status: 'partial',
      consecutive_failures: 1,
      error_summary: '12 of 503 symbols timed out'
    },
    okJobs[1]!
  ]
}

export const statusFailing: StatusResponse = {
  ...statusOk,
  jobs: [
    {
      job: 'quotes',
      status: 'failed',
      finished_at: '2024-09-17T15:41:50Z',
      last_success_at: '2024-09-17T13:58:14Z',
      consecutive_failures: 6,
      error_summary: 'Alpaca connection refused'
    },
    okJobs[1]!
  ],
  data_as_of: '2024-09-17T13:58:14Z'
}

export const statusMissingAlpaca: StatusResponse = {
  ...statusOk,
  market_clock: null,
  jobs: [
    {
      job: 'quotes',
      status: 'failed',
      finished_at: null,
      last_success_at: null,
      consecutive_failures: 1,
      error_summary: 'ALPACA_KEY_ID is not set'
    }
  ],
  missing_keys: ['ALPACA_KEY_ID', 'ALPACA_SECRET_KEY'],
  data_as_of: null
}

export const statusMissingAi: StatusResponse = {
  ...statusOk,
  missing_keys: ['ANTHROPIC_API_KEY']
}

export const statusBackfill: StatusResponse = {
  ...statusOk,
  backfill: { listings_done: 212, listings_total: 503 }
}

export const statusClosed: StatusResponse = {
  ...statusOk,
  server_time: CLOSED_NOW,
  market_clock: {
    is_open: false,
    next_open: '2024-09-17T13:30:00Z',
    next_close: NEXT_CLOSE
  },
  data_as_of: '2024-09-16T20:00:00Z'
}

export const statusFirstRun: StatusResponse = {
  ...statusClosed,
  jobs: [
    {
      job: 'quotes',
      status: 'failed',
      finished_at: '2024-09-17T13:10:00Z',
      last_success_at: null,
      consecutive_failures: 2,
      error_summary: 'No Listings loaded'
    }
  ],
  backfill: { listings_done: 0, listings_total: 0 },
  data_as_of: null
}

// /status `ai` block from #7 (feat/ai-chat); not yet in the generated types.
export const aiOk: AiStatus = { spend_usd: 1.24, limit_usd: 5, enabled: true }
export const aiSpent: AiStatus = {
  spend_usd: 5.0,
  limit_usd: 5,
  enabled: false
}
export const aiNoKey: AiStatus = { spend_usd: 0, limit_usd: 5, enabled: false }
