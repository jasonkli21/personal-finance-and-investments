import { moneyDisplay as formatMoney } from './decimal-display'
import { localDate } from './local-date'
import { useState, type FormEvent } from 'react'
import { useMutation, useQueries, useQuery } from '@tanstack/react-query'
import {
  fetchAccounts,
  fetchPositions,
  simulatePlanningScenario,
} from './api/client'
import type { components } from './api/schema'

type PlanningRequest = components['schemas']['PlanningScenarioRequest']
type PlanningResult = components['schemas']['PlanningScenarioRead']
type RecurringDraft = { id: string; amount: string; label: string }
type OneTimeDraft = {
  id: string
  monthOffset: string
  changeType: 'purchase' | 'liability_payment' | 'other'
  amount: string
  label: string
}

function formatDate(value: string | null | undefined): string {
  return value
    ? new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString()
    : 'Unavailable'
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="font-semibold text-slate-900">{title}</h3>
      {children}
    </section>
  )
}

function PlanningResultView({ result }: { result: PlanningResult }) {
  const positionQueries = useQueries({
    queries: result.account_ids
      .filter((accountId) => result.position_snapshot_ids[accountId])
      .map((accountId) => ({
        queryKey: ['positions', accountId],
        queryFn: () => fetchPositions(accountId),
      })),
  })
  const revisionAccounts = result.account_ids.filter(
    (accountId) => result.position_snapshot_ids[accountId],
  )
  const isSameDay = result.as_of === localDate()
  const changedAccounts = revisionAccounts.filter((accountId, index) => {
    const query = positionQueries[index]
    return (
      isSameDay &&
      query?.data !== undefined &&
      query.data.current_revision !==
        result.account_position_revisions[accountId]
    )
  })
  const base = result.cases.find((item) => item.case === 'base')

  return (
    <section className="space-y-5" aria-label="Planning scenario results">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">
            {result.scenario_label}
          </h3>
          <p className="text-sm text-slate-600">
            As of {formatDate(result.as_of)} · projection starts{' '}
            {formatDate(result.projection_start)} · {result.horizon_months}{' '}
            months
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
              anchor.download = `planning-scenario-${result.as_of}.json`
              anchor.click()
              window.setTimeout(() => URL.revokeObjectURL(url), 1000)
            }}
          >
            Export JSON
          </button>
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
            Read only · not saved
          </span>
        </div>
      </div>

      {changedAccounts.length > 0 && (
        <p
          className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950"
          role="status"
        >
          Current position revisions changed after this calculation for{' '}
          {changedAccounts
            .map(
              (accountId) =>
                result.account_names[result.account_ids.indexOf(accountId)],
            )
            .join(', ')}
          . This result remains tied to its original dated inputs; calculate
          again to use the latest positions.
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Observed USD liquid cash
          </p>
          <p className="mt-1 text-xl font-semibold text-slate-950">
            {formatMoney(result.liquid_cash_observed_usd)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {result.starting_cash_source === 'user_override'
              ? 'Projection uses the explicit override below.'
              : `Projection cash coverage: ${result.starting_cash_coverage}.`}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Projection starting cash
          </p>
          <p className="mt-1 text-xl font-semibold text-slate-950">
            {formatMoney(result.starting_cash_usd)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {result.starting_cash_source === 'user_override'
              ? 'User-entered total assumption'
              : 'Observed USD cash in selected non-retirement accounts'}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Balance sheet evidence
          </p>
          <p className="mt-1 text-xl font-semibold text-slate-950">
            {result.balance_sheet_complete ? 'Complete' : 'Incomplete'}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Projection {result.projection_status}; assets remain separate by
            currency.
          </p>
        </div>
      </div>

      <Section title="Observed assets and liabilities by currency">
        {result.currency_balances.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">
            No valued balance lines were available for these accounts.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">Currency</th>
                  <th className="px-3 py-2">Liquid cash</th>
                  <th className="px-3 py-2">Investments</th>
                  <th className="px-3 py-2">Restricted</th>
                  <th className="px-3 py-2">Other assets</th>
                  <th className="px-3 py-2">Liabilities</th>
                  <th className="px-3 py-2">Known net worth</th>
                  <th className="px-3 py-2">Evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.currency_balances.map((row) => (
                  <tr key={row.currency}>
                    <td className="px-3 py-2 font-semibold">{row.currency}</td>
                    <td className="px-3 py-2">
                      {formatMoney(row.liquid_cash, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {formatMoney(row.investment_assets, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {formatMoney(row.restricted_assets, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {formatMoney(row.other_assets, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {formatMoney(row.liabilities, row.currency)}
                    </td>
                    <td className="px-3 py-2 font-medium">
                      {formatMoney(row.known_net_worth, row.currency)}
                    </td>
                    <td className="px-3 py-2">{row.completeness}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <details className="mt-4 rounded-lg border border-slate-200 p-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-800">
            Account-level source and quality details
          </summary>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-xs">
              <thead className="bg-slate-50 uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">Account / item</th>
                  <th className="px-3 py-2">Bucket</th>
                  <th className="px-3 py-2">Snapshot / price date</th>
                  <th className="px-3 py-2">Value</th>
                  <th className="px-3 py-2">Source / quality</th>
                  <th className="px-3 py-2">Revision</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.balances.map((line, index) => (
                  <tr
                    key={`${line.account_id}-${line.detail ?? line.bucket}-${index}`}
                  >
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900">
                        {line.account_name}
                      </div>
                      <div className="text-slate-500">
                        {line.detail ?? line.account_type}
                      </div>
                    </td>
                    <td className="px-3 py-2">{line.bucket}</td>
                    <td className="px-3 py-2">
                      Snapshot {formatDate(line.as_of)} · price{' '}
                      {formatDate(line.price_as_of)} ·{' '}
                      {line.currency ?? 'Unknown'}
                    </td>
                    <td className="px-3 py-2">
                      {line.amount === null
                        ? 'Unavailable'
                        : formatMoney(line.amount, line.currency ?? 'USD')}
                    </td>
                    <td className="px-3 py-2">
                      {line.source ?? 'Unavailable'} · {line.quality_status} ·{' '}
                      {line.status}
                    </td>
                    <td className="px-3 py-2">
                      {line.position_revision !== null
                        ? `position ${line.position_revision}`
                        : line.balance_revision !== null
                          ? `balance ${line.balance_revision}`
                          : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </Section>

      <Section title="Historical cash-flow context">
        <p className="mt-1 text-xs text-slate-500">
          Selected records from {formatDate(result.history_start)} through{' '}
          {formatDate(result.history_end)}. These observations are not copied
          into the projection assumptions.
        </p>
        {result.transaction_history.length === 0 ? (
          <p className="mt-3 text-sm text-slate-600">
            No eligible published transactions were observed in the sample.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">Currency</th>
                  <th className="px-3 py-2">Recorded income</th>
                  <th className="px-3 py-2">Income average / month</th>
                  <th className="px-3 py-2">Recorded expenses</th>
                  <th className="px-3 py-2">Expense average / month</th>
                  <th className="px-3 py-2">Unclassified rows</th>
                  <th className="px-3 py-2">Sources</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.transaction_history.map((row) => (
                  <tr key={row.currency}>
                    <td className="px-3 py-2 font-semibold">{row.currency}</td>
                    <td className="px-3 py-2">
                      {formatMoney(row.income_total, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {formatMoney(row.income_monthly_average, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {formatMoney(row.expenses_total, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {formatMoney(row.expenses_monthly_average, row.currency)}
                    </td>
                    <td className="px-3 py-2">
                      {row.unclassified_count} ·{' '}
                      {formatMoney(
                        row.unclassified_signed_amount,
                        row.currency,
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {row.source_labels.join(', ') || 'Unavailable'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-800">
            Reviewed dividend events
          </h4>
          {result.dividend_history.length === 0 ? (
            <p className="mt-1 text-sm text-slate-600">
              No reviewed dividend events were found in this sample.
            </p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {result.dividend_history.map((row) => (
                <li
                  className="flex flex-wrap justify-between gap-2"
                  key={row.currency}
                >
                  <span>
                    {row.currency} · {row.event_count} events ·{' '}
                    {row.source_labels.join(', ')}
                  </span>
                  <span>
                    {formatMoney(row.total, row.currency)} total ·{' '}
                    {formatMoney(row.monthly_average, row.currency)} monthly
                    average
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-amber-900">
          {result.history_gaps.map((gap, index) => (
            <li key={`${index}-${gap}`}>{gap}</li>
          ))}
        </ul>
      </Section>

      <Section
        title={`Cash projection · ±${result.sensitivity_percent}% sensitivity`}
      >
        <div className="grid gap-3 md:grid-cols-3">
          {result.cases.map((scenario) => (
            <div
              className={`rounded-xl border p-4 ${scenario.case === 'base' ? 'border-indigo-300 bg-indigo-50' : 'border-slate-200 bg-white'}`}
              key={scenario.case}
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {scenario.case}
              </p>
              <p className="mt-1 text-xl font-semibold text-slate-950">
                {formatMoney(scenario.ending_cash)}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                End cash · {scenario.runway_status.replaceAll('_', ' ')}
                {scenario.shortfall_month !== null
                  ? ` · shortfall in month ${scenario.shortfall_month}`
                  : ''}
              </p>
            </div>
          ))}
        </div>
        {base && (
          <details className="mt-4 rounded-lg border border-slate-200 p-3" open>
            <summary className="cursor-pointer text-sm font-medium text-slate-800">
              Base case month-by-month cash
            </summary>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Month</th>
                    <th className="px-3 py-2">Starting cash</th>
                    <th className="px-3 py-2">Income</th>
                    <th className="px-3 py-2">Expenses</th>
                    <th className="px-3 py-2">Dividends</th>
                    <th className="px-3 py-2">Recurring changes</th>
                    <th className="px-3 py-2">One-time changes</th>
                    <th className="px-3 py-2">Ending cash</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {base.months.map((month) => (
                    <tr key={month.month_index}>
                      <td className="px-3 py-2">
                        {formatDate(month.month_start)}
                      </td>
                      <td className="px-3 py-2">
                        {formatMoney(month.starting_cash)}
                      </td>
                      <td className="px-3 py-2">{formatMoney(month.income)}</td>
                      <td className="px-3 py-2">
                        {formatMoney(month.expenses)}
                      </td>
                      <td className="px-3 py-2">
                        {formatMoney(month.dividends)}
                      </td>
                      <td className="px-3 py-2">
                        {formatMoney(month.recurring_changes)}
                      </td>
                      <td className="px-3 py-2">
                        {formatMoney(month.one_time_changes)}
                      </td>
                      <td className="px-3 py-2 font-medium">
                        {formatMoney(month.ending_cash)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
        <details className="mt-3 rounded-lg border border-slate-200 p-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-800">
            Assumptions, warnings, and reproducibility
          </summary>
          <div className="mt-3 space-y-3 text-xs text-slate-600">
            <p>
              Monthly income {formatMoney(result.monthly_income_assumption)},
              expenses {formatMoney(result.monthly_expense_assumption)}, and
              dividends {formatMoney(result.monthly_dividend_assumption)} use
              these source labels: income “{result.monthly_income_source}”,
              expenses “{result.monthly_expenses_source}”, dividends “
              {result.monthly_dividends_source}”. Conservative/optimistic cases
              adjust income and dividends opposite to expenses using the
              displayed sensitivity percentage.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
            <dl>
              <dt className="font-medium text-slate-800">
                Scenario fingerprint
              </dt>
              <dd className="break-all">{result.scenario_fingerprint}</dd>
            </dl>
          </div>
        </details>
      </Section>
    </section>
  )
}

export default function PlanningWorkspace() {
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const [accountIds, setAccountIds] = useState<string[] | null>(null)
  const [asOf, setAsOf] = useState(localDate())
  const [horizon, setHorizon] = useState('12')
  const [historyMonths, setHistoryMonths] = useState('6')
  const [income, setIncome] = useState('')
  const [incomeSource, setIncomeSource] = useState(
    'User-entered income assumption',
  )
  const [expenses, setExpenses] = useState('')
  const [expensesSource, setExpensesSource] = useState(
    'User-entered expense budget',
  )
  const [dividends, setDividends] = useState('')
  const [dividendsSource, setDividendsSource] = useState(
    'User-entered dividend assumption',
  )
  const [sensitivity, setSensitivity] = useState('10')
  const [startingCashOverride, setStartingCashOverride] = useState('')
  const [scenarioLabel, setScenarioLabel] = useState('Large purchase plan')
  const [recurringChanges, setRecurringChanges] = useState<RecurringDraft[]>([])
  const [oneTimeChanges, setOneTimeChanges] = useState<OneTimeDraft[]>([])
  const [result, setResult] = useState<PlanningResult | null>(null)
  const [formError, setFormError] = useState('')
  const mutation = useMutation({
    mutationFn: simulatePlanningScenario,
    onSuccess: (response) => {
      setResult(response)
      setFormError('')
    },
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : 'Planning failed.')
    },
  })

  const activeAccounts = (accountsQuery.data ?? []).filter(
    (account) => account.active,
  )
  const selectedIds =
    accountIds === null
      ? activeAccounts.map((account) => account.id)
      : accountIds
  const accountSelectionLabel =
    accountIds === null ? 'All active accounts' : 'Selected accounts'

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
    if (selectedIds.length > 100) {
      setFormError('Select no more than 100 active accounts per scenario.')
      return
    }
    if (
      selectedIds.some(
        (id) => !activeAccounts.some((account) => account.id === id),
      )
    ) {
      setFormError('Every selected account must still be active.')
      return
    }
    const maxHorizon = Number(horizon)
    if (!Number.isInteger(maxHorizon) || maxHorizon < 1 || maxHorizon > 120) {
      setFormError('Projection horizon must be between 1 and 120 months.')
      return
    }
    const sampleMonths = Number(historyMonths)
    if (
      !Number.isInteger(sampleMonths) ||
      sampleMonths < 1 ||
      sampleMonths > 60
    ) {
      setFormError('Historical sample must be between 1 and 60 months.')
      return
    }
    if (!income.trim() || !expenses.trim() || !dividends.trim()) {
      setFormError(
        'Enter explicit monthly income, expense, and dividend assumptions. Use 0 only when you intentionally assume none.',
      )
      return
    }
    if (oneTimeChanges.some((item) => Number(item.monthOffset) > maxHorizon)) {
      setFormError(
        'Each one-time change must fall inside the projection horizon.',
      )
      return
    }
    const input: PlanningRequest = {
      account_ids: accountIds ?? [],
      as_of: asOf,
      horizon_months: maxHorizon,
      history_months: sampleMonths,
      monthly_income: income.trim(),
      monthly_income_source: incomeSource.trim(),
      monthly_expenses: expenses.trim(),
      monthly_expenses_source: expensesSource.trim(),
      monthly_dividends: dividends.trim(),
      monthly_dividends_source: dividendsSource.trim(),
      sensitivity_percent: sensitivity.trim(),
      ...(startingCashOverride.trim()
        ? { starting_cash_override: startingCashOverride.trim() }
        : {}),
      recurring_changes: recurringChanges.map((change) => ({
        amount: change.amount.trim(),
        label: change.label.trim(),
      })),
      one_time_changes: oneTimeChanges.map((change) => ({
        month_offset: Number(change.monthOffset),
        change_type: change.changeType,
        amount: change.amount.trim(),
        label: change.label.trim(),
      })),
      scenario_label: scenarioLabel.trim(),
    }
    setFormError('')
    mutation.mutate(input)
  }

  return (
    <section
      className="mx-auto flex max-w-6xl flex-col gap-6 border-t border-slate-200 px-5 pb-12 pt-8 sm:px-8"
      aria-labelledby="planning-heading"
    >
      <header>
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">
          Stage 3.5 · Planning
        </p>
        <h2
          id="planning-heading"
          className="mt-2 text-2xl font-semibold tracking-tight text-slate-950"
        >
          Income, runway, and purchase scenarios
        </h2>
        <p className="mt-2 max-w-4xl text-sm text-slate-600">
          Review dated cash, investments, restricted assets, liabilities, and
          imported cash-flow observations, then project only the assumptions you
          enter. Investment and retirement assets are never treated as spendable
          cash. No balances or transactions are changed.
        </p>
      </header>

      {formError && (
        <p
          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
          role="alert"
        >
          {formError}
        </p>
      )}

      <form className="space-y-5" onSubmit={submit}>
        <Section title="Date, accounts, and projection horizon">
          <div className="grid gap-4 md:grid-cols-3">
            <label className="text-sm font-medium text-slate-700">
              Balance-sheet as of
              <input
                className="mt-1 block rounded-lg border border-slate-300 px-3 py-2"
                type="date"
                max={localDate()}
                value={asOf}
                onChange={(event) => setAsOf(event.target.value)}
                required
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Projection months (1–120)
              <input
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                type="number"
                min={1}
                max={120}
                value={horizon}
                onChange={(event) => setHorizon(event.target.value)}
                required
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              History sample months (1–60)
              <input
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                type="number"
                min={1}
                max={60}
                value={historyMonths}
                onChange={(event) => setHistoryMonths(event.target.value)}
                required
              />
            </label>
          </div>
          <fieldset className="mt-4">
            <legend className="text-sm font-medium text-slate-700">
              Accounts · {accountSelectionLabel}
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
                      className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${checked ? 'border-teal-300 bg-teal-50 text-teal-950' : 'border-slate-200 text-slate-600'}`}
                      key={account.id}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) =>
                          toggleAccount(account.id, event.target.checked)
                        }
                      />
                      {account.name} · {account.account_type}
                    </label>
                  )
                })}
              </div>
            )}
          </fieldset>
          <label className="mt-4 block max-w-xl text-sm font-medium text-slate-700">
            Scenario label
            <input
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={scenarioLabel}
              maxLength={100}
              onChange={(event) => setScenarioLabel(event.target.value)}
              required
            />
          </label>
        </Section>

        <Section title="Explicit monthly assumptions · USD">
          <p className="mt-1 text-xs text-slate-500">
            Enter nonnegative amounts. Historical records appear below as
            context; they do not prefill or generate the projection.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="text-sm font-medium text-slate-700">
              Monthly income
              <input
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                inputMode="decimal"
                pattern="\d+(\.\d{1,10})?"
                placeholder="Enter 0 only if intentional"
                value={income}
                onChange={(event) => setIncome(event.target.value)}
                required
              />
              <input
                className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal"
                aria-label="Monthly income assumption source"
                placeholder="Source / note"
                maxLength={100}
                value={incomeSource}
                onChange={(event) => setIncomeSource(event.target.value)}
                required
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Monthly expenses
              <input
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                inputMode="decimal"
                pattern="\d+(\.\d{1,10})?"
                placeholder="Enter 0 only if intentional"
                value={expenses}
                onChange={(event) => setExpenses(event.target.value)}
                required
              />
              <input
                className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal"
                aria-label="Monthly expense assumption source"
                placeholder="Source / note"
                maxLength={100}
                value={expensesSource}
                onChange={(event) => setExpensesSource(event.target.value)}
                required
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Monthly dividends
              <input
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                inputMode="decimal"
                pattern="\d+(\.\d{1,10})?"
                placeholder="Enter 0 only if intentional"
                value={dividends}
                onChange={(event) => setDividends(event.target.value)}
                required
              />
              <input
                className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal"
                aria-label="Monthly dividend assumption source"
                placeholder="Source / note"
                maxLength={100}
                value={dividendsSource}
                onChange={(event) => setDividendsSource(event.target.value)}
                required
              />
            </label>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-700">
              Sensitivity range (0–50%)
              <input
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                inputMode="decimal"
                pattern="\d+(\.\d{1,10})?"
                value={sensitivity}
                onChange={(event) => setSensitivity(event.target.value)}
                required
              />
              <span className="mt-1 block text-xs font-normal text-slate-500">
                Conservative reduces income/dividends and raises expenses;
                optimistic applies the reverse.
              </span>
            </label>
            <label className="text-sm font-medium text-slate-700">
              Optional starting USD cash override
              <input
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                inputMode="decimal"
                pattern="\d+(\.\d{1,10})?"
                placeholder="Leave blank to use observed cash"
                value={startingCashOverride}
                onChange={(event) =>
                  setStartingCashOverride(event.target.value)
                }
              />
              <span className="mt-1 block text-xs font-normal text-slate-500">
                Replaces observed USD cash for this calculation when provided.
              </span>
            </label>
          </div>
        </Section>

        <Section title="Recurring monthly cash changes">
          <p className="mt-1 text-xs text-slate-500">
            Optional signed additions to the three monthly assumptions, such as
            a new bill or side income. Use a negative amount for an outflow.
          </p>
          <div className="mt-3 space-y-3">
            {recurringChanges.map((change) => (
              <fieldset
                className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1fr_2fr_auto]"
                key={change.id}
              >
                <legend className="sr-only">Recurring change</legend>
                <label className="text-xs font-medium text-slate-600">
                  Signed monthly amount (USD)
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    inputMode="decimal"
                    pattern="-?\d+(\.\d{1,10})?"
                    value={change.amount}
                    onChange={(event) =>
                      setRecurringChanges((current) =>
                        current.map((item) =>
                          item.id === change.id
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
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    value={change.label}
                    onChange={(event) =>
                      setRecurringChanges((current) =>
                        current.map((item) =>
                          item.id === change.id
                            ? { ...item, label: event.target.value }
                            : item,
                        ),
                      )
                    }
                    maxLength={100}
                    required
                  />
                </label>
                <button
                  className="self-end rounded-lg px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50"
                  type="button"
                  onClick={() =>
                    setRecurringChanges((current) =>
                      current.filter((item) => item.id !== change.id),
                    )
                  }
                >
                  Remove
                </button>
              </fieldset>
            ))}
          </div>
          <button
            className="mt-3 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            type="button"
            onClick={() =>
              setRecurringChanges((current) => [
                ...current,
                { id: crypto.randomUUID(), amount: '', label: '' },
              ])
            }
            disabled={recurringChanges.length >= 20}
          >
            Add recurring change
          </button>
        </Section>

        <Section title="One-time purchases and cash changes">
          <p className="mt-1 text-xs text-slate-500">
            Month 1 is the first full calendar month after the as-of date. Enter
            signed amounts: purchases and liability payments must be negative.
          </p>
          <div className="mt-3 space-y-3">
            {oneTimeChanges.map((change) => (
              <fieldset
                className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-5"
                key={change.id}
              >
                <legend className="sr-only">One-time cash change</legend>
                <label className="text-xs font-medium text-slate-600">
                  Month
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    type="number"
                    min={1}
                    max={horizon}
                    value={change.monthOffset}
                    onChange={(event) =>
                      setOneTimeChanges((current) =>
                        current.map((item) =>
                          item.id === change.id
                            ? { ...item, monthOffset: event.target.value }
                            : item,
                        ),
                      )
                    }
                    required
                  />
                </label>
                <label className="text-xs font-medium text-slate-600">
                  Type
                  <select
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    value={change.changeType}
                    onChange={(event) =>
                      setOneTimeChanges((current) =>
                        current.map((item) =>
                          item.id === change.id
                            ? {
                                ...item,
                                changeType: event.target
                                  .value as OneTimeDraft['changeType'],
                              }
                            : item,
                        ),
                      )
                    }
                  >
                    <option value="purchase">Purchase</option>
                    <option value="liability_payment">Liability payment</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label className="text-xs font-medium text-slate-600">
                  Signed amount (USD)
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    inputMode="decimal"
                    pattern="-?\d+(\.\d{1,10})?"
                    value={change.amount}
                    onChange={(event) =>
                      setOneTimeChanges((current) =>
                        current.map((item) =>
                          item.id === change.id
                            ? { ...item, amount: event.target.value }
                            : item,
                        ),
                      )
                    }
                    required
                  />
                </label>
                <label className="text-xs font-medium text-slate-600">
                  Label
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    value={change.label}
                    onChange={(event) =>
                      setOneTimeChanges((current) =>
                        current.map((item) =>
                          item.id === change.id
                            ? { ...item, label: event.target.value }
                            : item,
                        ),
                      )
                    }
                    maxLength={100}
                    required
                  />
                </label>
                <button
                  className="self-end rounded-lg px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50"
                  type="button"
                  onClick={() =>
                    setOneTimeChanges((current) =>
                      current.filter((item) => item.id !== change.id),
                    )
                  }
                >
                  Remove
                </button>
              </fieldset>
            ))}
          </div>
          <button
            className="mt-3 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            type="button"
            onClick={() =>
              setOneTimeChanges((current) => [
                ...current,
                {
                  id: crypto.randomUUID(),
                  monthOffset: '1',
                  changeType: 'purchase',
                  amount: '',
                  label: '',
                },
              ])
            }
            disabled={oneTimeChanges.length >= 100}
          >
            Add purchase / cash change
          </button>
        </Section>

        <button
          className="rounded-lg bg-teal-700 px-5 py-3 font-semibold text-white hover:bg-teal-800 disabled:opacity-50"
          type="submit"
          disabled={
            mutation.isPending ||
            accountsQuery.isPending ||
            selectedIds.length === 0
          }
        >
          {mutation.isPending
            ? 'Calculating plan…'
            : 'Calculate runway and purchase scenarios'}
        </button>
      </form>

      <aside className="rounded-xl border border-teal-100 bg-teal-50 p-4 text-sm text-teal-950">
        <h3 className="font-semibold">Planning limits</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            Projection uses USD cash only. No currency conversion, investment
            sale, tax, credit facility, or automatic liability payment is
            assumed.
          </li>
          <li>
            IRA, Roth IRA, 401(k), and HSA assets are shown as restricted and do
            not fund purchases.
          </li>
          <li>
            Historical transactions and reviewed dividend events are context,
            not guarantees. Dividend-event history may overlap transaction
            income.
          </li>
          <li>
            The sensitivity cases are arithmetic what-if ranges, not probability
            estimates or financial advice.
          </li>
        </ul>
      </aside>

      {result && <PlanningResultView result={result} />}
    </section>
  )
}
