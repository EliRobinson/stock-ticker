import type { Page } from '@playwright/test'

import { marketOpen } from '../src/fixtures/market'
import { notesResponse } from '../src/fixtures/notes'
import { statusOk } from '../src/fixtures/status'

// The browser calls the API directly (AGENTS.md), so the network boundary is
// where these specs mock it: no Python API or database needed.
export async function mockApi(page: Page) {
  await page.route('**/api/v1/market', (route) =>
    route.fulfill({ json: marketOpen })
  )
  await page.route('**/api/v1/status', (route) =>
    route.fulfill({ json: statusOk })
  )
  await page.route('**/api/v1/notes**', (route) =>
    route.fulfill({ json: notesResponse })
  )
  await page.route('**/api/v1/chat', (route) => {
    const parts = [
      { type: 'start', messageId: 'm1' },
      { type: 'start-step' },
      { type: 'text-start', id: 't1' },
      {
        type: 'text-delta',
        id: 't1',
        delta: 'NCLH fell furthest, down 85.70%.'
      },
      { type: 'text-end', id: 't1' },
      { type: 'finish-step' },
      { type: 'finish' }
    ]
    return route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream',
        'x-vercel-ai-ui-message-stream': 'v1'
      },
      body:
        parts.map((p) => `data: ${JSON.stringify(p)}\n\n`).join('') +
        'data: [DONE]\n\n'
    })
  })
}
