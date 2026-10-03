import AuthenticationGate from './AuthenticationGate'
import { localDate } from './local-date'
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  createAccount,
  fetchAccounts,
  fetchPositions,
  replacePositions,
  resolveSecurity,
  updateAccount,
} from './api/client'
import type { components } from './api/schema'
import { captureDraftBaseRevision } from './position-draft'
import { startReadinessPolling, type ApiStatus } from './readiness'
import StageOneWorkspace from './StageOneWorkspace'
import FundWorkspace from './FundWorkspace'
import ReportWorkspace from './ReportWorkspace'
import SpendingWorkspace from './SpendingWorkspace'
import FinanceWorkspace from './FinanceWorkspace'
import HistoryPerformanceWorkspace from './HistoryPerformanceWorkspace'
import TaxLotWorkspace from './TaxLotWorkspace'
import PortfolioScenarioWorkspace from './PortfolioScenarioWorkspace'
import PlanningWorkspace from './PlanningWorkspace'
import ResearchWorkspace from './ResearchWorkspace'

type Security = components['schemas']['SecurityRead']
type PositionLine = components['schemas']['PositionLineRead']
type DraftHolding = {
  rowKey: string
  security: Security | null
  search: string
  quantity: string
  price: string
}
type AccountDraft = {
  name: string
  account_type: string
  base_currency: string
}

const EMPTY_ACCOUNTS: Awaited<ReturnType<typeof fetchAccounts>> = []

const emptyHolding = (): DraftHolding => ({
  rowKey: crypto.randomUUID(),
  security: null,
  search: '',
  quantity: '',
  price: '',
})

function draftFromPosition(position: PositionLine): DraftHolding {
  return {
    rowKey: position.id,
    security: position.security,
    search: position.security.display_ticker ?? position.security.name,
    quantity: position.quantity,
    price: position.reported_price ?? '',
  }
}

function HoldingEditor({
  holding,
  disabled,
  onChange,
  onRemove,
}: {
  holding: DraftHolding
  disabled: boolean
  onChange: (next: DraftHolding) => void
  onRemove: () => void
}) {
  const lookup = useQuery({
    queryKey: ['security-resolution', holding.search.trim()],
    queryFn: () => resolveSecurity(holding.search.trim()),
    enabled: holding.security === null && holding.search.trim().length >= 2,
    staleTime: 30_000,
  })

  return (
    <fieldset className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-[minmax(0,2fr)_1fr_1fr_auto]">
      <legend className="sr-only">Holding</legend>
      <div className="min-w-0">
        <label
          className="mb-1 block text-sm font-medium text-slate-700"
          htmlFor={`security-${holding.rowKey}`}
        >
          Security
        </label>
        <input
          id={`security-${holding.rowKey}`}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100"
          value={holding.search}
          placeholder="Ticker or name"
          disabled={disabled}
          onChange={(event) =>
            onChange({
              ...holding,
              search: event.target.value,
              security: null,
            })
          }
        />
        {holding.security ? (
          <p className="mt-2 text-sm text-emerald-800" role="status">
            Selected {holding.security.display_ticker ?? holding.security.name}{' '}
            · {holding.security.currency}
          </p>
        ) : holding.search.trim().length >= 2 ? (
          <div className="mt-2 space-y-1" aria-live="polite">
            {lookup.isPending ? (
              <p className="text-sm text-slate-500">Searching local catalog…</p>
            ) : lookup.error ? (
              <p className="text-sm text-rose-700">
                Catalog search is unavailable.
              </p>
            ) : lookup.data?.matches.length ? (
              lookup.data.matches.map((match) => (
                <button
                  className="block w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  key={match.id}
                  type="button"
                  onClick={() =>
                    onChange({
                      ...holding,
                      security: match,
                      search: match.display_ticker ?? match.name,
                    })
                  }
                >
                  <span className="font-semibold">
                    {match.display_ticker ?? match.name}
                  </span>{' '}
                  <span className="text-slate-600">{match.name}</span>
                </button>
              ))
            ) : (
              <p className="text-sm text-slate-500">
                No local match. Add a reviewed security in the local catalog
                below before entering this position.
              </p>
            )}
          </div>
        ) : (
          <p className="mt-2 text-xs text-slate-500">
            Search uses the local catalog and works offline.
          </p>
        )}
      </div>
      <div>
        <label
          className="mb-1 block text-sm font-medium text-slate-700"
          htmlFor={`quantity-${holding.rowKey}`}
        >
          Quantity / cash balance
        </label>
        <input
          id={`quantity-${holding.rowKey}`}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100"
          inputMode="decimal"
          value={holding.quantity}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...holding, quantity: event.target.value })
          }
        />
      </div>
      <div>
        <label
          className="mb-1 block text-sm font-medium text-slate-700"
          htmlFor={`price-${holding.rowKey}`}
        >
          Manual price
        </label>
        <input
          id={`price-${holding.rowKey}`}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100"
          inputMode="decimal"
          placeholder={
            holding.security?.security_type === 'cash'
              ? 'Cash balance'
              : 'Optional'
          }
          value={holding.price}
          onChange={(event) =>
            onChange({ ...holding, price: event.target.value })
          }
          disabled={disabled || holding.security?.security_type === 'cash'}
        />
        <p className="mt-1 text-xs text-slate-500">
          {holding.security?.security_type === 'cash'
            ? 'Cash is valued at its explicit balance.'
            : 'Leave blank to show value unavailable.'}
        </p>
      </div>
      <div className="flex items-end">
        <button
          aria-label="Remove holding from draft"
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          type="button"
          onClick={onRemove}
          disabled={disabled}
        >
          Remove
        </button>
      </div>
    </fieldset>
  )
}

function FinanceApp({
  authenticated,
  onLogout,
}: {
  authenticated: boolean
  onLogout: () => void
}) {
  const queryClient = useQueryClient()
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [newAccountName, setNewAccountName] = useState('')
  const [newAccountType, setNewAccountType] = useState('taxable')
  const [newAccountCurrency, setNewAccountCurrency] = useState('USD')
  const [accountDrafts, setAccountDrafts] = useState<
    Record<string, AccountDraft>
  >({})
  const [effectiveDates, setEffectiveDates] = useState<Record<string, string>>(
    {},
  )
  const [holdingDrafts, setHoldingDrafts] = useState<
    Record<string, DraftHolding[]>
  >({})
  const [holdingBaseRevisions, setHoldingBaseRevisions] = useState<
    Record<string, number>
  >({})
  const [positionConflicts, setPositionConflicts] = useState<
    Record<string, boolean>
  >({})
  const [notice, setNotice] = useState('')
  const [formError, setFormError] = useState('')

  useEffect(() => startReadinessPolling({ onStatus: setApiStatus }), [])

  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const accounts = accountsQuery.data ?? EMPTY_ACCOUNTS
  const selectedAccount = accounts.find(
    (account) => account.id === selectedAccountId,
  )
  const positionsQuery = useQuery({
    queryKey: ['positions', selectedAccountId],
    queryFn: () => fetchPositions(selectedAccountId),
    enabled: selectedAccountId.length > 0,
  })
  const currentSnapshot = positionsQuery.data?.snapshot
  const selectedAccountDraft = selectedAccount
    ? (accountDrafts[selectedAccount.id] ?? {
        name: selectedAccount.name,
        account_type: selectedAccount.account_type,
        base_currency: selectedAccount.base_currency,
      })
    : undefined
  const effectiveDate = selectedAccount
    ? (effectiveDates[selectedAccount.id] ??
      currentSnapshot?.effective_date ??
      localDate())
    : localDate()
  const holdings = selectedAccount
    ? (holdingDrafts[selectedAccount.id] ??
      currentSnapshot?.positions.map(draftFromPosition) ??
      [])
    : []

  function capturePositionBaseRevision(accountId: string) {
    const currentRevision = positionsQuery.data?.current_revision ?? 0
    setHoldingBaseRevisions((current) =>
      current[accountId] === undefined
        ? {
            ...current,
            [accountId]: captureDraftBaseRevision(
              current[accountId],
              currentRevision,
            ),
          }
        : current,
    )
  }

  function updateAccountDraft(patch: Partial<AccountDraft>) {
    if (!selectedAccount || !selectedAccountDraft) return
    setAccountDrafts((current) => ({
      ...current,
      [selectedAccount.id]: { ...selectedAccountDraft, ...patch },
    }))
  }

  function updateHoldings(
    transform: (current: DraftHolding[]) => DraftHolding[],
  ) {
    if (!selectedAccount) return
    capturePositionBaseRevision(selectedAccount.id)
    setHoldingDrafts((current) => ({
      ...current,
      [selectedAccount.id]: transform(
        current[selectedAccount.id] ??
          currentSnapshot?.positions.map(draftFromPosition) ??
          [],
      ),
    }))
  }

  function updateEffectiveDate(value: string) {
    if (!selectedAccount) return
    capturePositionBaseRevision(selectedAccount.id)
    setEffectiveDates((current) => ({
      ...current,
      [selectedAccount.id]: value,
    }))
  }

  const createAccountMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: async (account) => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setSelectedAccountId(account.id)
      setAccountDrafts((current) => withoutKey(current, account.id))
      setEffectiveDates((current) => withoutKey(current, account.id))
      setHoldingDrafts((current) => withoutKey(current, account.id))
      setHoldingBaseRevisions((current) => withoutKey(current, account.id))
      setNewAccountName('')
      setNotice('Account created.')
      setFormError('')
    },
    onError: (error) => setFormError(messageFor(error)),
  })

  const updateAccountMutation = useMutation({
    mutationFn: ({
      id,
      input,
    }: {
      id: string
      input: {
        name?: string
        account_type?: string
        base_currency?: string
        active?: boolean
      }
    }) => updateAccount(id, input),
    onSuccess: async (account) => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setAccountDrafts((current) => withoutKey(current, account.id))
      setNotice(account.active ? 'Account details saved.' : 'Account archived.')
      setFormError('')
    },
    onError: (error) => setFormError(messageFor(error)),
  })

  const savePositionsMutation = useMutation({
    mutationFn: () => {
      if (!selectedAccount || !positionsQuery.data) {
        throw new Error(
          'Choose an account and wait for its current positions to load.',
        )
      }
      if (!selectedAccountDraft) throw new Error('Select an account.')
      if (!effectiveDate) throw new Error('Enter the position effective date.')
      if (
        holdings.some(
          (holding) => !holding.security || !holding.quantity.trim(),
        )
      ) {
        throw new Error(
          'Choose a local security and enter a quantity for every row.',
        )
      }
      return replacePositions(selectedAccount.id, {
        expected_revision:
          holdingBaseRevisions[selectedAccount.id] ??
          positionsQuery.data.current_revision,
        effective_date: effectiveDate,
        positions: holdings.map((holding) => ({
          security_id: holding.security!.id,
          quantity: holding.quantity.trim(),
          reported_price: holding.price.trim() || null,
          currency: holding.security!.currency,
        })),
      })
    },
    onSuccess: async (snapshot) => {
      queryClient.setQueryData(['positions', selectedAccountId], {
        snapshot,
        current_revision: snapshot.revision,
      })
      setEffectiveDates((current) => withoutKey(current, selectedAccountId))
      setHoldingDrafts((current) => withoutKey(current, selectedAccountId))
      setHoldingBaseRevisions((current) =>
        withoutKey(current, selectedAccountId),
      )
      setPositionConflicts((current) => withoutKey(current, selectedAccountId))
      setNotice(
        `Saved revision ${snapshot.revision}. Values are dated ${snapshot.effective_date}.`,
      )
      setFormError('')
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setPositionConflicts((current) => ({
          ...current,
          [selectedAccountId]: true,
        }))
        await queryClient.invalidateQueries({
          queryKey: ['positions', selectedAccountId],
        })
        setFormError(
          'The saved revision changed. Your draft is preserved but cannot be saved against the newer revision. Reload latest to discard this draft.',
        )
        return
      }
      setFormError(messageFor(error))
    },
  })

  function editHolding(rowKey: string, next: DraftHolding) {
    updateHoldings((current) =>
      current.map((row) => (row.rowKey === rowKey ? next : row)),
    )
    setNotice('')
    setFormError('')
  }

  function removeHolding(rowKey: string) {
    updateHoldings((current) => current.filter((row) => row.rowKey !== rowKey))
    setNotice('')
    setFormError('')
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-5 py-10 sm:px-8">
      <header className="flex flex-col gap-4 border-b border-slate-200 pb-7 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">
            {authenticated
              ? 'Private portfolio workspace'
              : 'Local portfolio workspace'}
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
            Accounts and owned positions
          </h1>
          <p className="mt-2 max-w-2xl text-slate-600">
            Enter a dated manual snapshot. It records what you own and does not
            create trade or tax lot history.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {authenticated && (
            <button
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="button"
              onClick={onLogout}
            >
              Sign out
            </button>
          )}
          <p
            className="rounded-full bg-slate-100 px-4 py-2 text-sm text-slate-700"
            role="status"
          >
            API and database: {apiStatus}
          </p>
        </div>
      </header>

      {notice && (
        <p
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
          role="status"
        >
          {notice}
        </p>
      )}
      {formError && (
        <p
          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
          role="alert"
        >
          {formError}
        </p>
      )}

      <section className="grid gap-8 lg:grid-cols-[minmax(16rem,0.8fr)_minmax(0,1.6fr)]">
        <aside className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Accounts</h2>
            <label
              className="mt-4 block text-sm font-medium text-slate-700"
              htmlFor="account-select"
            >
              Select account
            </label>
            <select
              id="account-select"
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
              value={selectedAccountId}
              disabled={savePositionsMutation.isPending}
              onChange={(event) => {
                const nextAccountId = event.target.value
                setSelectedAccountId(nextAccountId)
                setAccountDrafts((current) =>
                  withoutKey(current, nextAccountId),
                )
                setEffectiveDates((current) =>
                  withoutKey(current, nextAccountId),
                )
                setHoldingDrafts((current) =>
                  withoutKey(current, nextAccountId),
                )
                setHoldingBaseRevisions((current) =>
                  withoutKey(current, nextAccountId),
                )
                setPositionConflicts((current) =>
                  withoutKey(current, nextAccountId),
                )
                setNotice('')
                setFormError('')
              }}
            >
              <option value="">Choose an account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                  {account.source_type === 'demo' ? ' (SYNTHETIC DEMO)' : ''}
                  {account.active ? '' : ' (archived)'}
                </option>
              ))}
            </select>
            {accountsQuery.isError && (
              <p className="mt-2 text-sm text-rose-700">
                Accounts could not be loaded.
              </p>
            )}
            {selectedAccount && (
              <>
                {selectedAccount.source_type === 'demo' && (
                  <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-amber-900">
                    Synthetic demo account · fictional data only
                  </p>
                )}
                <form
                  className="mt-5 border-t border-slate-100 pt-4"
                  onSubmit={(event) => {
                    event.preventDefault()
                    if (selectedAccountDraft?.name.trim()) {
                      updateAccountMutation.mutate({
                        id: selectedAccount.id,
                        input: {
                          name: selectedAccountDraft.name.trim(),
                          account_type: selectedAccountDraft.account_type,
                          base_currency: selectedAccountDraft.base_currency,
                        },
                      })
                    }
                  }}
                >
                  <label
                    className="block text-sm font-medium text-slate-700"
                    htmlFor="account-name"
                  >
                    Account name
                  </label>
                  <input
                    id="account-name"
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                    value={selectedAccountDraft?.name ?? ''}
                    onChange={(event) =>
                      updateAccountDraft({ name: event.target.value })
                    }
                  />
                  <label
                    className="mt-3 block text-sm font-medium text-slate-700"
                    htmlFor="edit-account-type"
                  >
                    Account type
                  </label>
                  <select
                    id="edit-account-type"
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                    value={selectedAccountDraft?.account_type ?? 'taxable'}
                    onChange={(event) =>
                      updateAccountDraft({ account_type: event.target.value })
                    }
                  >
                    <option value="taxable">Taxable brokerage</option>
                    <option value="ira">Traditional IRA</option>
                    <option value="roth_ira">Roth IRA</option>
                    <option value="401k">401(k)</option>
                    <option value="hsa">HSA</option>
                    <option value="other">Other</option>
                  </select>
                  <label
                    className="mt-3 block text-sm font-medium text-slate-700"
                    htmlFor="edit-account-currency"
                  >
                    Base currency
                  </label>
                  <select
                    id="edit-account-currency"
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                    value={selectedAccountDraft?.base_currency ?? 'USD'}
                    onChange={(event) =>
                      updateAccountDraft({ base_currency: event.target.value })
                    }
                  >
                    {['USD', 'CAD', 'EUR', 'GBP', 'JPY'].map((currency) => (
                      <option key={currency} value={currency}>
                        {currency}
                      </option>
                    ))}
                  </select>
                  <button
                    className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    type="submit"
                    disabled={
                      !selectedAccount.active || updateAccountMutation.isPending
                    }
                  >
                    Save account details
                  </button>
                  {selectedAccount.active && (
                    <button
                      className="mt-2 w-full rounded-lg px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                      type="button"
                      disabled={updateAccountMutation.isPending}
                      onClick={() =>
                        updateAccountMutation.mutate({
                          id: selectedAccount.id,
                          input: { active: false },
                        })
                      }
                    >
                      Archive account
                    </button>
                  )}
                </form>
              </>
            )}
          </div>

          <form
            className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
            onSubmit={(event) => {
              event.preventDefault()
              if (!newAccountName.trim()) return
              createAccountMutation.mutate({
                name: newAccountName.trim(),
                account_type: newAccountType,
                base_currency: newAccountCurrency,
              })
            }}
          >
            <h2 className="text-lg font-semibold text-slate-900">
              Add an account
            </h2>
            <label
              className="mt-4 block text-sm font-medium text-slate-700"
              htmlFor="new-account-name"
            >
              Name
            </label>
            <input
              id="new-account-name"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              maxLength={200}
              value={newAccountName}
              onChange={(event) => setNewAccountName(event.target.value)}
              required
            />
            <label
              className="mt-3 block text-sm font-medium text-slate-700"
              htmlFor="new-account-type"
            >
              Account type
            </label>
            <select
              id="new-account-type"
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
              value={newAccountType}
              onChange={(event) => setNewAccountType(event.target.value)}
            >
              <option value="taxable">Taxable brokerage</option>
              <option value="ira">Traditional IRA</option>
              <option value="roth_ira">Roth IRA</option>
              <option value="401k">401(k)</option>
              <option value="hsa">HSA</option>
              <option value="other">Other</option>
            </select>
            <label
              className="mt-3 block text-sm font-medium text-slate-700"
              htmlFor="new-account-currency"
            >
              Base currency
            </label>
            <select
              id="new-account-currency"
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
              value={newAccountCurrency}
              onChange={(event) => setNewAccountCurrency(event.target.value)}
            >
              {['USD', 'CAD', 'EUR', 'GBP', 'JPY'].map((currency) => (
                <option key={currency} value={currency}>
                  {currency}
                </option>
              ))}
            </select>
            <p className="mt-2 text-xs text-slate-500">
              This labels the account. No currency conversion is performed.
            </p>
            <button
              className="mt-4 w-full rounded-lg bg-blue-700 px-4 py-2.5 font-semibold text-white hover:bg-blue-800 disabled:opacity-50"
              type="submit"
              disabled={createAccountMutation.isPending}
            >
              {createAccountMutation.isPending ? 'Creating…' : 'Create account'}
            </button>
          </form>
        </aside>

        <section className="space-y-5" aria-labelledby="positions-heading">
          <div>
            <h2
              id="positions-heading"
              className="text-xl font-semibold text-slate-900"
            >
              Manual position snapshot
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Prices use the snapshot date shown here. Unpriced securities
              remain visible with unavailable value.
            </p>
          </div>

          {!selectedAccountId ? (
            <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">
              Select or create an account to enter positions.
            </div>
          ) : positionsQuery.isPending ? (
            <p className="rounded-xl bg-white p-5 text-slate-600" role="status">
              Loading saved positions…
            </p>
          ) : positionsQuery.isError ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-rose-900">
              Saved positions could not be loaded. Retry after the API is
              available.
            </div>
          ) : (
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault()
                savePositionsMutation.mutate()
              }}
            >
              {positionsQuery.data?.snapshot && (
                <p className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-900">
                  {holdingBaseRevisions[selectedAccountId] !== undefined
                    ? `Draft based on revision ${holdingBaseRevisions[selectedAccountId]}; server revision ${positionsQuery.data.current_revision}.`
                    : `Loaded revision ${positionsQuery.data.current_revision};`}{' '}
                  source: manual; as of {currentSnapshot?.effective_date}.
                </p>
              )}
              {positionConflicts[selectedAccountId] && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
                  <span>
                    This draft is stale. Review and reload the latest saved
                    positions before making another change.
                  </span>
                  <button
                    className="rounded-lg border border-amber-700 px-3 py-1.5 font-semibold hover:bg-amber-100"
                    type="button"
                    onClick={async () => {
                      await queryClient.invalidateQueries({
                        queryKey: ['positions', selectedAccountId],
                      })
                      setEffectiveDates((current) =>
                        withoutKey(current, selectedAccountId),
                      )
                      setHoldingDrafts((current) =>
                        withoutKey(current, selectedAccountId),
                      )
                      setHoldingBaseRevisions((current) =>
                        withoutKey(current, selectedAccountId),
                      )
                      setPositionConflicts((current) =>
                        withoutKey(current, selectedAccountId),
                      )
                      setFormError('')
                    }}
                  >
                    Discard draft and reload latest
                  </button>
                </div>
              )}
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <label
                  className="block text-sm font-medium text-slate-700"
                  htmlFor="effective-date"
                >
                  Position and manual price as of
                </label>
                <input
                  id="effective-date"
                  className="mt-1 rounded-lg border border-slate-300 px-3 py-2"
                  type="date"
                  value={effectiveDate}
                  onChange={(event) => updateEffectiveDate(event.target.value)}
                  disabled={savePositionsMutation.isPending}
                  required
                />
              </div>

              {holdings.map((holding) => (
                <HoldingEditor
                  key={holding.rowKey}
                  holding={holding}
                  disabled={savePositionsMutation.isPending}
                  onChange={(next) => editHolding(holding.rowKey, next)}
                  onRemove={() => removeHolding(holding.rowKey)}
                />
              ))}

              {holdings.length === 0 && (
                <p className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-600">
                  This snapshot has no position lines. Saving an empty list
                  replaces it with an empty snapshot.
                </p>
              )}

              <div className="flex flex-wrap gap-3">
                <button
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 font-semibold text-slate-700 hover:bg-slate-50"
                  type="button"
                  onClick={() =>
                    updateHoldings((current) => [...current, emptyHolding()])
                  }
                  disabled={
                    !selectedAccount?.active || savePositionsMutation.isPending
                  }
                >
                  Add holding
                </button>
                <button
                  className="rounded-lg bg-blue-700 px-5 py-2.5 font-semibold text-white hover:bg-blue-800 disabled:opacity-50"
                  type="submit"
                  disabled={
                    !selectedAccount?.active ||
                    savePositionsMutation.isPending ||
                    positionConflicts[selectedAccountId] ||
                    !positionsQuery.data
                  }
                >
                  {savePositionsMutation.isPending
                    ? 'Saving…'
                    : 'Save snapshot'}
                </button>
              </div>

              {!selectedAccount?.active && (
                <p className="text-sm text-amber-800">
                  This account is archived and cannot receive edits.
                </p>
              )}
            </form>
          )}

          {positionsQuery.data?.snapshot && (
            <section
              className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
              aria-label="Persisted owned positions"
            >
              <div className="border-b border-slate-200 px-5 py-4">
                <h3 className="font-semibold text-slate-900">
                  Persisted owned positions
                </h3>
                <p className="mt-1 text-xs text-slate-500">
                  Manual source · effective{' '}
                  {positionsQuery.data.snapshot.effective_date} · revision{' '}
                  {positionsQuery.data.snapshot.revision}
                </p>
              </div>
              {positionsQuery.data.snapshot.positions.length === 0 ? (
                <p className="p-5 text-sm text-slate-600">
                  No position lines in this revision.
                </p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {positionsQuery.data.snapshot.positions.map((position) => (
                    <li
                      className="grid gap-1 px-5 py-4 sm:grid-cols-[1fr_auto]"
                      key={position.id}
                    >
                      <div>
                        <p className="font-medium text-slate-900">
                          {position.security.display_ticker ??
                            position.security.name}
                        </p>
                        <p className="text-sm text-slate-600">
                          {position.quantity}{' '}
                          {position.security.security_type === 'cash'
                            ? 'balance'
                            : 'shares'}{' '}
                          · {position.source} · {position.quality_status}
                        </p>
                      </div>
                      <div className="text-left sm:text-right">
                        <p className="font-medium text-slate-900">
                          {position.reported_value === null
                            ? 'Value unavailable'
                            : `${position.currency} ${position.reported_value}`}
                        </p>
                        {position.reported_price !== null && (
                          <p className="text-xs text-slate-500">
                            Manual price {position.reported_price} as of{' '}
                            {position.price_as_of}
                          </p>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </section>
      </section>
      <ReportWorkspace />
      <FundWorkspace />
      <StageOneWorkspace
        accountId={selectedAccountId}
        effectiveDate={effectiveDate}
        expectedRevision={positionsQuery.data?.current_revision ?? 0}
        onPublished={async (publishedAccountId) => {
          if (publishedAccountId) {
            await queryClient.invalidateQueries({
              queryKey: ['positions', publishedAccountId],
            })
            setEffectiveDates((current) =>
              withoutKey(current, publishedAccountId),
            )
            setHoldingDrafts((current) =>
              withoutKey(current, publishedAccountId),
            )
            setHoldingBaseRevisions((current) =>
              withoutKey(current, publishedAccountId),
            )
          }
        }}
      />
      <SpendingWorkspace />
      <FinanceWorkspace />
      <HistoryPerformanceWorkspace />
      <TaxLotWorkspace />
      <PortfolioScenarioWorkspace />
      <PlanningWorkspace />
      <ResearchWorkspace />
    </main>
  )
}

export default function App() {
  return <AuthenticationGate workspace={FinanceApp} />
}

function messageFor(error: unknown): string {
  if (error instanceof Error) return error.message
  return 'The request could not be completed.'
}

function withoutKey<T>(
  record: Record<string, T>,
  key: string,
): Record<string, T> {
  const next = { ...record }
  delete next[key]
  return next
}
