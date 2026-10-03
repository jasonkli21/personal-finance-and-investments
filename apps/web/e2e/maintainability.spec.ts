import { expect, test, type Page } from '@playwright/test'

test.use({ timezoneId: 'America/Los_Angeles' })

async function restrictToLocal(page: Page) {
  await page.route('**/*', (route) =>
    new URL(route.request().url()).hostname === '127.0.0.1'
      ? route.continue()
      : route.abort(),
  )
}

test('transaction drafts keep their starting revision after another row is corrected', async ({
  page,
  request,
}) => {
  await restrictToLocal(page)
  const accountResponse = await request.post('/api/v1/accounts', {
    data: {
      name: 'Synthetic review concurrency',
      account_type: 'bank',
      base_currency: 'USD',
    },
  })
  expect(accountResponse.ok()).toBeTruthy()
  const account = (await accountResponse.json()) as { id: string }
  await page.goto('/')
  const review = page.getByRole('region', {
    name: 'Bank or card CSV review',
    exact: true,
  })
  await review
    .getByRole('combobox', { name: 'Account', exact: true })
    .selectOption(account.id)
  await review.getByLabel('CSV file', { exact: true }).setInputFiles({
    name: 'synthetic-draft.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'posted_date,amount,currency,description\n2026-10-01,-10,USD,Synthetic coffee\n2026-10-02,-20,USD,Synthetic groceries\n',
    ),
  })
  await expect(
    review.getByRole('combobox', { name: 'posted date *', exact: true }),
  ).toHaveValue('posted_date')
  const createdResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/imports/transactions/preview') &&
      response.request().method() === 'POST',
  )
  await review.getByRole('button', { name: 'Preview CSV', exact: true }).click()
  const created = (await (await createdResponse).json()) as { id: string }
  const first = review
    .getByRole('row')
    .filter({ hasText: 'Source: Synthetic coffee' })
  const second = review
    .getByRole('row')
    .filter({ hasText: 'Source: Synthetic groceries' })
  await first.locator('input').nth(3).fill('Unsaved synthetic edit')
  await expect(
    review.getByRole('button', { name: 'Publish accepted rows' }),
  ).toBeDisabled()
  await second.getByRole('button', { name: 'Save correction' }).click()
  await expect(review.getByText(/revision 2/)).toBeVisible()
  await expect(first.locator('input').nth(3)).toHaveValue(
    'Unsaved synthetic edit',
  )
  const staleResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/transaction-imports/${created.id}/rows/`) &&
      response.request().method() === 'PATCH',
  )
  await first.getByRole('button', { name: 'Save correction' }).click()
  expect((await staleResponse).status()).toBe(409)
  const canonical = await request.get(
    `/api/v1/transactions?account_id=${account.id}`,
  )
  expect(await canonical.json()).toEqual([])
  await review
    .getByRole('button', { name: 'Discard row drafts and reload review' })
    .click()
  await expect(first.locator('input').nth(3)).toHaveValue('Synthetic coffee')
  await expect(
    review.getByRole('button', { name: 'Publish accepted rows' }),
  ).toBeEnabled()
  await request.patch(`/api/v1/accounts/${account.id}`, {
    data: { active: false },
  })
})

test('sign-out fences a session refresh that was already in flight', async ({
  page,
}) => {
  await restrictToLocal(page)
  let delayRefresh = false
  let finishRefresh: (() => void) | undefined
  let refreshStarted: (() => void) | undefined
  const started = new Promise<void>((resolve) => {
    refreshStarted = resolve
  })
  await page.route('**/api/v1/auth/session', async (route) => {
    if (delayRefresh) {
      refreshStarted?.()
      await new Promise<void>((resolve) => {
        finishRefresh = resolve
      })
    }
    await route.fulfill({ json: { authenticated: true, local_mode: false } })
  })
  await page.route('**/api/v1/auth/logout', (route) =>
    route.fulfill({ status: 204 }),
  )
  await page.goto('/')
  await expect(
    page.getByRole('button', { name: 'Sign out', exact: true }),
  ).toBeVisible()
  delayRefresh = true
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await started
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Sign in', exact: true }),
  ).toBeVisible()
  finishRefresh?.()
  await expect(
    page.getByRole('button', { name: 'Sign out', exact: true }),
  ).toHaveCount(0)
})

test('published transactions page beyond the first 200 rows', async ({
  page,
  request,
}) => {
  await restrictToLocal(page)
  const accountResponse = await request.post('/api/v1/accounts', {
    data: {
      name: 'Synthetic paginated transactions',
      account_type: 'bank',
      base_currency: 'USD',
    },
  })
  expect(accountResponse.ok()).toBeTruthy()
  const account = (await accountResponse.json()) as { id: string }
  const rows = Array.from(
    { length: 201 },
    (_, index) => `2026-10-01,-1,USD,Synthetic page transaction ${index + 1}`,
  )
  const previewResponse = await request.post(
    '/api/v1/imports/transactions/preview',
    {
      headers: {
        'Content-Type': 'text/csv',
        'X-Account-Id': account.id,
        'X-Source-Label': 'Synthetic pagination fixture',
        'X-Column-Mapping': JSON.stringify({
          posted_date: 'posted_date',
          amount: 'amount',
          currency: 'currency',
          description: 'description',
        }),
        'X-File-Name': 'synthetic-pages.csv',
        'Idempotency-Key': 'synthetic-pagination-import',
      },
      data: Buffer.from(
        `posted_date,amount,currency,description\n${rows.join('\n')}\n`,
      ),
    },
  )
  expect(previewResponse.ok()).toBeTruthy()
  const created = (await previewResponse.json()) as { id: string }
  const reviewResponse = await request.get(
    `/api/v1/transaction-imports/${created.id}`,
  )
  const reviewState = (await reviewResponse.json()) as {
    review_revision: number
  }
  const published = await request.post(
    `/api/v1/transaction-imports/${created.id}/publish`,
    {
      data: {
        expected_review_revision: reviewState.review_revision,
        reason: 'Synthetic pagination fixture',
      },
    },
  )
  expect(published.ok()).toBeTruthy()
  await page.goto('/')
  await page
    .getByRole('region', { name: 'Bank or card CSV review', exact: true })
    .getByRole('combobox', { name: 'Account', exact: true })
    .selectOption(account.id)
  const transactions = page.getByRole('region', {
    name: 'Published transactions',
    exact: true,
  })
  await expect(transactions.locator('tbody tr')).toHaveCount(200)
  const nextPage = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/transactions?') &&
      new URL(response.url()).searchParams.get('offset') === '200',
  )
  await transactions.getByRole('button', { name: 'Next transactions' }).click()
  const secondPage = await nextPage
  expect(secondPage.ok()).toBeTruthy()
  expect(new URL(secondPage.url()).searchParams.get('limit')).toBe('201')
  await expect(transactions.locator('tbody tr')).toHaveCount(1)
  await expect(
    transactions.getByText('Rows 201–201', { exact: true }),
  ).toBeVisible()
  await expect(
    transactions.getByRole('button', { name: 'Next transactions' }),
  ).toBeDisabled()
  await transactions
    .getByRole('button', { name: 'Previous transactions' })
    .click()
  await expect(transactions.locator('tbody tr')).toHaveCount(200)
})

test('changing research issuer clears draft source references and notes', async ({
  page,
  request,
}) => {
  await restrictToLocal(page)
  const firstResponse = await request.post('/api/v1/issuers', {
    data: { display_name: 'Synthetic first research issuer' },
  })
  const secondResponse = await request.post('/api/v1/issuers', {
    data: { display_name: 'Synthetic second research issuer' },
  })
  expect(firstResponse.ok()).toBeTruthy()
  expect(secondResponse.ok()).toBeTruthy()
  const firstIssuer = (await firstResponse.json()) as { id: string }
  const secondIssuer = (await secondResponse.json()) as { id: string }
  const documentResponse = await request.post('/api/v1/research/documents', {
    data: {
      issuer_id: firstIssuer.id,
      cik: '123456',
      accession_number: '0000123456-26-000001',
      form_type: '10-K',
      title: 'Synthetic filing reference only',
      source_url:
        'https://www.sec.gov/Archives/edgar/data/123456/synthetic.htm',
    },
  })
  expect(documentResponse.ok()).toBeTruthy()
  const document = (await documentResponse.json()) as { id: string }
  await page.goto('/')
  const selector = page.getByRole('combobox', {
    name: 'Company in your issuer catalog',
  })
  await selector.selectOption(firstIssuer.id)
  const reference = page.getByRole('combobox', {
    name: 'Filing reference',
    exact: true,
  })
  await reference.selectOption(document.id)
  await page
    .getByRole('textbox', { name: 'Concept', exact: true })
    .fill('SyntheticRevenue')
  await page
    .getByRole('textbox', { name: 'Add a thesis note revision' })
    .fill('Unsaved note about the first synthetic issuer')
  await selector.selectOption(secondIssuer.id)
  await expect(reference).toHaveValue('')
  await expect(
    page.getByRole('textbox', { name: 'Concept', exact: true }),
  ).toHaveValue('')
  await expect(
    page.getByRole('textbox', { name: 'Add a thesis note revision' }),
  ).toHaveValue('')
})

test('tax-lot drafts survive another row correction and reject stale saves', async ({
  page,
  request,
}) => {
  await restrictToLocal(page)
  const accountResponse = await request.post('/api/v1/accounts', {
    data: {
      name: 'Synthetic tax-lot review',
      account_type: 'taxable',
      base_currency: 'USD',
    },
  })
  expect(accountResponse.ok()).toBeTruthy()
  const account = (await accountResponse.json()) as { id: string }
  const securityResponse = await request.post('/api/v1/securities', {
    data: {
      security_type: 'equity',
      display_ticker: 'TAXREV',
      name: 'Synthetic tax-lot review security',
      currency: 'USD',
    },
  })
  expect(securityResponse.ok()).toBeTruthy()
  await page.goto('/')
  const upload = page
    .getByRole('heading', { name: 'Stage a supplied lot CSV', exact: true })
    .locator('..')
  await upload
    .getByRole('combobox', { name: 'Account', exact: true })
    .selectOption(account.id)
  await upload.getByLabel('CSV file', { exact: true }).setInputFiles({
    name: 'synthetic-lot-drafts.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'ticker,source_lot_id,acquired_at,remaining_quantity,remaining_basis,basis_currency\nTAXREV,synthetic-lot-one,2025-01-01,1,10,USD\nTAXREV,synthetic-lot-two,2025-01-02,1,20,USD\n',
    ),
  })
  await upload
    .getByRole('button', { name: 'Stage for review', exact: true })
    .click()
  const first = page.locator('article').filter({
    has: page.getByRole('heading', { name: 'Row 1 · TAXREV', exact: true }),
  })
  const second = page.locator('article').filter({
    has: page.getByRole('heading', { name: 'Row 2 · TAXREV', exact: true }),
  })
  await first
    .getByRole('textbox', { name: 'Remaining basis', exact: true })
    .fill('15')
  await expect(
    page.getByRole('button', { name: 'Publish reviewed lots', exact: true }),
  ).toBeDisabled()
  await second
    .getByRole('textbox', { name: 'Remaining basis', exact: true })
    .fill('21')
  await second
    .getByRole('button', { name: 'Save reviewed correction', exact: true })
    .click()
  await expect(page.getByText(/2 rows · revision 2/i)).toBeVisible()
  await expect(
    first.getByRole('textbox', { name: 'Remaining basis', exact: true }),
  ).toHaveValue('15')
  const staleResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/tax-lot-imports/') &&
      response.request().method() === 'PATCH',
  )
  await first
    .getByRole('button', { name: 'Save reviewed correction', exact: true })
    .click()
  expect((await staleResponse).status()).toBe(409)
  await page
    .getByRole('button', {
      name: 'Discard lot drafts and reload review',
      exact: true,
    })
    .click()
  await expect(
    first.getByRole('textbox', { name: 'Remaining basis', exact: true }),
  ).toHaveValue(/^10(?:\.0+)?$/)
})

test('position review publication stays tied to its captured account', async ({
  page,
  request,
}) => {
  await restrictToLocal(page)
  const accounts: string[] = []
  for (const name of [
    'Synthetic captured account',
    'Synthetic other account',
  ]) {
    const response = await request.post('/api/v1/accounts', {
      data: { name, account_type: 'taxable', base_currency: 'USD' },
    })
    expect(response.ok()).toBeTruthy()
    accounts.push(((await response.json()) as { id: string }).id)
  }
  const securityResponse = await request.post('/api/v1/securities', {
    data: {
      security_type: 'equity',
      display_ticker: 'ACCTREV',
      name: 'Synthetic account review security',
      currency: 'USD',
    },
  })
  expect(securityResponse.ok()).toBeTruthy()
  await page.goto('/')
  const selectAccount = page.getByRole('combobox', {
    name: 'Select account',
    exact: true,
  })
  await selectAccount.selectOption(accounts[0])
  await page.getByLabel('Position and manual price as of').fill('2026-10-01')
  const review = page.getByRole('region', {
    name: 'Reviewed CSV or brokerage statement import',
    exact: true,
  })
  await review
    .getByLabel('CSV or supported text PDF', { exact: true })
    .setInputFiles({
      name: 'synthetic-account-review.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('ticker,quantity,price\nACCTREV,1,10\n'),
    })
  await review
    .getByRole('combobox', { name: 'Ticker / identifier', exact: true })
    .selectOption('ticker')
  await review
    .getByRole('combobox', { name: 'Quantity or cash balance', exact: true })
    .selectOption('quantity')
  await review
    .getByRole('combobox', { name: 'Price (optional)', exact: true })
    .selectOption('price')
  await review
    .getByRole('button', { name: 'Stage for review', exact: true })
    .click()
  await expect(
    review.getByRole('button', {
      name: 'Publish reviewed snapshot',
      exact: true,
    }),
  ).toBeEnabled()
  await selectAccount.selectOption(accounts[1])
  await expect(
    review.getByRole('button', {
      name: 'Publish reviewed snapshot',
      exact: true,
    }),
  ).toBeDisabled()
  await expect(
    review.getByText(
      'This review belongs to another account. Select its captured account before publishing.',
    ),
  ).toBeVisible()
  await selectAccount.selectOption(accounts[0])
  await review
    .getByRole('button', { name: 'Publish reviewed snapshot', exact: true })
    .click()
  await expect(
    page.getByText(
      'Reviewed position snapshot published atomically to the account.',
    ),
  ).toBeVisible()
  const originalPositions = await request.get(
    `/api/v1/accounts/${accounts[0]}/positions`,
  )
  const otherPositions = await request.get(
    `/api/v1/accounts/${accounts[1]}/positions`,
  )
  expect(
    ((await originalPositions.json()) as { current_revision: number })
      .current_revision,
  ).toBe(1)
  expect(
    ((await otherPositions.json()) as { current_revision: number })
      .current_revision,
  ).toBe(0)
})
