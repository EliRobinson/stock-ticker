import { expect, test } from '@playwright/test'

import { mockApi } from './mock-api'

test.describe('Ask', () => {
  test.skip(!process.env.RUN_E2E, 'Set RUN_E2E=1 to run the E2E suite')

  test.beforeEach(async ({ page }) => {
    await mockApi(page)
    await page.goto('/')
    await expect(
      page
        .getByRole('region', { name: 'Constituent list' })
        .getByRole('row', { name: /AAPL/ })
    ).toBeVisible()
  })

  test('opens beside Market and answers a suggested question', async ({
    page
  }) => {
    await page.getByRole('banner').getByRole('button', { name: 'Ask' }).click()
    const panel = page.getByRole('region', { name: 'Ask' })
    await expect(
      panel.getByText('Questions run against the local database.', {
        exact: false
      })
    ).toBeVisible()

    await panel.getByRole('button', { name: /COVID/ }).click()
    await expect(
      panel.getByText('NCLH fell furthest, down 85.70%.')
    ).toBeVisible()
    await expect(
      page.getByRole('region', { name: 'Constituent list' })
    ).toBeVisible()
  })

  test('sends a typed question with Enter', async ({ page }) => {
    await page.keyboard.press('Alt+KeyA')
    const input = page.getByRole('textbox', { name: 'Ask a question' })
    await input.fill('Worst drawdowns in 2020?')
    await input.press('Enter')
    await expect(page.getByText('Worst drawdowns in 2020?')).toBeVisible()
    await expect(
      page.getByText('NCLH fell furthest, down 85.70%.')
    ).toBeVisible()
  })
})
