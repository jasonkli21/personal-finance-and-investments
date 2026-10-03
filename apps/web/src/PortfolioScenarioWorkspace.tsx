import { moneyDisplay as displayMoney } from './decimal-display'
import { localDate } from './local-date'
import { useState, type FormEvent } from 'react'
import { useMutation, useQueries, useQuery } from '@tanstack/react-query'
import {
  fetchAccounts,
  fetchPositions,
  fetchSecurities,
  simulatePortfolioScenario,
} from './api/client'
import type { components } from './api/schema'

type ScenarioRequest = components['schemas']['PortfolioScenarioRequest']
type ScenarioResult = components['schemas']['PortfolioScenarioRead']
type TradeDraft = {
  rowId: string
  accountId: string
  securityId: string
  side: 'buy' | 'sell'
  quantity: string
  price: string
  fee: string
}
type CashDraft = {
  rowId: string
  accountId: string
  amount: string
  label: string
}
type Category =
  | 'direct'
  | 'indirect'
  | 'cash'
  | 'opaque_fund'
  | 'nested_fund'
  | 'missing_weight'
  | 'unknown_other'

const CATEGORIES: { key: Category; label: string }[] = [
  { key: 'direct', label: 'Direct securities' },
  { key: 'indirect', label: 'ETF look-through' },
  { key: 'cash', label: 'Cash' },
  { key: 'opaque_fund', label: 'Opaque funds' },
  { key: 'nested_fund', label: 'Nested funds' },
  { key: 'missing_weight', label: 'Missing fund weights' },
  { key: 'unknown_other', label: 'Unknown / other' },
]

function displayPercent(value: string | null | undefined): string {
  return value === null || value === undefined ? 'Unavailable' : `${value}%`
}

function displayPoints(value: string | null | undefined): string {
  return value === null || value === undefined ? 'Unavailable' : `${value} pp`
}

function labelForCategory(category: string): string {
  return CATEGORIES.find((item) => item.key === category)?.label ?? category
}

function emptyTrade(accountId: string): TradeDraft {
  return {
    rowId: crypto.randomUUID(),
    accountId,
    securityId: '',
    side: 'buy',
    quantity: '',
    price: '',
    fee: '0',
  }
}

function emptyCash(accountId: string): CashDraft {
  return {
    rowId: crypto.randomUUID(),
    accountId,
    amount: '',
    label: '',
  }
}

function SnapshotSummary({
  title,
  snapshot,
}: {
  title: string
  snapshot: ScenarioResult['before']
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h4 className="font-semibold text-slate-900">{title}</h4>
      <p className="mt-1 text-2xl font-semibold text-slate-950">
        {displayMoney(snapshot.included_valued_nav)}
      </p>
      <p className="text-xs text-slate-500">
        {snapshot.nav_status === 'complete'
          ? 'Valued NAV complete'
          : 'Valued NAV incomplete'}
        {' · '}
        {snapshot.reconciled
          ? 'Exposure decomposition reconciled'
          : 'Exposure decomposition unavailable'}
        {snapshot.total_portfolio_nav
          ? ` · reported total ${displayMoney(snapshot.total_portfolio_nav)}`
          : ''}
      </p>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-slate-500">Direct assets</dt>
          <dd className="font-medium">
            {displayMoney(snapshot.direct_assets)}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Indirect look-through</dt>
          <dd className="font-medium">
            {displayMoney(snapshot.indirect_lookthrough)}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Residual</dt>
          <dd className="font-medium">{displayMoney(snapshot.residual)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Opaque / unknown</dt>
          <dd className="font-medium">
            {displayMoney(snapshot.opaque_and_unknown_value)}
          </dd>
        </div>
      </dl>
      <div className="mt-4 border-t border-slate-100 pt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Exposure categories
        </p>
        <ul className="space-y-1 text-sm">
          {Object.entries(snapshot.categories).map(([category, value]) => (
            <li className="flex justify-between gap-4" key={category}>
              <span className="text-slate-600">
                {labelForCategory(category)}
              </span>
              <span className="font-medium">{displayMoney(value)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-4 grid gap-4 border-t border-slate-100 pt-3 md:grid-cols-2">
        {[
          { title: 'Security exposure', rows: snapshot.security_rows },
          { title: 'Issuer exposure', rows: snapshot.issuer_rows },
        ].map(({ title: sectionTitle, rows }) => (
          <div key={sectionTitle}>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {sectionTitle}
            </p>
            {rows.length === 0 ? (
              <p className="text-xs text-slate-500">No mapped exposure.</p>
            ) : (
              <ul className="space-y-1 text-xs">
                {rows.slice(0, 8).map((row) => (
                  <li
                    className="flex justify-between gap-3"
                    key={row.id}
                    title={`Direct ${displayMoney(row.direct)} · indirect ${displayMoney(row.indirect)}`}
                  >
                    <span className="truncate text-slate-600">{row.label}</span>
                    <span className="shrink-0 font-medium">
                      {displayMoney(row.total)}
                      {row.percentage ? ` · ${row.percentage}%` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function PortfolioScenarioResult({ result }: { result: ScenarioResult }) {
  const baselineQueries = useQueries({
    queries: result.account_ids.map((accountId) => ({
      queryKey: ['positions', accountId],
      queryFn: () => fetchPositions(accountId),
    })),
  })
  const comparesWithCurrentHead =
    new Date(result.as_of).toDateString() === new Date().toDateString()
  const changedAccounts = result.account_ids.filter((accountId, index) => {
    const query = baselineQueries[index]
    return (
      comparesWithCurrentHead &&
      query?.data !== undefined &&
      query.data.current_revision !==
        result.account_position_revisions[accountId]
    )
  })

  return (
    <section className="space-y-5" aria-label="Portfolio scenario results">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">
            Frozen scenario result
          </h3>
          <p className="text-sm text-slate-600">
            As of {new Date(result.as_of).toLocaleString()} ·{' '}
            {result.account_names.join(', ')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            type="button"
            onClick={() => {
              const blob = new Blob([JSON.stringify(result, null, 2)], {
                type: 'application/json',
              })
              const url = URL.createObjectURL(blob)
              const anchor = document.createElement('a')
              anchor.href = url
              anchor.download = `portfolio-scenario-${result.as_of.slice(0, 10)}.json`
              anchor.click()
              URL.revokeObjectURL(url)
            }}
          >
            Export JSON
          </button>
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
            Read only · not persisted
          </span>
        </div>
      </div>

      {changedAccounts.length > 0 && (
        <p
          className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950"
          role="status"
        >
          Current account positions changed after this result was calculated for{' '}
          {changedAccounts
            .map(
              (accountId) =>
                result.account_names[result.account_ids.indexOf(accountId)],
            )
            .join(', ')}
          . This result remains tied to its frozen baseline; calculate again to
          compare the latest positions.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <SnapshotSummary title="Before" snapshot={result.before} />
        <SnapshotSummary title="After" snapshot={result.after} />
      </div>

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-3">
          <h4 className="font-semibold text-slate-900">
            Trade and cash effects
          </h4>
          <p className="mt-1 text-xs text-slate-500">
            Cash-only financing · USD · transaction prices are assumptions
          </p>
        </div>
        {result.trades.length === 0 ? (
          <p className="p-4 text-sm text-slate-600">
            No trades in this scenario.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Account / security</th>
                  <th className="px-4 py-2">Action</th>
                  <th className="px-4 py-2">Quantity</th>
                  <th className="px-4 py-2">Price / fee</th>
                  <th className="px-4 py-2">Cash change</th>
                  <th className="px-4 py-2">Valuation basis</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.trades.map((trade, index) => (
                  <tr key={`${trade.account_id}-${trade.security_id}-${index}`}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">
                        {trade.account_name}
                      </div>
                      <div className="text-xs text-slate-600">
                        {trade.ticker ?? trade.security_id}
                      </div>
                    </td>
                    <td className="px-4 py-3 capitalize">{trade.side}</td>
                    <td className="px-4 py-3">{trade.quantity}</td>
                    <td className="px-4 py-3">
                      {displayMoney(trade.execution_price)} /{' '}
                      {displayMoney(trade.fee_amount)} fee
                    </td>
                    <td className="px-4 py-3">
                      {displayMoney(trade.cash_delta)}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {trade.valuation_price_source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="border-t border-slate-200 px-4 py-3">
          <ul className="space-y-1 text-sm">
            {result.cash.map((item) => (
              <li
                className="flex flex-wrap justify-between gap-x-4 gap-y-1"
                key={item.account_id}
              >
                <span className="text-slate-600">{item.account_name} cash</span>
                <span className="font-medium">
                  {displayMoney(item.cash_before)} →{' '}
                  {displayMoney(item.cash_after)}
                </span>
              </li>
            ))}
          </ul>
          {result.cash_changes.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3 text-xs text-slate-600">
              {result.cash_changes.map((item, index) => (
                <li key={`${item.account_id}-${index}`}>
                  {item.account_name}: {displayMoney(item.amount)} assumed ·{' '}
                  {item.label}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h4 className="font-semibold text-slate-900">Shared ETF holdings</h4>
          <p className="mt-1 text-xs text-slate-500">
            Shared indirect value is shown for overlap review; it is not added
            to portfolio value.
          </p>
          {result.after.overlap_rows.length === 0 ? (
            <p className="mt-3 text-sm text-slate-600">
              No shared look-through securities were identified.
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-100">
              {result.after.overlap_rows.map((row) => (
                <li className="py-3" key={row.security_id}>
                  <div className="flex justify-between gap-3 text-sm">
                    <span className="font-medium text-slate-900">
                      {row.label}
                    </span>
                    <span>{displayMoney(row.shared_indirect_amount)}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {row.fund_labels.join(' · ')}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h4 className="font-semibold text-slate-900">Allocation drift</h4>
          {result.after.drift_status === 'not_requested' ? (
            <p className="mt-2 text-sm text-slate-600">
              No custom allocation targets were entered.
            </p>
          ) : result.after.drift_status === 'unavailable' ? (
            <p className="mt-2 text-sm text-amber-800">
              Drift is unavailable because portfolio valuation is incomplete.
            </p>
          ) : (
            <div className="mt-2 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-2 pr-3">Category</th>
                    <th className="py-2 pr-3">Target</th>
                    <th className="py-2 pr-3">Before</th>
                    <th className="py-2 pr-3">After</th>
                    <th className="py-2">After drift</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {result.after.drift_rows.map((row) => {
                    const beforeRow = result.before.drift_rows.find(
                      (candidate) => candidate.category === row.category,
                    )
                    return (
                      <tr key={row.category}>
                        <td className="py-2 pr-3">
                          {labelForCategory(row.category)}
                        </td>
                        <td className="py-2 pr-3">
                          {displayPercent(row.target_percent)}
                        </td>
                        <td className="py-2 pr-3">
                          {displayPercent(beforeRow?.actual_percent)}
                        </td>
                        <td className="py-2 pr-3">
                          {displayPercent(row.actual_percent)}
                        </td>
                        <td className="py-2">
                          {displayPoints(row.drift_percentage_points)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <details className="rounded-xl border border-slate-200 bg-white p-4">
        <summary className="cursor-pointer font-semibold text-slate-900">
          Fund evidence, warnings, and calculation fingerprints
        </summary>
        <div className="mt-3 space-y-4 text-sm">
          <div>
            <h5 className="font-medium">Fund snapshots</h5>
            {[...result.after.fund_snapshots]
              .sort((left, right) =>
                left.security_id.localeCompare(right.security_id),
              )
              .map((fund) => (
                <p
                  className="mt-1 text-xs text-slate-600"
                  key={fund.security_id}
                >
                  {fund.security_id} · {fund.source} · as of {fund.as_of} ·{' '}
                  {fund.quality_status}
                  {fund.stale ? ' · stale' : ''}
                  {fund.source_url ? ` · ${fund.source_url}` : ''}
                </p>
              ))}
          </div>
          {[...new Set([...result.before.warnings, ...result.after.warnings])]
            .length > 0 && (
            <div>
              <h5 className="font-medium">Warnings</h5>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-amber-900">
                {[
                  ...new Set([
                    ...result.before.warnings,
                    ...result.after.warnings,
                  ]),
                ].map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
          <dl className="grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
            {result.account_ids.map((accountId, index) => (
              <div key={accountId}>
                <dt className="font-medium text-slate-800">
                  {result.account_names[index]} · position revision
                </dt>
                <dd>{result.account_position_revisions[accountId]}</dd>
              </div>
            ))}
            <div>
              <dt className="font-medium text-slate-800">
                Baseline fingerprint
              </dt>
              <dd className="break-all">{result.baseline_fingerprint}</dd>
            </div>
            <div>
              <dt className="font-medium text-slate-800">
                Scenario fingerprint
              </dt>
              <dd className="break-all">{result.scenario_fingerprint}</dd>
            </div>
          </dl>
          <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600">
            {result.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </div>
      </details>
    </section>
  )
}

export default function PortfolioScenarioWorkspace() {
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const securitiesQuery = useQuery({
    queryKey: ['securities'],
    queryFn: fetchSecurities,
  })
  const [asOfDate, setAsOfDate] = useState(localDate)
  const [accountIds, setAccountIds] = useState<string[] | null>(null)
  const [trades, setTrades] = useState<TradeDraft[]>([])
  const [cashChanges, setCashChanges] = useState<CashDraft[]>([])
  const [targetDrafts, setTargetDrafts] = useState<Record<string, string>>({})
  const [result, setResult] = useState<ScenarioResult | null>(null)
  const [formError, setFormError] = useState('')
  const mutation = useMutation({
    mutationFn: simulatePortfolioScenario,
    onSuccess: (response) => {
      setResult(response)
      setFormError('')
    },
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : 'Scenario failed.')
    },
  })

  const activeAccounts = (accountsQuery.data ?? []).filter(
    (account) => account.active,
  )
  const selectedIds =
    accountIds === null
      ? activeAccounts.map((account) => account.id)
      : accountIds
  const availableSecurities = (securitiesQuery.data ?? []).filter(
    (security) =>
      ['equity', 'etf'].includes(security.security_type) &&
      security.currency === 'USD',
  )
  const targetSum = Object.values(targetDrafts).reduce(
    (sum, value) => sum + (value.trim() ? Number(value) || 0 : 0),
    0,
  )
  const hasTargets = Object.values(targetDrafts).some((value) => value.trim())
  const tradeAccountOutsideSelection = trades.some(
    (trade) => !selectedIds.includes(trade.accountId),
  )
  const cashAccountOutsideSelection = cashChanges.some(
    (cash) => !selectedIds.includes(cash.accountId),
  )

  function addTrade() {
    setTrades((current) => [...current, emptyTrade(selectedIds[0] ?? '')])
  }

  function addCashAssumption() {
    setCashChanges((current) => [...current, emptyCash(selectedIds[0] ?? '')])
  }

  function toggleAccount(accountId: string, checked: boolean) {
    setAccountIds((current) => {
      const currentIds = current ?? activeAccounts.map((account) => account.id)
      const next = checked
        ? [...new Set([...currentIds, accountId])]
        : currentIds.filter((id) => id !== accountId)
      return next.length === activeAccounts.length ? null : next
    })
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedIds.length === 0) {
      setFormError('Choose at least one active account.')
      return
    }
    if (tradeAccountOutsideSelection || cashAccountOutsideSelection) {
      setFormError(
        'Every trade and cash assumption must belong to a selected account.',
      )
      return
    }
    if (trades.length === 0 && cashChanges.length === 0) {
      setFormError('Add at least one hypothetical trade or cash assumption.')
      return
    }
    if (hasTargets && Math.abs(targetSum - 100) > 0.00000001) {
      setFormError('Allocation targets must sum to 100%.')
      return
    }
    const now = new Date()
    const localToday = localDate()
    const asOf =
      asOfDate === localToday ? now.toISOString() : `${asOfDate}T23:59:59.999Z`
    const body: ScenarioRequest = {
      account_ids: accountIds ?? [],
      as_of: asOf,
      financing_policy: 'cash_only',
      trades: trades.map((trade) => ({
        account_id: trade.accountId,
        security_id: trade.securityId,
        side: trade.side,
        quantity: trade.quantity,
        price: trade.price,
        fee_amount: trade.fee || '0',
        currency: 'USD',
      })),
      cash_changes: cashChanges.map((cash) => ({
        account_id: cash.accountId,
        amount: cash.amount,
        currency: 'USD',
        label: cash.label,
      })),
      category_targets: hasTargets
        ? CATEGORIES.flatMap(({ key }) =>
            targetDrafts[key]?.trim()
              ? [{ category: key, target_percent: targetDrafts[key].trim() }]
              : [],
          )
        : [],
    }
    setFormError('')
    mutation.mutate(body)
  }

  return (
    <section
      className="mt-8 space-y-5 border-t border-slate-200 pt-8"
      aria-labelledby="portfolio-scenario-heading"
    >
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">
          Stage 3.4 · Planning
        </p>
        <h2
          id="portfolio-scenario-heading"
          className="mt-1 text-2xl font-semibold text-slate-950"
        >
          Portfolio trade scenarios
        </h2>
        <p className="mt-2 max-w-4xl text-sm text-slate-600">
          Compare current exposure with hypothetical USD equity or ETF trades.
          Calculations use frozen position and price inputs. Trade prices are
          assumptions; existing positions keep their baseline valuation price.
          For a held security, a difference between its trade price and baseline
          valuation price changes scenario NAV. No orders are placed and no
          account records are changed.
        </p>
      </div>

      <form className="space-y-5" onSubmit={submit}>
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="grid gap-4 md:grid-cols-[1fr_2fr]">
            <div>
              <label
                className="block text-sm font-medium text-slate-700"
                htmlFor="portfolio-scenario-date"
              >
                Value portfolio as of
              </label>
              <input
                id="portfolio-scenario-date"
                className="mt-1 rounded-lg border border-slate-300 px-3 py-2"
                type="date"
                max={localDate()}
                value={asOfDate}
                onChange={(event) => setAsOfDate(event.target.value)}
                required
              />
            </div>
            <fieldset>
              <legend className="text-sm font-medium text-slate-700">
                Accounts
              </legend>
              {accountsQuery.isPending ? (
                <p className="mt-2 text-sm text-slate-500">Loading accounts…</p>
              ) : activeAccounts.length === 0 ? (
                <p className="mt-2 text-sm text-slate-500">
                  No active accounts are available.
                </p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2">
                  {activeAccounts.map((account) => {
                    const checked = selectedIds.includes(account.id)
                    return (
                      <label
                        className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${checked ? 'border-indigo-300 bg-indigo-50 text-indigo-950' : 'border-slate-200 text-slate-600'}`}
                        key={account.id}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(event) =>
                            toggleAccount(account.id, event.target.checked)
                          }
                        />
                        {account.name}
                      </label>
                    )
                  })}
                </div>
              )}
              <p className="mt-2 text-xs text-slate-500">
                The selected accounts need accepted position history on the
                chosen date.
              </p>
            </fieldset>
          </div>
        </section>

        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold text-slate-900">
                Hypothetical trades
              </h3>
              <p className="text-xs text-slate-500">
                USD equity and ETF securities from the local catalog only.
              </p>
            </div>
            <button
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              type="button"
              onClick={addTrade}
              disabled={selectedIds.length === 0}
            >
              Add trade
            </button>
          </div>
          {trades.map((trade) => (
            <fieldset
              className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-6"
              key={trade.rowId}
            >
              <legend className="sr-only">Hypothetical trade</legend>
              <label className="text-xs font-medium text-slate-600">
                Account
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  value={trade.accountId}
                  onChange={(event) =>
                    setTrades((current) =>
                      current.map((item) =>
                        item.rowId === trade.rowId
                          ? { ...item, accountId: event.target.value }
                          : item,
                      ),
                    )
                  }
                  required
                >
                  {activeAccounts
                    .filter((account) => selectedIds.includes(account.id))
                    .map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="text-xs font-medium text-slate-600">
                Security
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  value={trade.securityId}
                  onChange={(event) =>
                    setTrades((current) =>
                      current.map((item) =>
                        item.rowId === trade.rowId
                          ? { ...item, securityId: event.target.value }
                          : item,
                      ),
                    )
                  }
                  required
                >
                  <option value="">Choose security</option>
                  {availableSecurities.map((security) => (
                    <option key={security.id} value={security.id}>
                      {security.display_ticker ?? security.name} ·{' '}
                      {security.security_type}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-medium text-slate-600">
                Action
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  value={trade.side}
                  onChange={(event) =>
                    setTrades((current) =>
                      current.map((item) =>
                        item.rowId === trade.rowId
                          ? {
                              ...item,
                              side: event.target.value as 'buy' | 'sell',
                            }
                          : item,
                      ),
                    )
                  }
                >
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </select>
              </label>
              <label className="text-xs font-medium text-slate-600">
                Shares
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  inputMode="decimal"
                  pattern="\d+(\.\d{1,10})?"
                  value={trade.quantity}
                  onChange={(event) =>
                    setTrades((current) =>
                      current.map((item) =>
                        item.rowId === trade.rowId
                          ? { ...item, quantity: event.target.value }
                          : item,
                      ),
                    )
                  }
                  required
                />
              </label>
              <label className="text-xs font-medium text-slate-600">
                Price / share
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  inputMode="decimal"
                  pattern="\d+(\.\d{1,10})?"
                  value={trade.price}
                  onChange={(event) =>
                    setTrades((current) =>
                      current.map((item) =>
                        item.rowId === trade.rowId
                          ? { ...item, price: event.target.value }
                          : item,
                      ),
                    )
                  }
                  required
                />
              </label>
              <div className="flex items-end gap-2">
                <label className="min-w-0 flex-1 text-xs font-medium text-slate-600">
                  Fee
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                    inputMode="decimal"
                    pattern="\d+(\.\d{1,10})?"
                    value={trade.fee}
                    onChange={(event) =>
                      setTrades((current) =>
                        current.map((item) =>
                          item.rowId === trade.rowId
                            ? { ...item, fee: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  className="rounded-lg px-2 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50"
                  type="button"
                  onClick={() =>
                    setTrades((current) =>
                      current.filter((item) => item.rowId !== trade.rowId),
                    )
                  }
                  aria-label="Remove trade"
                >
                  Remove
                </button>
              </div>
            </fieldset>
          ))}
          {trades.length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600">
              Add a buy or sale to compare the portfolio before and after.
            </p>
          )}
        </section>

        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold text-slate-900">Cash assumptions</h3>
              <p className="text-xs text-slate-500">
                Use signed amounts for contributions or withdrawals. Cash-only
                financing prevents borrowing.
              </p>
            </div>
            <button
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              type="button"
              onClick={addCashAssumption}
              disabled={selectedIds.length === 0}
            >
              Add cash change
            </button>
          </div>
          {cashChanges.map((cash) => (
            <fieldset
              className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-[1fr_1fr_2fr_auto]"
              key={cash.rowId}
            >
              <legend className="sr-only">Cash assumption</legend>
              <label className="text-xs font-medium text-slate-600">
                Account
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  value={cash.accountId}
                  onChange={(event) =>
                    setCashChanges((current) =>
                      current.map((item) =>
                        item.rowId === cash.rowId
                          ? { ...item, accountId: event.target.value }
                          : item,
                      ),
                    )
                  }
                  required
                >
                  {activeAccounts
                    .filter((account) => selectedIds.includes(account.id))
                    .map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="text-xs font-medium text-slate-600">
                Amount (USD, + / −)
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  inputMode="decimal"
                  pattern="-?\d+(\.\d{1,10})?"
                  value={cash.amount}
                  onChange={(event) =>
                    setCashChanges((current) =>
                      current.map((item) =>
                        item.rowId === cash.rowId
                          ? { ...item, amount: event.target.value }
                          : item,
                      ),
                    )
                  }
                  required
                />
              </label>
              <label className="text-xs font-medium text-slate-600">
                Reason
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
                  value={cash.label}
                  onChange={(event) =>
                    setCashChanges((current) =>
                      current.map((item) =>
                        item.rowId === cash.rowId
                          ? { ...item, label: event.target.value }
                          : item,
                      ),
                    )
                  }
                  maxLength={120}
                  required
                />
              </label>
              <button
                className="self-end rounded-lg px-2 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50"
                type="button"
                onClick={() =>
                  setCashChanges((current) =>
                    current.filter((item) => item.rowId !== cash.rowId),
                  )
                }
              >
                Remove
              </button>
            </fieldset>
          ))}
          {(tradeAccountOutsideSelection || cashAccountOutsideSelection) && (
            <p className="text-sm text-amber-800" role="status">
              A trade or cash change belongs to an account outside the current
              selection. Re-select that account or update/remove the row.
            </p>
          )}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h3 className="font-semibold text-slate-900">
                Optional category targets
              </h3>
              <p className="text-xs text-slate-500">
                Enter any categories you want to target; omitted categories are
                treated as zero. Entered targets must total 100%.
              </p>
            </div>
            {hasTargets && (
              <p
                className={`text-sm font-semibold ${Math.abs(targetSum - 100) < 0.00000001 ? 'text-emerald-700' : 'text-amber-800'}`}
              >
                Total: {targetSum}%
              </p>
            )}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {CATEGORIES.map(({ key, label }) => (
              <label className="text-xs font-medium text-slate-600" key={key}>
                {label} target %
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  inputMode="decimal"
                  pattern="\d+(\.\d{1,10})?"
                  value={targetDrafts[key] ?? ''}
                  onChange={(event) =>
                    setTargetDrafts((current) => ({
                      ...current,
                      [key]: event.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </div>
        </section>

        {formError && (
          <p
            className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
            role="alert"
          >
            {formError}
          </p>
        )}
        {mutation.isError && !formError && (
          <p className="text-sm text-rose-700" role="alert">
            The portfolio scenario could not be calculated.
          </p>
        )}
        <button
          className="rounded-lg bg-indigo-700 px-5 py-3 font-semibold text-white hover:bg-indigo-800 disabled:opacity-50"
          type="submit"
          disabled={
            mutation.isPending ||
            accountsQuery.isPending ||
            securitiesQuery.isPending ||
            selectedIds.length === 0
          }
        >
          {mutation.isPending ? 'Calculating scenario…' : 'Calculate scenario'}
        </button>
      </form>

      <aside className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-950">
        <h3 className="font-semibold">Model boundaries</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            Trade entry prices value newly introduced positions until a
            source-backed valuation is available.
          </li>
          <li>
            Buys require available USD cash, including fees. Sales cannot exceed
            actual holdings. Margin and FX conversion are unsupported.
          </li>
          <li>
            ETF look-through depends on dated published fund data. Missing,
            nested, stale, or opaque exposure remains visible in residuals and
            warnings.
          </li>
          <li>
            Indirect holdings decompose the portfolio value; they are not added
            to owned assets or net worth.
          </li>
        </ul>
      </aside>

      {result && <PortfolioScenarioResult result={result} />}
    </section>
  )
}
