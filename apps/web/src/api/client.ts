import createClient from 'openapi-fetch'
import type { paths } from './schema'

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
