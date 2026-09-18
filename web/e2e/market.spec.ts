import { expect, test } from '@playwright/test'

import { mockApi } from './mock-api'

test.describe('Market', () => {
  test.skip(!process.env.RUN_E2E, 'Set RUN_E2E=1 to run the E2E suite')

  test.beforeEach(async ({ page }) => {
    await mockApi(page)
    await page.goto('/')
  })

  test('lists the Constituent List with status in the header strip', async ({
    page
  }) => {
    const table = page.getByRole('region', { name: 'Constituent list' })
    await expect(table.getByRole('row', { name: /AAPL/ })).toBeVisible()
    await expect(page.getByText('Open · closes 4:00 PM ET')).toBeVisible()
    await expect(page.getByText(/Ingest ok/)).toBeVisible()
  })

  test('filters by search, keeps it in the URL, and opens a Company', async ({
    page
  }) => {
    await page.getByRole('searchbox', { name: 'Search Listings' }).fill('nvid')
    await expect(page.getByText('60 Listings · 1 shown')).toBeVisible()
    await expect(page).toHaveURL(/q=nvid/)
    await page.getByRole('row', { name: /NVDA/ }).click()
    await expect(page).toHaveURL(/\/companies\/0001045810/)
  })

  test('opens the command palette with the keyboard', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    const palette = page.getByRole('dialog', { name: 'Jump to Company' })
    await expect(palette).toBeVisible()
    await palette.getByRole('combobox').fill('micro')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/companies\/0000789019/)
  })
})
