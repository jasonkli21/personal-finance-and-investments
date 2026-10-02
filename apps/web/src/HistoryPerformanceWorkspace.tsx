import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createInvestmentEvent,
  fetchAccounts,
  fetchPortfolioHistory,
  fetchPortfolioPerformance,
  fetchSecurities,
  fetchHistoryReconciliation,
} from './api/client'
import type { components } from './api/schema'
import { decimalDisplay } from './decimal-display'

type EventType = components['schemas']['InvestmentEventCreate']['event_type']

function localDate(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function priorYear(): string {
  const value = new Date()
  value.setFullYear(value.getFullYear() - 1)
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${value.getFullYear()}-${month}-${day}`
}

function percent(value: string | null): string {
  if (value === null) return 'Unavailable'
  const match = /^(-?)(\d+)(?:\.(\d*))?$/.exec(value)
  if (!match) return 'Unavailable'
  const fraction = (match[3] ?? '').padEnd(14, '0')
  const scale = 10n ** 14n
  const units = BigInt(match[2]) * scale + BigInt(fraction.slice(0, 14))
  const hundredths = (units * 10_000n + scale / 2n) / scale
  const whole = hundredths / 100n
  const decimal = String(hundredths % 100n).padStart(2, '0')
  return `${match[1] && hundredths !== 0n ? '-' : ''}${whole}.${decimal}%`
}

export default function HistoryPerformanceWorkspace() {
  const queryClient = useQueryClient()
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const securitiesQuery = useQuery({
    queryKey: ['securities'],
    queryFn: fetchSecurities,
  })
  const accounts = (accountsQuery.data ?? []).filter((row) => row.active)
  const [accountId, setAccountId] = useState('')
  const [startDate, setStartDate] = useState(priorYear)
  const [endDate, setEndDate] = useState(localDate)
  const [eventType, setEventType] = useState<EventType>('deposit')
  const [effectiveDate, setEffectiveDate] = useState(localDate)
  const [securityId, setSecurityId] = useState('')
  const [quantityDelta, setQuantityDelta] = useState('')
  const [cashAmount, setCashAmount] = useState('')
  const [sourceEventId, setSourceEventId] = useState('')
  const [evidenceRef, setEvidenceRef] = useState('')
  const [notice, setNotice] = useState('')

  const selectedAccountId = accountId || accounts[0]?.id || ''
  const request = { accountId: selectedAccountId, startDate, endDate }
  const historyQuery = useQuery({
    queryKey: ['portfolio-history', selectedAccountId, startDate, endDate],
    queryFn: () => fetchPortfolioHistory(request),
    enabled: Boolean(selectedAccountId && startDate && endDate),
  })
  const performanceQuery = useQuery({
    queryKey: ['portfolio-performance', selectedAccountId, startDate, endDate],
    queryFn: () => fetchPortfolioPerformance(request),
    enabled: Boolean(selectedAccountId && startDate && endDate),
  })
  const reconciliationQuery = useQuery({
    queryKey: [
      'portfolio-history-reconciliation',
      selectedAccountId,
      startDate,
      endDate,
    ],
    queryFn: () => fetchHistoryReconciliation(request),
    enabled: Boolean(selectedAccountId && startDate && endDate),
  })
  const account = accounts.find((row) => row.id === selectedAccountId)

  const addEvent = useMutation({
    mutationFn: () => {
      if (
        !selectedAccountId ||
        !effectiveDate ||
        (!sourceEventId.trim() && eventType === 'other')
      ) {
        throw new Error(
          'Complete an account, event date and source for this event.',
        )
      }
      const quantityEvent = [
        'buy',
        'sell',
        'split',
        'adjustment',
        'transfer_in',
        'transfer_out',
      ].includes(eventType)
      const needsSecurity = quantityEvent
      const externalFlow = ['deposit', 'withdrawal'].includes(eventType)
      const selectedSecurity = (securitiesQuery.data ?? []).find(
        (item) => item.id === securityId,
      )
      const linkedCash =
        externalFlow && selectedSecurity?.security_type === 'cash'
      if (needsSecurity && !securityId) {
        throw new Error(
          'Select the actual owned security affected by this event.',
        )
      }
      if (
        eventType === 'buy' &&
        (!quantityDelta || Number(quantityDelta) <= 0)
      ) {
        throw new Error('A purchase requires a positive quantity change.')
      }
      if (
        eventType === 'sell' &&
        (!quantityDelta || Number(quantityDelta) >= 0)
      ) {
        throw new Error('A sale requires a negative quantity change.')
      }
      if (
        eventType === 'transfer_in' &&
        (!quantityDelta || Number(quantityDelta) <= 0)
      ) {
        throw new Error('A transfer in requires a positive quantity change.')
      }
      if (
        eventType === 'transfer_out' &&
        (!quantityDelta || Number(quantityDelta) >= 0)
      ) {
        throw new Error('A transfer out requires a negative quantity change.')
      }
      if (eventType === 'deposit' && (!cashAmount || Number(cashAmount) <= 0)) {
        throw new Error('Enter a positive deposit amount.')
      }
      if (
        eventType === 'withdrawal' &&
        (!cashAmount || Number(cashAmount) >= 0)
      ) {
        throw new Error('Enter a negative withdrawal amount.')
      }
      return createInvestmentEvent({
        account_id: selectedAccountId,
        event_type: eventType,
        effective_date: effectiveDate,
        security_id: needsSecurity || linkedCash ? securityId : null,
        quantity_delta: quantityEvent
          ? quantityDelta || null
          : linkedCash
            ? cashAmount || null
            : null,
        cash_amount: cashAmount || null,
        currency: account?.base_currency ?? 'USD',
        source_label: 'Manual history entry',
        source_event_id: sourceEventId || null,
        evidence_ref: evidenceRef || null,
        quality_status: 'manual',
        idempotency_key: crypto.randomUUID(),
      })
    },
    onSuccess: async () => {
      setNotice(
        'Event saved with manual source status. Existing snapshots were not changed.',
      )
      setQuantityDelta('')
      setCashAmount('')
      setSourceEventId('')
      setEvidenceRef('')
      await queryClient.invalidateQueries({ queryKey: ['portfolio-history'] })
      await queryClient.invalidateQueries({
        queryKey: ['portfolio-performance'],
      })
      await queryClient.invalidateQueries({
        queryKey: ['portfolio-history-reconciliation'],
      })
    },
  })

  const history = historyQuery.data
  const performance = performanceQuery.data
  const reconciliation = reconciliationQuery.data
  const events = history?.events ?? []

  return (
    <section className="mx-auto flex max-w-6xl flex-col gap-6 px-5 pb-12 sm:px-8">
      <header className="border-b border-slate-200 pb-5">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-700">
          Stage 3 · History and performance
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
          Historical portfolio analysis
        </h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Review dated position evidence and explicitly supplied investment
          events. Returns require complete USD snapshots at both selected dates.
          Event entries never change accepted holdings.
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
      {addEvent.error && (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900"
        >
          {addEvent.error.message}
        </p>
      )}
      {historyQuery.error && (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900"
        >
          {historyQuery.error.message}
        </p>
      )}

      <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">
          History and return period
        </h2>
        <div className="flex flex-wrap items-end gap-4">
          <label className="grid gap-1 text-sm font-medium">
            Account
            <select
              className="rounded-lg border border-slate-300 p-2"
              value={selectedAccountId}
              onChange={(event) => setAccountId(event.target.value)}
            >
              {accounts.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            From snapshot date
            <input
              className="rounded-lg border border-slate-300 p-2"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Through snapshot date
            <input
              className="rounded-lg border border-slate-300 p-2"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </label>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <article className="rounded-xl border border-slate-200 p-4">
            <h3 className="font-semibold">Chained Modified Dietz</h3>
            <p className="mt-2 text-2xl font-semibold">
              {percent(performance?.time_weighted_return ?? null)}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              Return fraction converted to percent ·{' '}
              {performance?.observation_count ?? 0} dated valuations ·{' '}
              {performance?.external_flow_count ?? 0} external flows
            </p>
          </article>
          <article className="rounded-xl border border-slate-200 p-4">
            <h3 className="font-semibold">Money-weighted XIRR</h3>
            <p className="mt-2 text-2xl font-semibold">
              {percent(performance?.money_weighted_return ?? null)}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              {performance?.money_weighted_status ??
                'Waiting for data sufficiency'}
            </p>
          </article>
        </div>
        {performance?.diagnostics.map((message) => (
          <p className="text-sm text-amber-900" key={message}>
            {message}
          </p>
        ))}
        <div className="rounded-xl bg-slate-50 p-4 text-sm">
          <p className="font-semibold">Snapshot reconciliation</p>
          <p className="mt-1">
            {reconciliation?.status ?? 'Loading'} ·{' '}
            {reconciliation?.gaps.join(' ')}
          </p>
          {reconciliation?.differences.map((row) => (
            <p className="mt-1 font-mono" key={row.security_id}>
              {row.ticker ?? row.security_id}: expected{' '}
              {decimalDisplay(row.expected_quantity, 4)}, snapshot{' '}
              {decimalDisplay(row.snapshot_quantity, 4)}, difference{' '}
              {decimalDisplay(row.difference, 4)}
            </p>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <caption className="sr-only">
              Dated accepted position snapshots
            </caption>
            <thead>
              <tr className="border-b text-slate-600">
                <th className="p-2">Date</th>
                <th className="p-2">Revision</th>
                <th className="p-2">Source</th>
                <th className="p-2">Status</th>
                <th className="p-2">Lines</th>
              </tr>
            </thead>
            <tbody>
              {history?.snapshots.map((row) => (
                <tr className="border-b" key={row.id}>
                  <td className="p-2">{row.effective_date}</td>
                  <td className="p-2">{row.revision}</td>
                  <td className="p-2">{row.source}</td>
                  <td className="p-2">{row.status}</td>
                  <td className="p-2">{row.line_count}</td>
                </tr>
              ))}
              {history?.snapshots.length === 0 && (
                <tr>
                  <td className="p-2 text-slate-600" colSpan={5}>
                    No accepted position snapshots in this period.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">
          Record supplied investment event
        </h2>
        <p className="text-sm text-slate-600">
          Sign convention: deposits are positive cash flows into the portfolio;
          withdrawals are negative. Transfers stay internal. Enter only
          source-backed quantities and dates.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="grid gap-1 text-sm">
            Event type
            <select
              className="rounded-lg border p-2"
              value={eventType}
              onChange={(event) =>
                setEventType(event.target.value as EventType)
              }
            >
              {(
                [
                  'deposit',
                  'withdrawal',
                  'buy',
                  'sell',
                  'dividend',
                  'fee',
                  'transfer_in',
                  'transfer_out',
                  'split',
                  'adjustment',
                  'other',
                ] as EventType[]
              ).map((value) => (
                <option key={value} value={value}>
                  {value.replace('_', ' ')}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Effective date
            <input
              className="rounded-lg border p-2"
              type="date"
              value={effectiveDate}
              onChange={(event) => setEffectiveDate(event.target.value)}
            />
          </label>
          {[
            'buy',
            'sell',
            'split',
            'adjustment',
            'transfer_in',
            'transfer_out',
          ].includes(eventType) && (
            <label className="grid gap-1 text-sm">
              Actual security
              <select
                className="rounded-lg border p-2"
                value={securityId}
                onChange={(event) => setSecurityId(event.target.value)}
              >
                <option value="">Select security</option>
                {(securitiesQuery.data ?? [])
                  .filter((item) => item.security_type !== 'cash')
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.display_ticker ?? item.name}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {[
            'buy',
            'sell',
            'split',
            'adjustment',
            'transfer_in',
            'transfer_out',
          ].includes(eventType) && (
            <label className="grid gap-1 text-sm">
              Quantity change
              <input
                className="rounded-lg border p-2"
                inputMode="decimal"
                value={quantityDelta}
                onChange={(event) => setQuantityDelta(event.target.value)}
              />
            </label>
          )}
          {['deposit', 'withdrawal'].includes(eventType) && (
            <label className="grid gap-1 text-sm">
              Cash position (optional)
              <select
                className="rounded-lg border p-2"
                value={securityId}
                onChange={(event) => setSecurityId(event.target.value)}
              >
                <option value="">Not tracked as a position</option>
                {(securitiesQuery.data ?? [])
                  .filter((item) => item.security_type === 'cash')
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · {item.currency}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {[
            'deposit',
            'withdrawal',
            'buy',
            'sell',
            'dividend',
            'fee',
            'transfer_in',
            'transfer_out',
          ].includes(eventType) && (
            <label className="grid gap-1 text-sm">
              Cash change
              <input
                className="rounded-lg border p-2"
                inputMode="decimal"
                value={cashAmount}
                onChange={(event) => setCashAmount(event.target.value)}
              />
            </label>
          )}
          <label className="grid gap-1 text-sm">
            Source event ID
            <input
              className="rounded-lg border p-2"
              value={sourceEventId}
              onChange={(event) => setSourceEventId(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Evidence reference
            <input
              className="rounded-lg border p-2"
              value={evidenceRef}
              onChange={(event) => setEvidenceRef(event.target.value)}
              placeholder="Statement page / line"
            />
          </label>
        </div>
        <button
          className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50"
          type="button"
          disabled={addEvent.isPending || !selectedAccountId}
          onClick={() => addEvent.mutate()}
        >
          {addEvent.isPending ? 'Saving…' : 'Save source-backed event'}
        </button>
      </section>

      <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">
          Explicit investment events
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <caption className="sr-only">
              Explicit investment events from sources
            </caption>
            <thead>
              <tr className="border-b text-slate-600">
                <th className="p-2">Date</th>
                <th className="p-2">Type</th>
                <th className="p-2">Quantity</th>
                <th className="p-2">Cash</th>
                <th className="p-2">Source</th>
                <th className="p-2">Quality</th>
              </tr>
            </thead>
            <tbody>
              {events.map((row) => (
                <tr className="border-b" key={row.id}>
                  <td className="p-2">{row.effective_date}</td>
                  <td className="p-2">{row.event_type}</td>
                  <td className="p-2 font-mono">{row.quantity_delta ?? '—'}</td>
                  <td className="p-2 font-mono">
                    {row.cash_amount
                      ? `${row.currency} ${row.cash_amount}`
                      : '—'}
                  </td>
                  <td className="p-2">
                    {row.source_label}
                    {row.evidence_ref && (
                      <span className="block text-xs text-slate-500">
                        {row.evidence_ref}
                      </span>
                    )}
                  </td>
                  <td className="p-2">
                    {row.quality_status} · {row.review_status}
                  </td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td className="p-2 text-slate-600" colSpan={6}>
                    No supplied investment events in this period.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  )
}
