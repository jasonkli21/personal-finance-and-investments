import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { readJsonResponse } from './api/response'
import type { components } from './api/schema'
import { ShoppingProjectSelect } from './ShoppingProjectSelect'

type Budget = components['schemas']['MonthlyDiscretionaryBudgetRead']
type Status = components['schemas']['SourceTaskStatus']
type GrantChoices = { choices: { id: string; category_label: string }[] }
type ProjectChoices = components['schemas']['DelegatedTargetChoicesResult']

async function request<T>(
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<T> {
  return readJsonResponse<T>(
    await fetch(`/api${path}`, {
      method,
      headers:
        body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
    'The Shopping task could not be completed. Refresh authentication or check its result.',
  )
}

export default function ShoppingBudgetTask() {
  const capabilities = useQuery({
    queryKey: ['shopping-task-capabilities'],
    queryFn: () =>
      request<{ enabled: boolean; recent_authentication: boolean }>(
        '/v1/finance/shopping-tasks/capabilities',
      ),
    retry: false,
  })
  if (!capabilities.data?.enabled) return null
  if (!capabilities.data.recent_authentication)
    return (
      <section
        aria-label="Shopping budget task"
        className="rounded-2xl border p-5"
      >
        <h2 className="text-lg font-semibold">Share a budget with Shopping</h2>
        <p>
          Recent verified authentication is required to review and apply a
          Shopping task.
        </p>
        <a href="/api/v1/auth/login">Authenticate again</a>
      </section>
    )
  return <BudgetTaskForm />
}

function BudgetTaskForm() {
  const date = new Date()
  const [period, setPeriod] = useState(
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`,
  )
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [consent, setConsent] = useState(false)
  const [budget, setBudget] = useState<Budget | null>(null)
  const [choice, setChoice] = useState('')
  const [projectId, setProjectId] = useState('')
  const [status, setStatus] = useState<Status | null>(null)
  const [created, setCreated] = useState(false)
  const [clientUncertain, setClientUncertain] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [commandId, setCommandId] = useState(() => crypto.randomUUID())
  const [confirmationId, setConfirmationId] = useState(() =>
    crypto.randomUUID(),
  )
  const grants = useQuery({
    queryKey: ['shopping-task-grants'],
    queryFn: () => request<GrantChoices>('/v1/finance/shopping-tasks/choices'),
    retry: false,
  })
  const projects = useQuery({
    queryKey: ['shopping-task-projects'],
    queryFn: () => request<ProjectChoices>('/v1/finance/shopping-tasks/projects'),
    retry: false,
  })
  const selectedProject = projects.data?.choices.find(
    (item) => item.project_id === projectId,
  )
  const base = `/v1/finance/shopping-tasks/commands/${commandId}`
  async function run(action: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : 'The request failed. Check the original task before trying again.',
      )
    } finally {
      setBusy(false)
    }
  }
  function reset() {
    setCommandId(crypto.randomUUID())
    setConfirmationId(crypto.randomUUID())
    setCreated(false)
    setStatus(null)
    setError('')
    setClientUncertain(false)
  }
  return (
    <section
      aria-label="Shopping budget task"
      className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5"
    >
      <h2 className="text-lg font-semibold">Share a budget with Shopping</h2>
      <p>
        Finance owns this monthly budget. Review the Shopping preview before
        applying it. A grant in Personal AI and a linked Shopping account are
        required.
      </p>
      <fieldset disabled={busy || created} className="flex flex-wrap gap-3">
        <label>
          Month{' '}
          <input
            type="month"
            value={period}
            onChange={(e) => {
              setPeriod(e.target.value)
              setBudget(null)
            }}
          />
        </label>
        <label>
          Amount{' '}
          <input
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="50.00"
          />
        </label>
        <label>
          Currency{' '}
          <input
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            maxLength={3}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          Allow Shopping to use this budget
        </label>
        <button
          type="button"
          onClick={() =>
            void run(async () => {
              const loaded = await request<Budget>(
                `/v1/finance/discretionary-budgets/${period}`,
              )
              setBudget(loaded)
              setAmount(loaded.amount)
              setCurrency(loaded.currency)
              setConsent(loaded.share_with_shopping)
            })
          }
        >
          Load budget
        </button>
        <button
          type="button"
          onClick={() =>
            void run(async () => {
              const saved = await request<Budget>(
                `/v1/finance/discretionary-budgets/${period}`,
                'PUT',
                {
                  expected_revision: budget?.revision ?? 0,
                  amount,
                  currency,
                  share_with_shopping: consent,
                },
              )
              setBudget(saved)
            })
          }
        >
          Save Finance budget
        </button>
      </fieldset>
      <fieldset disabled={busy || created} className="flex flex-wrap gap-3">
        <label>
          Grant{' '}
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Select an explicitly granted source</option>
            {(grants.data?.choices ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.category_label}
              </option>
            ))}
          </select>
        </label>
        <ShoppingProjectSelect
          choices={projects.data?.choices ?? []}
          selectedId={projectId}
          onSelect={setProjectId}
        />
      </fieldset>
      {grants.isError && (
        <p role="alert">
          Grants are unavailable. Check Personal AI authentication and
          permissions.
        </p>
      )}
      {projects.isError && (
        <p role="alert">
          Shopping projects are unavailable. Check Personal AI authentication
          and linked Shopping access.
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={
            busy ||
            !budget?.share_with_shopping ||
            !choice ||
            !selectedProject ||
            (status !== null && status.state !== 'proposed')
          }
          onClick={() =>
            void run(async () => {
              if (!budget) return
              if (!selectedProject) return
              await request('/v1/finance/shopping-tasks/commands', 'POST', {
                command_id: commandId,
                period,
                expected_budget_revision: budget.revision,
                context_choice_id: choice,
                shopping_project_id: selectedProject.project_id,
                expected_project_revision: selectedProject.revision,
              })
              setCreated(true)
              const proposed = await request<Status>(`${base}/submit`, 'POST')
              setStatus(proposed)
              if (proposed.state === 'proposed')
                setStatus(await request<Status>(`${base}/validate`, 'POST'))
            })
          }
        >
          Review Shopping change
        </button>
        {status &&
          ['validated', 'confirmed'].includes(status.state) &&
          status.apply_available &&
          !clientUncertain && (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const confirmation = {
                    confirmation_id: status?.confirmation_id ?? confirmationId,
                    binding: status.binding,
                  }
                  setStatus(
                    await request<Status>(
                      `${base}/confirm`,
                      'POST',
                      confirmation,
                    ),
                  )
                  setClientUncertain(true)
                  setStatus(
                    await request<Status>(
                      `${base}/apply`,
                      'POST',
                      confirmation,
                    ),
                  )
                  setClientUncertain(false)
                })
              }
            >
              Confirm and apply this change
            </button>
          )}
        {created && (
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const current = await request<Status>(base)
                const result = [
                  'executing',
                  'reconciling',
                  'uncertain',
                ].includes(current.state)
                  ? await request<Status>(`${base}/reconcile`, 'POST')
                  : current
                setStatus(result)
                setClientUncertain(false)
              })
            }
          >
            Check original result
          </button>
        )}
        <button
          type="button"
          disabled={
            busy ||
            clientUncertain ||
            ['executing', 'reconciling', 'uncertain'].includes(
              status?.state ?? '',
            )
          }
          onClick={reset}
        >
          Start a new task
        </button>
      </div>
      {clientUncertain && (
        <p role="alert">
          The apply acknowledgement is unavailable. Check the original result
          before starting another task.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {status && (
        <div role="status">
          <p>Task: {status.state}</p>
          {status.preview && <p>{status.preview}</p>}
          {status.state === 'uncertain' && (
            <p>
              The destination may have applied this change. Check the original
              result; do not create a replacement task.
            </p>
          )}
          {status.outcome_code && <p>Result: {status.outcome_code}</p>}
          {status.domain_version && (
            <p>Shopping project revision: {status.domain_version}</p>
          )}
        </div>
      )}
    </section>
  )
}
