import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export const api = createClient<paths>({ baseUrl: '/api' })

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function unwrap<T>(result: {
  data?: T
  error?: unknown
  response: Response
}): Promise<T> {
  if (!result.response.ok) {
    const body = result.error as { detail?: string } | undefined
    throw new ApiError(
      result.response.status,
      body?.detail ?? 'The request could not be completed.',
    )
  }
  if (result.data === undefined) {
    throw new ApiError(result.response.status, 'The server returned no data.')
  }
  return result.data
}

export async function fetchAccounts() {
  return unwrap(await api.GET('/v1/accounts'))
}

export async function createAccount(input: {
  name: string
  account_type: string
  base_currency: string
}) {
  return unwrap(await api.POST('/v1/accounts', { body: input }))
}

export async function updateAccount(
  id: string,
  input: {
    name?: string
    account_type?: string
    base_currency?: string
    active?: boolean
  },
) {
  return unwrap(
    await api.PATCH('/v1/accounts/{account_id}', {
      params: { path: { account_id: id } },
      body: input,
    }),
  )
}

export async function resolveSecurity(query: string) {
  return unwrap(
    await api.GET('/v1/securities/resolve', {
      params: { query: { q: query } },
    }),
  )
}

export async function fetchPositions(accountId: string) {
  return unwrap(
    await api.GET('/v1/accounts/{account_id}/positions', {
      params: { path: { account_id: accountId } },
    }),
  )
}

export async function fetchOwnedPortfolio(accountId: string, asOf?: string) {
  return unwrap(
    await api.GET('/v1/portfolio/owned/{account_id}', {
      params: {
        path: { account_id: accountId },
        query: asOf ? { as_of: asOf } : {},
      },
    }),
  )
}

export async function createIssuer(input: { display_name: string }) {
  return unwrap(await api.POST('/v1/issuers', { body: input }))
}

export async function fetchIssuers() {
  return unwrap(await api.GET('/v1/issuers'))
}

export async function fetchSecurities() {
  return unwrap(await api.GET('/v1/securities'))
}

export async function createSecurity(
  input: components['schemas']['SecurityCreate'],
) {
  return unwrap(await api.POST('/v1/securities', { body: input }))
}

export async function createManualQuote(
  input: components['schemas']['QuoteCreate'],
) {
  return unwrap(await api.POST('/v1/market-data/quotes', { body: input }))
}

export async function fetchImport(importId: string) {
  return unwrap(
    await api.GET('/v1/imports/{import_id}', {
      params: { path: { import_id: importId } },
    }),
  )
}

export async function previewPositionImport(input: {
  accountId: string
  effectiveDate: string
  expectedRevision: number
  sourceLabel: string
  mapping: Record<string, string>
  file: File
  replaceExisting?: boolean
}) {
  const response = await fetch('/api/v1/imports/positions/preview', {
    method: 'POST',
    headers: {
      'Content-Type': 'text/csv',
      'X-Account-Id': input.accountId,
      'X-Effective-Date': input.effectiveDate,
      'X-Expected-Account-Revision': String(input.expectedRevision),
      'X-Source-Label': input.sourceLabel,
      'X-Column-Mapping': JSON.stringify(input.mapping),
      'X-File-Name': input.file.name,
      'X-Replace-Existing': String(input.replaceExisting ?? false),
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: input.file,
  })
  const body = (await response.json()) as
    components['schemas']['ImportCreated'] | { detail?: string }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      'detail' in body
        ? (body.detail ?? 'CSV review could not be started.')
        : 'CSV review could not be started.',
    )
  }
  return body as components['schemas']['ImportCreated']
}

export async function previewBrokeragePdf(input: {
  accountId: string
  effectiveDate: string
  expectedRevision: number
  sourceLabel: string
  file: File
  replaceExisting?: boolean
}) {
  const response = await fetch('/api/v1/imports/documents/positions/preview', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/pdf',
      'X-Account-Id': input.accountId,
      'X-Effective-Date': input.effectiveDate,
      'X-Expected-Account-Revision': String(input.expectedRevision),
      'X-Source-Label': input.sourceLabel,
      'X-File-Name': input.file.name,
      'X-Replace-Existing': String(input.replaceExisting ?? false),
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: input.file,
  })
  const body = (await response.json()) as
    components['schemas']['DocumentImportCreated'] | { detail?: string }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      'detail' in body
        ? (body.detail ?? 'Statement review could not be started.')
        : 'Statement review could not be started.',
    )
  }
  return body as components['schemas']['DocumentImportCreated']
}

export async function previewTransactionImport(input: {
  accountId: string
  sourceLabel: string
  mapping: Record<string, string>
  file: File
}) {
  const response = await fetch('/api/v1/imports/transactions/preview', {
    method: 'POST',
    headers: {
      'Content-Type': 'text/csv',
      'X-Account-Id': input.accountId,
      'X-Source-Label': input.sourceLabel,
      'X-Column-Mapping': JSON.stringify(input.mapping),
      'X-File-Name': input.file.name,
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: input.file,
  })
  const body = (await response.json()) as
    components['schemas']['TransactionImportCreated'] | { detail?: string }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      'detail' in body
        ? (body.detail ?? 'Transaction review could not be started.')
        : 'Transaction review could not be started.',
    )
  }
  return body as components['schemas']['TransactionImportCreated']
}

export async function fetchTransactionImport(importId: string) {
  return unwrap(
    await api.GET('/v1/transaction-imports/{import_id}', {
      params: { path: { import_id: importId } },
    }),
  )
}

export async function correctTransactionRow(
  importId: string,
  rowId: string,
  input: components['schemas']['TransactionRowCorrection'],
) {
  return unwrap(
    await api.PATCH('/v1/transaction-imports/{import_id}/rows/{row_id}', {
      params: { path: { import_id: importId, row_id: rowId } },
      body: input,
    }),
  )
}

export async function publishTransactionImport(
  importId: string,
  expectedReviewRevision: number,
) {
  return unwrap(
    await api.POST('/v1/transaction-imports/{import_id}/publish', {
      params: { path: { import_id: importId } },
      body: {
        expected_review_revision: expectedReviewRevision,
        reason: 'Accepted in transaction review',
      },
    }),
  )
}

export async function cancelTransactionImport(
  importId: string,
  expectedReviewRevision: number,
) {
  return unwrap(
    await api.POST('/v1/transaction-imports/{import_id}/cancel', {
      params: { path: { import_id: importId } },
      body: {
        expected_review_revision: expectedReviewRevision,
        reason: 'Cancelled in transaction review',
      },
    }),
  )
}

export async function fetchTransactions(accountId: string) {
  return unwrap(
    await api.GET('/v1/transactions', {
      params: { query: { account_id: accountId, limit: 200 } },
    }),
  )
}

export async function createManualTransaction(
  input: components['schemas']['TransactionManualCreate'],
) {
  return unwrap(await api.POST('/v1/transactions/manual', { body: input }))
}

export async function updateTransaction(
  id: string,
  input: components['schemas']['TransactionPatch'],
) {
  return unwrap(
    await api.PATCH('/v1/transactions/{transaction_id}', {
      params: { path: { transaction_id: id } },
      body: input,
    }),
  )
}

export async function fetchTransactionSplits(transactionId: string) {
  return unwrap(
    await api.GET('/v1/transactions/{transaction_id}/splits', {
      params: { path: { transaction_id: transactionId } },
    }),
  )
}

export async function replaceTransactionSplits(
  transactionId: string,
  input: components['schemas']['TransactionSplitsReplace'],
) {
  return unwrap(
    await api.PUT('/v1/transactions/{transaction_id}/splits', {
      params: { path: { transaction_id: transactionId } },
      body: input,
    }),
  )
}

export async function fetchCategories() {
  return unwrap(await api.GET('/v1/categories'))
}

export async function createCategory(
  input: components['schemas']['SpendingCategoryCreate'],
) {
  return unwrap(await api.POST('/v1/categories', { body: input }))
}

export async function fetchCategoryRules() {
  return unwrap(await api.GET('/v1/category-rules'))
}

export async function createCategoryRule(
  input: components['schemas']['CategoryRuleCreate'],
) {
  return unwrap(await api.POST('/v1/category-rules', { body: input }))
}

export async function fetchTransferCandidates() {
  return unwrap(await api.GET('/v1/transfers/candidates'))
}

export async function confirmTransfer(
  firstTransactionId: string,
  secondTransactionId: string,
) {
  return unwrap(
    await api.POST('/v1/transfers', {
      body: {
        first_transaction_id: firstTransactionId,
        second_transaction_id: secondTransactionId,
        reason: 'Confirmed from transfer review',
      },
    }),
  )
}

export async function unlinkTransfer(transferId: string) {
  return unwrap(
    await api.POST('/v1/transfers/{transfer_id}/unlink', {
      params: {
        path: { transfer_id: transferId },
        header: { 'X-Reason': 'Unlinked from spending review' },
      },
    }),
  )
}

export async function correctImportRow(
  importId: string,
  rowId: string,
  input: components['schemas']['ImportRowCorrection'],
) {
  return unwrap(
    await api.PATCH('/v1/imports/{import_id}/rows/{row_id}', {
      params: { path: { import_id: importId, row_id: rowId } },
      body: input,
    }),
  )
}

export async function cancelImport(
  importId: string,
  expectedReviewRevision: number,
) {
  return unwrap(
    await api.POST('/v1/imports/{import_id}/cancel', {
      params: { path: { import_id: importId } },
      body: {
        expected_review_revision: expectedReviewRevision,
        reason: 'Cancelled in local review',
      },
    }),
  )
}

export async function publishImport(
  importId: string,
  expectedReviewRevision: number,
) {
  return unwrap(
    await api.POST('/v1/imports/{import_id}/publish', {
      params: { path: { import_id: importId } },
      body: {
        expected_review_revision: expectedReviewRevision,
        reason: 'Published after local review',
      },
    }),
  )
}

export async function replacePositions(
  accountId: string,
  input: {
    expected_revision: number | null
    effective_date: string
    positions: Array<{
      security_id: string
      quantity: string
      reported_price: string | null
      currency: string
    }>
  },
) {
  return unwrap(
    await api.PUT('/v1/accounts/{account_id}/positions', {
      params: { path: { account_id: accountId } },
      body: input,
    }),
  )
}

export async function previewFundImport(input: {
  fundId: string
  date: string
  format: string
  unit: string
  mapping: Record<string, string>
  file: File
}) {
  const response = await fetch(`/api/v1/funds/${input.fundId}/upload`, {
    method: 'POST',
    headers: {
      'X-Effective-Date': input.date,
      'X-Fund-Format': input.format,
      'X-Weight-Unit': input.unit,
      'X-Column-Mapping': JSON.stringify(input.mapping),
      'X-File-Name': input.file.name,
      'X-Source-Label': `User upload (${input.format})`,
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: input.file,
  })
  const body =
    (await response.json()) as components['schemas']['ImportCreated'] & {
      detail?: string
    }
  if (!response.ok)
    throw new ApiError(response.status, body.detail ?? 'Fund review failed')
  return body
}
export async function fetchFundSnapshots(fundId: string) {
  return unwrap(
    await api.GET('/v1/funds/{fund_id}/snapshots', {
      params: { path: { fund_id: fundId } },
    }),
  )
}
export async function publishFundImport(importId: string, revision: number) {
  return unwrap(
    await api.POST('/v1/fund-imports/{import_id}/publish', {
      params: { path: { import_id: importId } },
      body: {
        expected_review_revision: revision,
        reason: 'Accepted after fund review',
      },
    }),
  )
}
export async function correctFundRow(
  importId: string,
  rowId: string,
  data: components['schemas']['FundCorrection'],
) {
  return unwrap(
    await api.PATCH('/v1/fund-imports/{import_id}/rows/{row_id}', {
      params: { path: { import_id: importId, row_id: rowId } },
      body: data,
    }),
  )
}

export async function createReport(
  input: components['schemas']['ReportCreate'],
) {
  return unwrap(await api.POST('/v1/portfolio/reports', { body: input }))
}
export async function fetchReport(id: string) {
  return unwrap(
    await api.GET('/v1/portfolio/reports/{identifier}', {
      params: { path: { identifier: id } },
    }),
  )
}
export async function fetchReportRows(
  id: string,
  view: 'owned' | 'security' | 'issuer',
  offset: number,
  q: string,
  source: string,
  sort: 'label' | 'value',
  descending: boolean,
) {
  return unwrap(
    await api.GET('/v1/portfolio/reports/{identifier}/rows', {
      params: {
        path: { identifier: id },
        query: { view, offset, limit: 50, q, source, sort, descending },
      },
    }),
  )
}
export async function fetchBreakdown(
  id: string,
  target: string,
  level: 'security' | 'issuer' | 'category',
  offset: number,
) {
  return unwrap(
    await api.GET('/v1/portfolio/reports/{identifier}/breakdown/{target}', {
      params: {
        path: { identifier: id, target },
        query: { level, offset, limit: 50 },
      },
    }),
  )
}
