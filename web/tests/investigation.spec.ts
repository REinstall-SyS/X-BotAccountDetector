import { expect, test } from '@playwright/test'

test('create a watchlist and complete a fixture investigation', async ({ page }) => {
  const token = process.env.E2E_REVIEWER_TOKEN
  if (!token) throw new Error('Set E2E_REVIEWER_TOKEN for a fresh fixture workspace')
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const initial = await page.request.get('/api/metrics?source=fixture', { headers: { Authorization: 'Bearer ' + token } })
  expect(initial.ok()).toBeTruthy()
  const actions = (await initial.json()).actions as number
  await page.goto('/')
  await page.getByLabel('Reviewer token').fill(token)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()

  await page.getByRole('link', { name: 'Manage watchlists' }).click()
  const watchlist = 'Browser watch ' + Date.now()
  await page.getByLabel('Name', { exact: true }).fill(watchlist)
  await page.getByLabel('Keywords').fill('community')
  await page.getByRole('button', { name: 'Create watchlist' }).click()
  await expect(page.getByRole('status')).toHaveText('Watchlist created.')

  await page.getByText(watchlist, { exact: true }).click()
  await page.getByRole('button', { name: 'Replay fixture' }).click()
  await expect(page.getByText('Fixture replay queued for this watchlist.')).toBeVisible()
  await page.getByRole('link', { name: 'Overview', exact: true }).click()
  const fixture = page.getByRole('link', { name: watchlist, exact: true })
  await expect(fixture).toBeVisible({ timeout: 15_000 })
  await fixture.click()
  await expect(page.getByRole('heading', { name: 'Account network' })).toBeVisible()
  await expect(page.locator('.network canvas').first()).toBeVisible()
  await expect(page.getByText('2 separated matches')).toBeVisible()
  await page.getByLabel('Account pair').selectOption('1')
  await expect(page.getByText('2 separated matches')).toBeVisible()

  await page.getByLabel('Investigation note').fill('Fixture confirms two distinct synchronized rounds.')
  await page.getByRole('button', { name: 'Record outcome' }).click()
  await expect(page.getByText('Fixture confirms two distinct synchronized rounds.')).toBeVisible()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export evidence' }).click()
  expect((await downloaded).suggestedFilename()).toMatch(/^investigation-\d+\.json$/)

  await page.locator('.timeline a').first().click()
  await expect(page.getByRole('heading', { name: 'Observed behavior' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Related investigations' })).toBeVisible()
  await page.getByRole('link', { name: 'Model Lab' }).click()
  await expect(page.getByRole('heading', { name: 'Investigation evaluation' })).toBeVisible()
  await expect(page.getByText((actions + 1) + (actions === 0 ? ' action' : ' actions'), { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})
