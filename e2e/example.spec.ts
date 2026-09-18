import { test, expect } from '@playwright/test'

test.describe('Home page', () => {
  test('loads and shows heading', async ({ page }) => {
    await page.goto('/')
    await expect(
      page.getByRole('heading', { name: 'Stock Ticker' })
    ).toBeVisible()
  })
})
