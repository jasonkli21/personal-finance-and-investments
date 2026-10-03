import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

test('offline reviewed positions → ETF compositions → frozen NVDA drill-down and CSV', async ({
  page,
}) => {
  // Fail any accidental external provider/browser request.
  await page.route('**/*', (route) =>
    new URL(route.request().url()).hostname === '127.0.0.1'
      ? route.continue()
      : route.abort(),
  )
  await page.goto('/')
  for (const [ticker, type] of [
    ['NVDA', 'equity'],
    ['OTHER', 'equity'],
    ['FA', 'etf'],
    ['FB', 'etf'],
  ]) {
    const form = page.locator('form').filter({ hasText: 'Add security' })
    await form
      .getByRole('combobox', { name: 'Type', exact: true })
      .selectOption(type)
    await form.getByLabel('Ticker (optional)').fill(ticker)
    await form.getByLabel('Name', { exact: true }).fill(`Synthetic ${ticker}`)
    await form
      .getByRole('button', { name: 'Add to local catalog', exact: true })
      .click()
    await expect(form.getByLabel('Name', { exact: true })).toHaveValue('')
  }
  for (const name of ['Brokerage', 'Retirement']) {
    await page
      .locator('form')
      .filter({
        has: page.getByRole('heading', { name: 'Add an account', exact: true }),
      })
      .getByLabel('Name', { exact: true })
      .fill(name)
    await page
      .getByRole('button', { name: 'Create account', exact: true })
      .click()
    await expect(
      page
        .locator('form')
        .filter({
          has: page.getByRole('heading', {
            name: 'Add an account',
            exact: true,
          }),
        })
        .getByLabel('Name', { exact: true }),
    ).toHaveValue('')
  }
  // Use only UI imports: snapshot review must precede publication.
  for (const [name, csv] of [
    [
      'Brokerage',
      'ticker,quantity,price,currency\nNVDA,300,100,USD\nFA,500,100,USD\nOTHER,1000,100,USD\n',
    ],
    ['Retirement', 'ticker,quantity,price,currency\nFB,200,100,USD\n'],
  ]) {
    await page
      .getByRole('combobox', { name: 'Select account', exact: true })
      .selectOption({ label: name })
    await page.getByLabel('Position and manual price as of').fill('2026-10-01')
    await page
      .getByLabel('CSV or supported text PDF', { exact: true })
      .setInputFiles({
        name: `${name}.csv`,
        mimeType: 'text/csv',
        buffer: Buffer.from(csv),
      })
    await page
      .getByRole('combobox', { name: 'Ticker / identifier', exact: true })
      .selectOption('ticker')
    await page
      .getByRole('combobox', { name: 'Quantity or cash balance', exact: true })
      .selectOption('quantity')
    await page
      .getByRole('combobox', { name: 'Price (optional)', exact: true })
      .selectOption('price')
    await page
      .getByRole('combobox', { name: 'Currency (optional)', exact: true })
      .selectOption('currency')
    await page
      .getByRole('region', {
        name: 'Reviewed CSV or brokerage statement import',
        exact: true,
      })
      .getByRole('button', { name: 'Stage for review', exact: true })
      .click()
    await expect(
      page.getByRole('button', {
        name: 'Publish reviewed snapshot',
        exact: true,
      }),
    ).toBeEnabled()
    await page
      .getByRole('button', { name: 'Publish reviewed snapshot', exact: true })
      .click()
    await expect(
      page.getByText(
        'Reviewed position snapshot published atomically to the account.',
      ),
    ).toBeVisible()
  }
  for (const [fund, weight] of [
    ['FA', '8'],
    ['FB', '6'],
  ]) {
    await page
      .getByLabel('Fund composition security')
      .selectOption({ label: fund })
    await page.getByLabel('Holdings as of').fill('2026-10-01')
    await page.getByLabel('Holdings file').setInputFiles({
      name: `${fund}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(
        `ticker,weight,type\nNVDA,${weight},equity\nOTHER,${100 - Number(weight)},equity\n`,
      ),
    })
    await page
      .getByRole('button', { name: 'Preview fund holdings', exact: true })
      .click()
    await page
      .getByRole('button', { name: 'Accept fund composition', exact: true })
      .click()
    await expect(
      page.getByRole('button', {
        name: 'Accept fund composition',
        exact: true,
      }),
    ).toBeDisabled()
  }
  const report = page.getByRole('region', {
    name: 'Portfolio reports',
    exact: true,
  })
  await report.getByRole('checkbox', { name: 'Brokerage', exact: true }).check()
  await report
    .getByRole('checkbox', { name: 'Retirement', exact: true })
    .check()
  await report.getByRole('button', { name: 'Create / refresh report' }).click()
  await expect(
    report.getByText('Total portfolio NAV: USD 200,000.00', { exact: true }),
  ).toBeVisible()
  await report.getByLabel('Search report rows').fill('NVDA')
  const row = report
    .getByRole('row')
    .filter({ has: page.getByRole('button', { name: 'NVDA', exact: true }) })
  await expect(row).toContainText('35,200.00')
  await expect(row).toContainText('17.60')
  await row.getByRole('button', { name: 'NVDA', exact: true }).click()
  const detail = report.getByRole('region', { name: 'Contribution breakdown' })
  await expect(detail).toContainText('30,000.00')
  await expect(detail).toContainText('4,000.00')
  await expect(detail).toContainText('1,200.00')
  const downloaded = page.waitForEvent('download')
  await report.getByRole('link', { name: 'Export frozen CSV' }).click()
  const file = await downloaded
  const csv = await readFile((await file.path())!, 'utf8')
  expect(csv).toContain('35200')
  expect(csv).toContain('17.6')
  const url = page.url()
  await page.reload()
  await expect(
    report.getByText('Total portfolio NAV: USD 200,000.00', { exact: true }),
  ).toBeVisible()
  expect(page.url()).toBe(url)
  await report
    .getByRole('button', { name: 'Owned positions', exact: true })
    .click()
  await expect(report.getByRole('table')).toContainText('50,000.00')
})
