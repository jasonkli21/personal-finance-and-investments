import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAccountBalance,
  fetchAccounts,
  fetchFinanceSummary,
} from './api/client'
import type { components } from './api/schema'

type Summary = components['schemas']['FinanceSummaryRead']

function localDate(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function firstOfCurrentMonth(): string {
  return localDate().slice(0, 7) + '-01'
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

export default function FinanceWorkspace() {
  const client = useQueryClient()
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const accounts = (accountsQuery.data ?? []).filter(
    (account) => account.active,
  )
  const [month, setMonth] = useState(firstOfCurrentMonth)
  const [asOf, setAsOf] = useState(localDate)
  const [accountId, setAccountId] = useState('')
  const [balanceKind, setBalanceKind] = useState<'asset' | 'liability'>('asset')
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [source, setSource] = useState('Manual statement balance')
  const [quality, setQuality] = useState<'reported' | 'estimated' | 'stale'>(
    'reported',
  )
  const [balanceKey, setBalanceKey] = useState(() => crypto.randomUUID())
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!accountId && accounts.length) {
      setAccountId(accounts[0].id)
      setCurrency(accounts[0].base_currency)
    }
  }, [accountId, accounts])

  const summaryQuery = useQuery({
    queryKey: ['finance-summary', month, asOf],
    queryFn: () => fetchFinanceSummary({ month, asOf }),
    enabled: Boolean(month && asOf),
  })
  const summary = summaryQuery.data as Summary | undefined
  const selectedAccount = accounts.find((account) => account.id === accountId)

  const addBalance = useMutation({
    mutationFn: () => {
      if (!accountId || !asOf || !amount || !source.trim()) {
        throw new Error('Complete account, date, amount and source.')
      }
      return createAccountBalance({
        account_id: accountId,
        as_of: asOf,
        balance_kind: balanceKind,
        amount,
        currency,
        source: source.trim(),
        quality_status: quality,
        idempotency_key: balanceKey,
      })
    },
    onSuccess: async () => {
      setAmount('')
      setBalanceKey(crypto.randomUUID())
      setNotice('Dated balance saved. Prior observations remain in history.')
      await client.invalidateQueries({ queryKey: ['finance-summary'] })
    },
  })

  function updateBalance<T>(setter: (value: T) => void, value: T) {
    setter(value)
    setBalanceKey(crypto.randomUUID())
    setNotice('')
  }

  return (
    <section className="mx-auto flex max-w-6xl flex-col gap-6 px-5 pb-12 sm:px-8">
      <header className="border-b border-slate-200 pb-5">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-violet-700">
          Stage 2 • Finance summary
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
          Spending and net worth
        </h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Monthly cash flow uses posted transactions. Net worth uses dated
          balances or owned positions and keeps currencies separate.
        </p>
      </header>

      {notice && (
        <p
          role="status"
          className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900"
        >
          {notice}
        </p>
      )}
      {summaryQuery.error && (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900"
        >
          {summaryQuery.error.message}
        </p>
      )}
      {addBalance.error && (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900"
        >
          {addBalance.error.message}
        </p>
      )}

      <Section title="Monthly cash flow">
        <label className="flex flex-wrap items-center gap-2 text-sm">
          Month
          <input
            type="month"
            className="rounded-lg border p-2"
            value={month.slice(0, 7)}
            onChange={(event) =>
              setMonth(event.target.value ? `${event.target.value}-01` : '')
            }
          />
        </label>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <caption className="sr-only">Monthly totals by currency</caption>
            <thead className="bg-slate-50">
              <tr>
                <th className="p-2">Currency</th>
                <th className="p-2">Income</th>
                <th className="p-2">Net spending</th>
                <th className="p-2">Net cash flow</th>
                <th className="p-2">Rows</th>
              </tr>
            </thead>
            <tbody>
              {summary?.currency_totals.map((total) => (
                <tr className="border-t" key={total.currency}>
                  <th className="p-2 font-medium">{total.currency}</th>
                  <td className="p-2 font-mono">{total.income}</td>
                  <td className="p-2 font-mono">{total.net_spending}</td>
                  <td className="p-2 font-mono">{total.net_cash_flow}</td>
                  <td className="p-2">{total.transaction_count}</td>
                </tr>
              ))}
              {summary && summary.currency_totals.length === 0 && (
                <tr>
                  <td className="p-3 text-slate-600" colSpan={5}>
                    No published transactions for this month.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-500">{summary?.transaction_policy}</p>
        <h3 className="font-medium text-slate-900">Net spending by category</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[460px] text-left text-sm">
            <caption className="sr-only">Category spending by currency</caption>
            <thead className="bg-slate-50">
              <tr>
                <th className="p-2">Category</th>
                <th className="p-2">Currency</th>
                <th className="p-2">Net spending</th>
              </tr>
            </thead>
            <tbody>
              {summary?.category_totals.map((total, index) => (
                <tr
                  className="border-t"
                  key={`${total.currency}-${total.category_id}-${index}`}
                >
                  <th className="p-2 font-medium">{total.category_name}</th>
                  <td className="p-2">{total.currency}</td>
                  <td className="p-2 font-mono">{total.net_spending}</td>
                </tr>
              ))}
              {summary && summary.category_totals.length === 0 && (
                <tr>
                  <td className="p-3 text-slate-600" colSpan={3}>
                    No classified spending or refunds for this month.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Dated balance observation">
        <form
          className="grid gap-3 md:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault()
            addBalance.mutate()
          }}
        >
          <label className="grid gap-1 text-sm">
            Account
            <select
              className="rounded-lg border p-2"
              value={accountId}
              onChange={(event) => {
                const nextId = event.target.value
                setAccountId(nextId)
                const nextAccount = accounts.find(
                  (account) => account.id === nextId,
                )
                if (nextAccount) setCurrency(nextAccount.base_currency)
                setBalanceKey(crypto.randomUUID())
              }}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            As of
            <input
              type="date"
              className="rounded-lg border p-2"
              value={asOf}
              onChange={(event) => updateBalance(setAsOf, event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Kind
            <select
              className="rounded-lg border p-2"
              value={balanceKind}
              onChange={(event) =>
                updateBalance(
                  setBalanceKind,
                  event.target.value as typeof balanceKind,
                )
              }
            >
              <option value="asset">Asset</option>
              <option value="liability">Liability</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Reported amount
            <input
              className="rounded-lg border p-2"
              inputMode="decimal"
              value={amount}
              onChange={(event) => updateBalance(setAmount, event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Currency
            <input
              className="rounded-lg border p-2 uppercase"
              maxLength={3}
              value={currency}
              onChange={(event) =>
                updateBalance(setCurrency, event.target.value.toUpperCase())
              }
            />
          </label>
          <label className="grid gap-1 text-sm">
            Source
            <input
              className="rounded-lg border p-2"
              maxLength={100}
              value={source}
              onChange={(event) => updateBalance(setSource, event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Quality
            <select
              className="rounded-lg border p-2"
              value={quality}
              onChange={(event) =>
                updateBalance(setQuality, event.target.value as typeof quality)
              }
            >
              <option value="reported">Reported</option>
              <option value="estimated">Estimated</option>
              <option value="stale">Stale</option>
            </select>
          </label>
          <button
            className="self-end rounded-lg bg-violet-700 px-4 py-2 font-medium text-white disabled:opacity-50"
            type="submit"
            disabled={!selectedAccount || addBalance.isPending}
          >
            Save dated balance
          </button>
        </form>
        <p className="text-xs text-slate-500">
          Liabilities are stored as positive reported amounts and deducted from
          net worth. A balance for an account with a positions snapshot stays in
          history and is shown as excluded from the total.
        </p>
      </Section>

      <Section title="Net worth by currency">
        <p className="text-sm text-slate-600">As of {summary?.as_of ?? asOf}</p>
        {summary && summary.net_worth.length > 0 ? (
          <ul className="grid gap-3 sm:grid-cols-2">
            {summary.net_worth.map((total) => (
              <li className="rounded-lg bg-slate-50 p-4" key={total.currency}>
                <p className="text-sm text-slate-600">{total.currency}</p>
                <p className="mt-1 font-mono text-xl font-semibold">
                  {total.known_amount}
                </p>
                <p className="text-xs text-slate-600">
                  {total.completeness} known values
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-600">
            No dated balance or valued position observations are available yet.
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-left text-sm">
            <caption className="sr-only">
              Included and excluded account balance sources
            </caption>
            <thead className="bg-slate-50">
              <tr>
                <th className="p-2">Account / holding</th>
                <th className="p-2">As of</th>
                <th className="p-2">Amount</th>
                <th className="p-2">Source</th>
                <th className="p-2">Quality</th>
                <th className="p-2">Treatment</th>
              </tr>
            </thead>
            <tbody>
              {summary?.balances.map((line, index) => (
                <tr className="border-t" key={`${line.account_id}-${index}`}>
                  <th className="p-2 font-medium">
                    {line.account_name}
                    {line.detail ? ` • ${line.detail}` : ''}
                  </th>
                  <td className="p-2">{line.as_of ?? 'Unavailable'}</td>
                  <td className="p-2 font-mono">
                    {line.amount === null
                      ? 'Unavailable'
                      : `${line.currency} ${line.amount}`}
                  </td>
                  <td className="p-2">{line.source ?? '—'}</td>
                  <td className="p-2">{line.quality_status}</td>
                  <td className="p-2">
                    {line.included ? `Included • ${line.status}` : line.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {summary && summary.coverage_gaps.length > 0 && (
          <div>
            <h3 className="font-medium text-slate-900">Coverage gaps</h3>
            <ul className="list-disc pl-5 text-sm text-amber-800">
              {summary.coverage_gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </div>
        )}
        <ul className="list-disc pl-5 text-xs text-slate-500">
          {summary?.exclusions.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </Section>
    </section>
  )
}
