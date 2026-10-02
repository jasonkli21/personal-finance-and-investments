import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmTransfer,
  correctTransactionRow,
  createCategory,
  createCategoryRule,
  createManualTransaction,
  fetchAccounts,
  fetchCategories,
  fetchTransactionImport,
  fetchTransactionSplits,
  fetchTransactions,
  fetchTransferCandidates,
  previewTransactionImport,
  publishTransactionImport,
  replaceTransactionSplits,
  unlinkTransfer,
  updateTransaction,
} from './api/client'
import type { components } from './api/schema'

type Row = components['schemas']['TransactionRowRead']
type Transaction = components['schemas']['TransactionRead']
type Category = components['schemas']['SpendingCategoryRead']
type Review = components['schemas']['TransactionImportReviewRead']
type Candidate = components['schemas']['TransferCandidateRead']
type Field =
  | 'posted_date'
  | 'transaction_date'
  | 'amount'
  | 'currency'
  | 'description'
  | 'provider_id'
  | 'raw_type'
const FIELDS: Field[] = [
  'posted_date',
  'transaction_date',
  'amount',
  'currency',
  'description',
  'provider_id',
  'raw_type',
]

function readHeaders(text: string): string[] {
  const first = text.replace(/^\uFEFF/, '').split(/\r?\n/, 1)[0] ?? ''
  const values: string[] = []
  let value = ''
  let quoted = false
  for (let i = 0; i < first.length; i += 1) {
    const ch = first[i]
    if (ch === '"') {
      if (quoted && first[i + 1] === '"') {
        value += '"'
        i += 1
      } else quoted = !quoted
    } else if (ch === ',' && !quoted) {
      values.push(value.trim())
      value = ''
    } else value += ch
  }
  values.push(value.trim())
  if (
    quoted ||
    values.some((item) => !item) ||
    new Set(values).size !== values.length
  ) {
    throw new Error('CSV headers must be valid, non-empty and unique.')
  }
  return values
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      {children}
    </section>
  )
}

export default function SpendingWorkspace() {
  const client = useQueryClient()
  const manualDraftKey = useRef(crypto.randomUUID())
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const accounts = (accountsQuery.data ?? []).filter((row) => row.active)
  const [accountId, setAccountId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<Field, string>>({
    posted_date: '',
    transaction_date: '',
    amount: '',
    currency: '',
    description: '',
    provider_id: '',
    raw_type: '',
  })
  const [importId, setImportId] = useState('')
  const [sourceLabel, setSourceLabel] = useState('Bank CSV')
  const [categoryName, setCategoryName] = useState('')
  const [merchant, setMerchant] = useState('')
  const [ruleCategory, setRuleCategory] = useState('')
  const [manualDate, setManualDate] = useState('')
  const [manualAmount, setManualAmount] = useState('')
  const [manualDescription, setManualDescription] = useState('')
  const [manualClass, setManualClass] = useState<
    'unclassified' | 'income' | 'expense' | 'refund' | 'fee'
  >('unclassified')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const categoryQuery = useQuery({
    queryKey: ['spending-categories'],
    queryFn: fetchCategories,
  })
  const categories = categoryQuery.data ?? []
  const reviewQuery = useQuery({
    queryKey: ['transaction-import-review', importId],
    queryFn: () => fetchTransactionImport(importId),
    enabled: Boolean(importId),
  })
  const review = reviewQuery.data as Review | undefined
  const transactionsQuery = useQuery({
    queryKey: ['transactions', accountId],
    queryFn: () => fetchTransactions(accountId),
    enabled: Boolean(accountId),
  })
  const transactions = transactionsQuery.data ?? []
  const transfersQuery = useQuery({
    queryKey: ['transfer-candidates'],
    queryFn: fetchTransferCandidates,
  })
  const candidates = transfersQuery.data ?? []

  const preview = useMutation({
    mutationFn: () => {
      if (!file || !accountId)
        throw new Error('Choose an account and a CSV file.')
      if (!mapping.posted_date || !mapping.amount || !mapping.description)
        throw new Error('Map posted date, signed amount and description.')
      const selected = Object.fromEntries(
        Object.entries(mapping).filter((entry) => Boolean(entry[1])),
      )
      return previewTransactionImport({
        accountId,
        sourceLabel,
        mapping: selected,
        file,
      })
    },
    onSuccess: async (result) => {
      setImportId(result.id)
      setMessage(
        result.duplicate
          ? 'This source already has a review.'
          : 'CSV staged for review.',
      )
      setError('')
      await client.invalidateQueries({
        queryKey: ['transaction-import-review', result.id],
      })
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : 'CSV review failed.'),
  })
  const correction = useMutation({
    mutationFn: ({
      row,
      input,
    }: {
      row: Row
      input: components['schemas']['TransactionRowCorrection']
    }) => correctTransactionRow(importId, row.id, input),
    onSuccess: async () => {
      setMessage('Row saved. Recheck the updated review revision.')
      setError('')
      await client.invalidateQueries({
        queryKey: ['transaction-import-review', importId],
      })
    },
    onError: (cause) =>
      setError(
        cause instanceof Error ? cause.message : 'Row correction failed.',
      ),
  })
  const publish = useMutation({
    mutationFn: () => {
      if (!review) throw new Error('Load a review first.')
      return publishTransactionImport(importId, review.review_revision)
    },
    onSuccess: async () => {
      setMessage('Transactions published.')
      await Promise.all([
        client.invalidateQueries({
          queryKey: ['transaction-import-review', importId],
        }),
        client.invalidateQueries({ queryKey: ['transactions', accountId] }),
        client.invalidateQueries({ queryKey: ['finance-summary'] }),
      ])
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : 'Publish failed.'),
  })
  const addCategory = useMutation({
    mutationFn: () => {
      const name = categoryName.trim()
      const slug = name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
      if (!slug) throw new Error('Enter a category with letters or numbers.')
      return createCategory({ display_name: name, slug })
    },
    onSuccess: async (category) => {
      setCategoryName('')
      setRuleCategory(category.id)
      setMessage('Category created.')
      setError('')
      await client.invalidateQueries({ queryKey: ['spending-categories'] })
    },
    onError: (cause) =>
      setError(
        cause instanceof Error ? cause.message : 'Category creation failed.',
      ),
  })
  const addRule = useMutation({
    mutationFn: () => {
      if (!ruleCategory) throw new Error('Choose a category.')
      return createCategoryRule({
        merchant,
        category_id: ruleCategory,
        priority: 100,
      })
    },
    onSuccess: () => {
      setMerchant('')
      setMessage('Exact merchant rule saved for future imports.')
      setError('')
    },
    onError: (cause) =>
      setError(
        cause instanceof Error ? cause.message : 'Rule creation failed.',
      ),
  })
  const addManual = useMutation({
    mutationFn: () => {
      if (
        !accountId ||
        !manualDate ||
        !manualAmount ||
        !manualDescription.trim()
      )
        throw new Error(
          'Complete account, date, signed amount and description.',
        )
      return createManualTransaction({
        account_id: accountId,
        posted_date: manualDate,
        transaction_date: null,
        amount: manualAmount,
        currency:
          accounts.find((account) => account.id === accountId)?.base_currency ??
          'USD',
        description: manualDescription.trim(),
        classification: manualClass,
        category_id: null,
        idempotency_key: manualDraftKey.current,
      })
    },
    onSuccess: async () => {
      setManualAmount('')
      setManualDescription('')
      manualDraftKey.current = crypto.randomUUID()
      setMessage('Manual transaction recorded.')
      setError('')
      await Promise.all([
        client.invalidateQueries({ queryKey: ['transactions', accountId] }),
        client.invalidateQueries({ queryKey: ['finance-summary'] }),
      ])
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : 'Manual entry failed.'),
  })
  const updateTx = useMutation({
    mutationFn: ({
      row,
      categoryId,
      classification,
    }: {
      row: Transaction
      categoryId: string | null
      classification: components['schemas']['TransactionPatch']['classification']
    }) =>
      updateTransaction(row.id, {
        expected_revision: row.revision,
        reason: 'Updated from spending workspace',
        category_id: categoryId,
        classification,
      }),
    onSuccess: async () => {
      setMessage('Classification saved.')
      await Promise.all([
        client.invalidateQueries({ queryKey: ['transactions', accountId] }),
        client.invalidateQueries({ queryKey: ['finance-summary'] }),
      ])
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : 'Update failed.'),
  })
  const linkTransfer = useMutation({
    mutationFn: (pair: Candidate) =>
      confirmTransfer(pair.first_transaction.id, pair.second_transaction.id),
    onSuccess: async () => {
      setMessage(
        'Transfer confirmed. Original signed amounts remain unchanged.',
      )
      await Promise.all([
        client.invalidateQueries({ queryKey: ['transfer-candidates'] }),
        client.invalidateQueries({ queryKey: ['transactions', accountId] }),
        client.invalidateQueries({ queryKey: ['finance-summary'] }),
      ])
    },
    onError: (cause) =>
      setError(
        cause instanceof Error ? cause.message : 'Transfer link failed.',
      ),
  })
  const unlink = useMutation({
    mutationFn: unlinkTransfer,
    onSuccess: async () => {
      setMessage('Transfer unlinked. Both signed transactions remain intact.')
      await Promise.all([
        client.invalidateQueries({ queryKey: ['transactions', accountId] }),
        client.invalidateQueries({ queryKey: ['finance-summary'] }),
        client.invalidateQueries({ queryKey: ['transfer-candidates'] }),
      ])
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : 'Unlink failed.'),
  })
  const unresolved =
    review?.rows.filter(
      (row) => !['ready', 'duplicate', 'update'].includes(row.status),
    ).length ?? 0

  function correctRow(
    row: Row,
    action?: 'keep' | 'duplicate' | 'update',
    target?: string,
  ) {
    if (!review) return
    correction.mutate({
      row,
      input: {
        expected_review_revision: review.review_revision,
        reason: action
          ? 'Identity reviewed: ' + action
          : 'Corrected transaction row',
        posted_date: row.posted_date ?? undefined,
        transaction_date: row.transaction_date ?? undefined,
        amount: row.amount ?? undefined,
        currency: row.currency ?? undefined,
        description: row.description || row.raw_description || undefined,
        provider_transaction_id: row.provider_transaction_id,
        raw_type: row.raw_type ?? undefined,
        identity_resolution: action,
        duplicate_of_transaction_id: target,
      },
    })
  }

  function selectFile(next: File | null) {
    setFile(next)
    setImportId('')
    if (!next) return
    void next.text().then((text) => {
      try {
        const parsed = readHeaders(text)
        setHeaders(parsed)
        const aliases: Record<Field, string[]> = {
          posted_date: ['posted date', 'post date', 'date'],
          transaction_date: ['transaction date', 'purchase date'],
          amount: ['amount', 'transaction amount', 'debit', 'credit'],
          currency: ['currency', 'currency code'],
          description: ['description', 'name', 'merchant', 'details'],
          provider_id: ['transaction id', 'provider id', 'fitid', 'reference'],
          raw_type: ['type', 'transaction type'],
        }
        setMapping(
          Object.fromEntries(
            FIELDS.map((field) => [
              field,
              parsed.find((name) =>
                aliases[field].includes(
                  name.toLowerCase().replace(/[_-]+/g, ' ').trim(),
                ),
              ) ?? '',
            ]),
          ) as Record<Field, string>,
        )
        setError('')
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Invalid CSV header.')
      }
    })
  }

  return (
    <section className="mx-auto flex max-w-6xl flex-col gap-6 px-5 pb-12 sm:px-8">
      <header className="border-b border-slate-200 pb-6">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700">
          Stage 2 • Spending
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
          Transactions and cash flow
        </h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Import a bank or card CSV, review every row, then publish. Debits stay
          negative and credits stay positive. Snapshot imports never create
          trades or tax lots.
        </p>
      </header>
      {message && (
        <p
          role="status"
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
        >
          {message}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
        >
          {error}
        </p>
      )}

      <Section title="Bank or card CSV review">
        <div className="grid gap-4 md:grid-cols-3">
          <label className="grid gap-1 text-sm text-slate-700">
            Account
            <select
              className="rounded-lg border p-2"
              value={accountId}
              onChange={(event) => {
                manualDraftKey.current = crypto.randomUUID()
                setAccountId(event.target.value)
              }}
            >
              <option value="">Choose account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm text-slate-700">
            Source label
            <input
              className="rounded-lg border p-2"
              value={sourceLabel}
              onChange={(event) => setSourceLabel(event.target.value)}
              maxLength={100}
            />
          </label>
          <label className="grid gap-1 text-sm text-slate-700">
            CSV file
            <input
              className="rounded-lg border p-2"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        {headers.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {FIELDS.map((field) => (
              <label key={field} className="grid gap-1 text-sm text-slate-700">
                {field.replaceAll('_', ' ')}
                {['posted_date', 'amount', 'description'].includes(field)
                  ? ' *'
                  : ''}
                <select
                  className="rounded-lg border p-2"
                  value={mapping[field]}
                  onChange={(event) =>
                    setMapping((current) => ({
                      ...current,
                      [field]: event.target.value,
                    }))
                  }
                >
                  <option value="">Not provided</option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        )}
        <button
          type="button"
          className="rounded-lg bg-blue-700 px-4 py-2 font-medium text-white disabled:opacity-50"
          disabled={!accountId || !file || preview.isPending}
          onClick={() => preview.mutate()}
        >
          {preview.isPending ? 'Preparing…' : 'Preview CSV'}
        </button>
        {review && (
          <div className="space-y-3 border-t pt-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-slate-600">
                {review.row_count} rows • revision {review.review_revision} •{' '}
                {review.status}
                {unresolved
                  ? ' • ' + unresolved + ' need review'
                  : ' • resolved'}
              </p>
              <button
                type="button"
                className="rounded-lg bg-emerald-700 px-3 py-2 text-sm text-white disabled:opacity-50"
                disabled={
                  review.status !== 'review' ||
                  unresolved > 0 ||
                  publish.isPending
                }
                onClick={() => publish.mutate()}
              >
                Publish accepted rows
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="p-2">Row</th>
                    <th className="p-2">Posted</th>
                    <th className="p-2">Amount</th>
                    <th className="p-2">Currency</th>
                    <th className="p-2">Description</th>
                    <th className="p-2">Provider ID</th>
                    <th className="p-2">Review</th>
                  </tr>
                </thead>
                <tbody>
                  {review.rows.map((row) => (
                    <ReviewRow
                      key={row.id}
                      row={row}
                      canEdit={review.status === 'review'}
                      onSave={correctRow}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-500">
              Exact-file reimports return the prior attempt.
              Same-date/amount/description rows without native IDs remain
              ambiguous; decide whether to keep the recurring purchase or mark
              it duplicate.
            </p>
          </div>
        )}
      </Section>

      <Section title="Manual transaction">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="grid gap-1 text-sm">
            Date
            <input
              type="date"
              className="rounded-lg border p-2"
              value={manualDate}
              onChange={(event) => {
                manualDraftKey.current = crypto.randomUUID()
                setManualDate(event.target.value)
              }}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Signed amount
            <input
              className="rounded-lg border p-2"
              inputMode="decimal"
              placeholder="-32.50"
              value={manualAmount}
              onChange={(event) => {
                manualDraftKey.current = crypto.randomUUID()
                setManualAmount(event.target.value)
              }}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Type
            <select
              className="rounded-lg border p-2"
              value={manualClass}
              onChange={(event) => {
                manualDraftKey.current = crypto.randomUUID()
                setManualClass(event.target.value as typeof manualClass)
              }}
            >
              <option value="unclassified">Unclassified</option>
              <option value="expense">Expense</option>
              <option value="income">Income</option>
              <option value="refund">Refund</option>
              <option value="fee">Fee</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Description
            <input
              className="rounded-lg border p-2"
              value={manualDescription}
              onChange={(event) => {
                manualDraftKey.current = crypto.randomUUID()
                setManualDescription(event.target.value)
              }}
            />
          </label>
        </div>
        <button
          type="button"
          className="rounded-lg border px-4 py-2"
          disabled={!accountId || addManual.isPending}
          onClick={() => addManual.mutate()}
        >
          Add to selected account
        </button>
      </Section>

      <Section title="Categories and exact merchant rules">
        <div className="grid gap-4 md:grid-cols-2">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              addCategory.mutate()
            }}
          >
            <input
              className="min-w-0 flex-1 rounded-lg border p-2"
              aria-label="New category"
              placeholder="Category name"
              value={categoryName}
              onChange={(event) => setCategoryName(event.target.value)}
            />
            <button className="rounded-lg border px-3" type="submit">
              Add category
            </button>
          </form>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              addRule.mutate()
            }}
          >
            <input
              className="min-w-0 flex-1 rounded-lg border p-2"
              aria-label="Merchant rule"
              placeholder="Exact merchant"
              value={merchant}
              onChange={(event) => setMerchant(event.target.value)}
            />
            <select
              className="rounded-lg border p-2"
              value={ruleCategory}
              onChange={(event) => setRuleCategory(event.target.value)}
            >
              <option value="">Category</option>
              {categories.map((category: Category) => (
                <option key={category.id} value={category.id}>
                  {category.display_name}
                </option>
              ))}
            </select>
            <button className="rounded-lg border px-3" type="submit">
              Save rule
            </button>
          </form>
        </div>
        <p className="text-xs text-slate-500">
          Rules apply to future imports. Existing manual category changes remain
          user overrides.
        </p>
      </Section>

      <Section title="Published transactions">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="p-2">Posted</th>
                <th className="p-2">Description</th>
                <th className="p-2">Signed amount</th>
                <th className="p-2">Type</th>
                <th className="p-2">Category</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {transactions.map((row: Transaction) => (
                <TransactionRow
                  key={row.id}
                  row={row}
                  categories={categories}
                  busy={updateTx.isPending}
                  onUnlink={(id) => unlink.mutate(id)}
                  onSave={(categoryId, classification) =>
                    updateTx.mutate({ row, categoryId, classification })
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
        {accountId && transactions.length === 0 && (
          <p className="text-sm text-slate-600">
            No published transactions for this account.
          </p>
        )}
      </Section>

      <Section title="Possible account transfers">
        {candidates.length === 0 ? (
          <p className="text-sm text-slate-600">
            No exact opposite-amount candidates across accounts. Links require
            confirmation and do not alter source amounts.
          </p>
        ) : (
          candidates.map((pair: Candidate) => (
            <div
              key={pair.first_transaction.id + ':' + pair.second_transaction.id}
              className="flex flex-wrap items-center justify-between gap-3 border-b py-3 text-sm"
            >
              <p>
                {pair.first_transaction.description} (
                {pair.first_transaction.amount}{' '}
                {pair.first_transaction.currency}) ↔{' '}
                {pair.second_transaction.description} (
                {pair.second_transaction.amount}{' '}
                {pair.second_transaction.currency}) • {pair.date_gap_days}{' '}
                day(s)
              </p>
              <button
                className="rounded-lg border px-3 py-2"
                type="button"
                disabled={linkTransfer.isPending}
                onClick={() => linkTransfer.mutate(pair)}
              >
                Confirm transfer
              </button>
            </div>
          ))
        )}
      </Section>
    </section>
  )
}

function ReviewRow({
  row,
  canEdit,
  onSave,
}: {
  row: Row
  canEdit: boolean
  onSave: (
    row: Row,
    action?: 'keep' | 'duplicate' | 'update',
    target?: string,
  ) => void
}) {
  const [posted, setPosted] = useState(row.posted_date ?? '')
  const [amount, setAmount] = useState(row.amount ?? '')
  const [currency, setCurrency] = useState(row.currency ?? '')
  const [description, setDescription] = useState(row.description)
  const [providerId, setProviderId] = useState(
    row.provider_transaction_id ?? '',
  )
  const candidates = row.duplicate_candidates ?? []
  const nativeConflict = Boolean(row.diagnostics.native_id_conflict)
  const resolved = ['ready', 'duplicate', 'update'].includes(row.status)
  const draft = {
    ...row,
    posted_date: posted || null,
    amount: amount || null,
    currency: currency || null,
    description,
    provider_transaction_id: providerId || null,
  }
  return (
    <tr className="border-t align-top">
      <td className="p-2">{row.row_number}</td>
      <td className="p-2">
        <input
          type="date"
          className="w-36 rounded border p-1"
          disabled={!canEdit || row.status === 'duplicate'}
          value={posted}
          onChange={(event) => setPosted(event.target.value)}
        />
      </td>
      <td className="p-2">
        <input
          inputMode="decimal"
          className="w-28 rounded border p-1"
          disabled={!canEdit || row.status === 'duplicate'}
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
      </td>
      <td className="p-2">
        <input
          className="w-16 rounded border p-1"
          maxLength={3}
          disabled={!canEdit || row.status === 'duplicate'}
          value={currency}
          onChange={(event) => setCurrency(event.target.value.toUpperCase())}
        />
      </td>
      <td className="p-2">
        <input
          className="w-64 rounded border p-1"
          disabled={!canEdit || row.status === 'duplicate'}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <p
          className="max-w-64 truncate text-xs text-slate-500"
          title={row.raw_description}
        >
          Source: {row.raw_description}
        </p>
      </td>
      <td className="p-2">
        <input
          className="w-40 rounded border p-1 font-mono text-xs"
          aria-label={`Provider transaction ID for row ${row.row_number}`}
          disabled={!canEdit || row.status === 'duplicate'}
          value={providerId}
          onChange={(event) => setProviderId(event.target.value)}
        />
        {Boolean(row.diagnostics.repeated_provider_id_in_file) && (
          <p className="mt-1 text-xs text-amber-800">
            Repeated in this file; clear the ID if these are separate events.
          </p>
        )}
      </td>
      <td className="space-y-1 p-2">
        <span
          className={
            resolved
              ? 'rounded bg-emerald-50 px-2 py-1 text-xs text-emerald-800'
              : 'rounded bg-amber-50 px-2 py-1 text-xs text-amber-800'
          }
        >
          {row.status}
        </span>
        {Object.keys(row.diagnostics).length > 0 && (
          <p className="text-xs text-amber-800">
            {Object.keys(row.diagnostics).join(', ')}
          </p>
        )}
        {canEdit && row.status !== 'duplicate' && (
          <div className="flex flex-wrap gap-1">
            <button
              className="rounded border px-2 py-1 text-xs"
              type="button"
              onClick={() => onSave(draft)}
            >
              Save correction
            </button>
            {candidates.map((id) => (
              <span key={id} className="flex gap-1">
                <button
                  className="rounded border px-2 py-1 text-xs"
                  type="button"
                  onClick={() => onSave(draft, 'duplicate', id)}
                >
                  Duplicate
                </button>
                {nativeConflict && (
                  <button
                    className="rounded border px-2 py-1 text-xs"
                    type="button"
                    onClick={() => onSave(draft, 'update', id)}
                  >
                    Update existing
                  </button>
                )}
              </span>
            ))}
            {(row.status === 'ambiguous' ||
              Boolean(row.diagnostics.repeated_provider_id_in_file)) && (
              <button
                className="rounded border px-2 py-1 text-xs"
                type="button"
                onClick={() => onSave(draft, 'keep')}
              >
                Keep separate
              </button>
            )}
          </div>
        )}
      </td>
    </tr>
  )
}

function TransactionRow({
  row,
  categories,
  busy,
  onUnlink,
  onSave,
}: {
  row: Transaction
  categories: Category[]
  busy: boolean
  onUnlink: (transferId: string) => void
  onSave: (
    categoryId: string | null,
    classification: components['schemas']['TransactionPatch']['classification'],
  ) => void
}) {
  const client = useQueryClient()
  const [editingSplits, setEditingSplits] = useState(false)
  const [splitAmounts, setSplitAmounts] = useState(['', ''])
  const [splitCategories, setSplitCategories] = useState(['', ''])
  const [splitLoaded, setSplitLoaded] = useState(false)
  const splitQuery = useQuery({
    queryKey: ['transaction-splits', row.id],
    queryFn: () => fetchTransactionSplits(row.id),
    enabled: editingSplits,
  })
  const saveSplits = useMutation({
    mutationFn: () => {
      const amounts = splitAmounts.map((value) => value.trim())
      if (amounts.some((value) => !value)) {
        throw new Error('Enter an amount for each split.')
      }
      return replaceTransactionSplits(row.id, {
        expected_revision: row.revision,
        reason: 'Updated from spending workspace',
        splits: amounts.map((amount, index) => ({
          amount,
          category_id: splitCategories[index] || null,
        })),
      })
    },
    onSuccess: async () => {
      setEditingSplits(false)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['transactions'] }),
        client.invalidateQueries({ queryKey: ['finance-summary'] }),
      ])
      await client.invalidateQueries({
        queryKey: ['transaction-splits', row.id],
      })
    },
  })
  useEffect(() => {
    if (editingSplits && splitQuery.data && !splitLoaded) {
      setSplitAmounts(
        splitQuery.data.length
          ? splitQuery.data.map((split) => split.amount)
          : ['', ''],
      )
      setSplitCategories(
        splitQuery.data.length
          ? splitQuery.data.map((split) => split.category_id ?? '')
          : ['', ''],
      )
      setSplitLoaded(true)
    }
  }, [editingSplits, splitLoaded, splitQuery.data])
  const [categoryId, setCategoryId] = useState(row.category_id ?? '')
  const [classification, setClassification] = useState(
    row.classification as components['schemas']['TransactionPatch']['classification'],
  )
  return (
    <>
      <tr className="border-t">
        <td className="whitespace-nowrap p-2">{row.posted_date}</td>
        <td className="max-w-64 truncate p-2" title={row.raw_description}>
          {row.description}
        </td>
        <td className="whitespace-nowrap p-2 font-mono">
          {row.amount} {row.currency}
        </td>
        <td className="p-2">
          <select
            className="rounded border p-1"
            value={classification ?? 'unclassified'}
            disabled={busy}
            onChange={(event) =>
              setClassification(event.target.value as typeof classification)
            }
          >
            <option value="unclassified">Unclassified</option>
            <option value="income">Income</option>
            <option value="expense">Expense</option>
            <option value="refund">Refund</option>
            <option value="transfer">Transfer</option>
            <option value="card_payment">Card payment</option>
            <option value="fee">Fee</option>
            <option value="other">Other</option>
          </select>
        </td>
        <td className="p-2">
          <select
            className="rounded border p-1"
            value={categoryId}
            disabled={busy}
            onChange={(event) => setCategoryId(event.target.value)}
          >
            <option value="">Uncategorized</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.display_name}
              </option>
            ))}
          </select>
        </td>
        <td className="p-2">
          <button
            className="rounded border px-2 py-1 text-xs"
            type="button"
            disabled={busy}
            onClick={() => onSave(categoryId || null, classification)}
          >
            Save
          </button>
          <button
            className="ml-1 rounded border px-2 py-1 text-xs"
            type="button"
            onClick={() => {
              setSplitLoaded(false)
              setEditingSplits((value) => !value)
            }}
          >
            {row.split_count ? 'Edit split' : 'Split'}
          </button>
          {row.transfer_match_id && (
            <button
              className="ml-1 rounded border px-2 py-1 text-xs"
              type="button"
              onClick={() => onUnlink(row.transfer_match_id!)}
            >
              Unlink transfer
            </button>
          )}
        </td>
      </tr>
      {editingSplits && (
        <tr className="border-t bg-slate-50">
          <td className="p-3" colSpan={6}>
            <div className="space-y-2">
              <p className="text-xs text-slate-600">
                Split amounts must add exactly to {row.amount} {row.currency}.
              </p>
              {splitAmounts.map((amount, index) => (
                <div key={index} className="flex flex-wrap gap-2">
                  <input
                    className="w-32 rounded border p-1"
                    aria-label={`Split ${index + 1} signed amount`}
                    inputMode="decimal"
                    value={amount}
                    onChange={(event) =>
                      setSplitAmounts((current) =>
                        current.map((value, item) =>
                          item === index ? event.target.value : value,
                        ),
                      )
                    }
                  />
                  <select
                    className="rounded border p-1"
                    aria-label={`Split ${index + 1} category`}
                    value={splitCategories[index] ?? ''}
                    onChange={(event) =>
                      setSplitCategories((current) =>
                        current.map((value, item) =>
                          item === index ? event.target.value : value,
                        ),
                      )
                    }
                  >
                    <option value="">Uncategorized</option>
                    {categories.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.display_name}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
              <button
                className="rounded border px-2 py-1 text-xs"
                type="button"
                disabled={saveSplits.isPending}
                onClick={() => saveSplits.mutate()}
              >
                Save exact split
              </button>
              {saveSplits.error && (
                <p role="alert" className="text-xs text-rose-800">
                  {saveSplits.error.message}
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
