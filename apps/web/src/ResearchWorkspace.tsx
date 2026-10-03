import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  ApiError,
  compareResearchFacts,
  createReportedResearchFact,
  createResearchThesisNote,
  createResearchRun,
  fetchIssuers,
  fetchResearchCompany,
  fetchResearchThesisNotes,
  fetchResearchWatchlistState,
  registerResearchDocument,
  updateResearchWatchlist,
} from './api/client'
import type { components } from './api/schema'

type Observation = components['schemas']['ResearchFactObservation']
type FactPeriod = 'duration' | 'instant'
type FiscalPeriod = 'Q1' | 'Q2' | 'Q3' | 'Q4' | 'H1' | 'H2' | 'FY'

const inputClass =
  'w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100'

function message(error: unknown, fallback: string) {
  if (error instanceof ApiError) return error.message
  return fallback
}

export default function ResearchWorkspace() {
  const queryClient = useQueryClient()
  const [issuerId, setIssuerId] = useState('')
  const issuers = useQuery({ queryKey: ['issuers'], queryFn: fetchIssuers })
  const company = useQuery({
    queryKey: ['research-company', issuerId],
    queryFn: () => fetchResearchCompany(issuerId),
    enabled: issuerId.length > 0,
  })
  const documents = company.data?.documents ?? []
  const observations = company.data?.facts ?? []
  const [documentDraft, setDocumentDraft] = useState({
    cik: '',
    accession_number: '',
    form_type: '10-K',
    title: '',
    source_url: '',
    filing_date: '',
    period_start: '',
    period_end: '',
  })
  const [factDraft, setFactDraft] = useState({
    document_id: '',
    taxonomy: 'us-gaap',
    concept: '',
    raw_value: '',
    normalized_value: '',
    unit: 'USD',
    currency: 'USD',
    period_kind: 'duration' as FactPeriod,
    period_start: '',
    period_end: '',
    instant: '',
    fiscal_year: '',
    fiscal_period: '' as FiscalPeriod | '',
  })
  const [priorFactId, setPriorFactId] = useState('')
  const [currentFactId, setCurrentFactId] = useState('')
  const [selectedFactIds, setSelectedFactIds] = useState<string[]>([])
  const [question, setQuestion] = useState('Review the selected reported facts')
  const [portfolioReportId, setPortfolioReportId] = useState('')
  const [thesisDraft, setThesisDraft] = useState('')
  const [selectedThesisNoteId, setSelectedThesisNoteId] = useState('')
  const thesisNotes = useQuery({
    queryKey: ['research-thesis-notes', issuerId],
    queryFn: () => fetchResearchThesisNotes(issuerId),
    enabled: issuerId.length > 0,
  })
  const watchlist = useQuery({
    queryKey: ['research-watchlist-state', issuerId],
    queryFn: () => fetchResearchWatchlistState(issuerId),
    enabled: issuerId.length > 0,
  })

  const registerDocument = useMutation({
    mutationFn: registerResearchDocument,
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['research-company', issuerId],
      })
    },
  })
  const registerFact = useMutation({
    mutationFn: createReportedResearchFact,
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['research-company', issuerId],
      })
    },
  })
  const comparison = useMutation({ mutationFn: compareResearchFacts })
  const run = useMutation({ mutationFn: createResearchRun })
  const saveThesis = useMutation({
    mutationFn: createResearchThesisNote,
    onSuccess: async (note) => {
      setThesisDraft('')
      setSelectedThesisNoteId(note.id)
      await queryClient.invalidateQueries({
        queryKey: ['research-thesis-notes', issuerId],
      })
    },
  })
  const changeWatchlist = useMutation({
    mutationFn: (action: 'added' | 'removed') =>
      updateResearchWatchlist(issuerId, {
        action,
        idempotency_key: crypto.randomUUID(),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['research-watchlist-state', issuerId],
      })
    },
  })
  const availableNotes = thesisNotes.data ?? []
  const activeThesisNoteId = availableNotes.some(
    (note) => note.id === selectedThesisNoteId,
  )
    ? selectedThesisNoteId
    : (availableNotes[0]?.id ?? '')

  function saveDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!issuerId) return
    const input: components['schemas']['ResearchDocumentCreate'] = {
      issuer_id: issuerId,
      cik: documentDraft.cik,
      accession_number: documentDraft.accession_number,
      form_type: documentDraft.form_type,
      title: documentDraft.title,
      source_url: documentDraft.source_url,
      filing_date: documentDraft.filing_date || null,
      period_start: documentDraft.period_start || null,
      period_end: documentDraft.period_end || null,
    }
    registerDocument.mutate(input)
  }

  function saveFact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!factDraft.document_id) return
    const input: components['schemas']['ReportedFactCreate'] = {
      document_id: factDraft.document_id,
      taxonomy: factDraft.taxonomy,
      concept: factDraft.concept,
      raw_value: factDraft.raw_value,
      normalized_value: factDraft.normalized_value || null,
      unit: factDraft.unit,
      currency: factDraft.currency || null,
      period_kind: factDraft.period_kind,
      period_start:
        factDraft.period_kind === 'duration' ? factDraft.period_start : null,
      period_end:
        factDraft.period_kind === 'duration' ? factDraft.period_end : null,
      instant: factDraft.period_kind === 'instant' ? factDraft.instant : null,
      fiscal_year: factDraft.fiscal_year ? Number(factDraft.fiscal_year) : null,
      fiscal_period: factDraft.fiscal_period || null,
      idempotency_key: crypto.randomUUID(),
    }
    registerFact.mutate(input)
  }

  function toggleFact(identifier: string) {
    setSelectedFactIds((current) =>
      current.includes(identifier)
        ? current.filter((item) => item !== identifier)
        : [...current, identifier],
    )
  }

  function createBaseline(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!issuerId || selectedFactIds.length === 0) return
    run.mutate({
      issuer_id: issuerId,
      question,
      fact_ids: selectedFactIds,
      idempotency_key: crypto.randomUUID(),
      portfolio_report_id: portfolioReportId.trim() || null,
      thesis_note_id: activeThesisNoteId || null,
    })
  }

  function saveThesisNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!issuerId || !thesisDraft.trim()) return
    saveThesis.mutate({
      issuer_id: issuerId,
      text: thesisDraft,
      idempotency_key: crypto.randomUUID(),
    })
  }

  function compareSelected(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!priorFactId || !currentFactId) return
    comparison.mutate({
      prior_fact_id: priorFactId,
      current_fact_id: currentFactId,
    })
  }

  function displayFact(observation: Observation) {
    const fact = observation.fact
    const period =
      fact.period_kind === 'instant'
        ? `as of ${fact.instant}`
        : `${fact.period_start} to ${fact.period_end}`
    return `${fact.concept} · ${fact.raw_value} ${fact.unit} · ${period}`
  }

  return (
    <section className="mt-8 space-y-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:p-7">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
          Stage 5 · offline research
        </p>
        <h2 className="mt-1 text-xl font-semibold text-slate-950">
          Company filings and reported facts
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">
          Add a public SEC filing reference and manually entered reported facts.
          Values remain unverified. This workspace makes no SEC or AI service
          requests and does not change your portfolio.
        </p>
      </header>

      <div className="max-w-xl">
        <label
          className="mb-1 block text-sm font-medium text-slate-800"
          htmlFor="research-issuer"
        >
          Company in your issuer catalog
        </label>
        <select
          id="research-issuer"
          className={inputClass}
          value={issuerId}
          onChange={(event) => {
            setIssuerId(event.target.value)
            setSelectedFactIds([])
            setSelectedThesisNoteId('')
            run.reset()
            comparison.reset()
          }}
        >
          <option value="">Choose an issuer</option>
          {(issuers.data ?? []).map((issuer) => (
            <option key={issuer.id} value={issuer.id}>
              {issuer.display_name}
            </option>
          ))}
        </select>
        {issuers.isError && (
          <p role="alert" className="mt-2 text-sm text-red-700">
            Issuers could not be loaded:{' '}
            {message(issuers.error, 'Request failed.')}
          </p>
        )}
      </div>

      {issuerId && (
        <>
          <div className="grid gap-6 xl:grid-cols-2">
            <form
              className="space-y-4 rounded-xl border border-slate-200 p-4"
              onSubmit={saveDocument}
            >
              <div>
                <h3 className="font-semibold text-slate-900">
                  Register a filing reference
                </h3>
                <p className="mt-1 text-xs text-slate-500">
                  SEC-hosted links only. Filing identity and source contents are
                  not independently checked.
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm text-slate-700">
                  CIK
                  <input
                    className={inputClass}
                    value={documentDraft.cik}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        cik: event.target.value,
                      })
                    }
                    inputMode="numeric"
                    maxLength={10}
                    required
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Form
                  <input
                    className={inputClass}
                    value={documentDraft.form_type}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        form_type: event.target.value.toUpperCase(),
                      })
                    }
                    maxLength={12}
                    required
                  />
                </label>
                <label className="text-sm text-slate-700 sm:col-span-2">
                  Accession number
                  <input
                    className={inputClass}
                    placeholder="0000000000-00-000000"
                    value={documentDraft.accession_number}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        accession_number: event.target.value,
                      })
                    }
                    required
                  />
                </label>
                <label className="text-sm text-slate-700 sm:col-span-2">
                  Filing title
                  <input
                    className={inputClass}
                    value={documentDraft.title}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        title: event.target.value,
                      })
                    }
                    maxLength={300}
                    required
                  />
                </label>
                <label className="text-sm text-slate-700 sm:col-span-2">
                  SEC source URL
                  <input
                    className={inputClass}
                    type="url"
                    placeholder="https://www.sec.gov/Archives/..."
                    value={documentDraft.source_url}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        source_url: event.target.value,
                      })
                    }
                    maxLength={2048}
                    required
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Filing date
                  <input
                    className={inputClass}
                    type="date"
                    value={documentDraft.filing_date}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        filing_date: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Report period start
                  <input
                    className={inputClass}
                    type="date"
                    value={documentDraft.period_start}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        period_start: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Report period end
                  <input
                    className={inputClass}
                    type="date"
                    value={documentDraft.period_end}
                    onChange={(event) =>
                      setDocumentDraft({
                        ...documentDraft,
                        period_end: event.target.value,
                      })
                    }
                  />
                </label>
              </div>
              <button
                type="submit"
                disabled={registerDocument.isPending}
                className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                {registerDocument.isPending ? 'Saving…' : 'Save SEC reference'}
              </button>
              {registerDocument.isError && (
                <p role="alert" className="text-sm text-red-700">
                  {message(
                    registerDocument.error,
                    'Filing reference could not be saved.',
                  )}
                </p>
              )}
              {registerDocument.isSuccess && (
                <p role="status" className="text-sm text-emerald-800">
                  Reference saved as user-supplied and unverified.
                </p>
              )}
            </form>

            <form
              className="space-y-4 rounded-xl border border-slate-200 p-4"
              onSubmit={saveFact}
            >
              <div>
                <h3 className="font-semibold text-slate-900">
                  Enter a reported fact
                </h3>
                <p className="mt-1 text-xs text-slate-500">
                  Keep the original value and the normalized decimal separate.
                </p>
              </div>
              <label className="block text-sm text-slate-700">
                Filing reference
                <select
                  className={inputClass}
                  value={factDraft.document_id}
                  onChange={(event) =>
                    setFactDraft({
                      ...factDraft,
                      document_id: event.target.value,
                    })
                  }
                  required
                >
                  <option value="">Choose a filing</option>
                  {documents.map((document) => (
                    <option key={document.id} value={document.id}>
                      {document.form_type} · {document.title}
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm text-slate-700">
                  Taxonomy
                  <input
                    className={inputClass}
                    value={factDraft.taxonomy}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        taxonomy: event.target.value,
                      })
                    }
                    required
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Concept
                  <input
                    className={inputClass}
                    value={factDraft.concept}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        concept: event.target.value,
                      })
                    }
                    maxLength={100}
                    required
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Raw reported value
                  <input
                    className={inputClass}
                    value={factDraft.raw_value}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        raw_value: event.target.value,
                      })
                    }
                    required
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Normalized decimal (optional)
                  <input
                    className={inputClass}
                    inputMode="decimal"
                    value={factDraft.normalized_value}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        normalized_value: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Unit
                  <input
                    className={inputClass}
                    value={factDraft.unit}
                    onChange={(event) =>
                      setFactDraft({ ...factDraft, unit: event.target.value })
                    }
                    required
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Currency (optional)
                  <input
                    className={inputClass}
                    maxLength={3}
                    value={factDraft.currency}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        currency: event.target.value.toUpperCase(),
                      })
                    }
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Period kind
                  <select
                    className={inputClass}
                    value={factDraft.period_kind}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        period_kind: event.target.value as FactPeriod,
                      })
                    }
                  >
                    <option value="duration">Duration</option>
                    <option value="instant">Instant</option>
                  </select>
                </label>
                {factDraft.period_kind === 'duration' ? (
                  <>
                    <label className="text-sm text-slate-700">
                      Period start
                      <input
                        className={inputClass}
                        type="date"
                        value={factDraft.period_start}
                        onChange={(event) =>
                          setFactDraft({
                            ...factDraft,
                            period_start: event.target.value,
                          })
                        }
                        required
                      />
                    </label>
                    <label className="text-sm text-slate-700">
                      Period end
                      <input
                        className={inputClass}
                        type="date"
                        value={factDraft.period_end}
                        onChange={(event) =>
                          setFactDraft({
                            ...factDraft,
                            period_end: event.target.value,
                          })
                        }
                        required
                      />
                    </label>
                  </>
                ) : (
                  <label className="text-sm text-slate-700">
                    Instant date
                    <input
                      className={inputClass}
                      type="date"
                      value={factDraft.instant}
                      onChange={(event) =>
                        setFactDraft({
                          ...factDraft,
                          instant: event.target.value,
                        })
                      }
                      required
                    />
                  </label>
                )}
                <label className="text-sm text-slate-700">
                  Fiscal year
                  <input
                    className={inputClass}
                    type="number"
                    min={1900}
                    max={2200}
                    value={factDraft.fiscal_year}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        fiscal_year: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="text-sm text-slate-700">
                  Fiscal period
                  <select
                    className={inputClass}
                    value={factDraft.fiscal_period}
                    onChange={(event) =>
                      setFactDraft({
                        ...factDraft,
                        fiscal_period: event.target.value as FiscalPeriod | '',
                      })
                    }
                  >
                    <option value="">Not provided</option>
                    {(['Q1', 'Q2', 'Q3', 'Q4', 'H1', 'H2', 'FY'] as const).map(
                      (period) => (
                        <option key={period} value={period}>
                          {period}
                        </option>
                      ),
                    )}
                  </select>
                </label>
              </div>
              <button
                type="submit"
                disabled={registerFact.isPending || documents.length === 0}
                className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                {registerFact.isPending ? 'Saving…' : 'Save reported fact'}
              </button>
              {registerFact.isError && (
                <p role="alert" className="text-sm text-red-700">
                  {message(
                    registerFact.error,
                    'Reported fact could not be saved.',
                  )}
                </p>
              )}
              {registerFact.isSuccess && (
                <p role="status" className="text-sm text-emerald-800">
                  Fact saved as user-entered and unverified.
                </p>
              )}
            </form>
          </div>

          <section className="space-y-4 rounded-xl border border-slate-200 p-4">
            <div>
              <h3 className="font-semibold text-slate-900">Source record</h3>
              <p className="mt-1 text-xs text-slate-500">
                Original values, filing dates, and source links stay visible.
              </p>
            </div>
            {company.isLoading ? (
              <p className="text-sm text-slate-600">
                Loading company research…
              </p>
            ) : company.isError ? (
              <p role="alert" className="text-sm text-red-700">
                Company research could not be loaded:{' '}
                {message(company.error, 'Request failed.')}
              </p>
            ) : observations.length === 0 ? (
              <p className="text-sm text-slate-600">
                No filing references or reported facts have been registered.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {observations.map(({ fact, document }) => (
                  <li
                    key={fact.id}
                    className="grid gap-3 py-4 lg:grid-cols-[auto_1fr_auto]"
                  >
                    <input
                      type="checkbox"
                      aria-label={`Include ${fact.concept} from ${document.title} in baseline`}
                      checked={selectedFactIds.includes(fact.id)}
                      onChange={() => toggleFact(fact.id)}
                      className="mt-1 h-4 w-4 rounded border-slate-300"
                    />
                    <div>
                      <p className="font-medium text-slate-900">
                        {displayFact({ fact, document })}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {document.form_type} · filed{' '}
                        {document.filing_date ?? 'date unavailable'} ·{' '}
                        registered{' '}
                        {new Date(document.recorded_at).toLocaleDateString()} ·{' '}
                        context {fact.context_ref ?? 'unavailable'} ·{' '}
                        {fact.quality_status}
                      </p>
                    </div>
                    <a
                      className="text-sm font-medium text-blue-700 underline"
                      href={document.source_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {document.title}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {observations.length > 1 && (
            <form
              className="grid gap-4 rounded-xl border border-slate-200 p-4 md:grid-cols-[1fr_1fr_auto] md:items-end"
              onSubmit={compareSelected}
            >
              <label className="text-sm text-slate-700">
                Prior fact
                <select
                  className={inputClass}
                  value={priorFactId}
                  onChange={(event) => setPriorFactId(event.target.value)}
                  required
                >
                  <option value="">Choose a fact</option>
                  {observations.map((item) => (
                    <option key={item.fact.id} value={item.fact.id}>
                      {displayFact(item)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm text-slate-700">
                Current fact
                <select
                  className={inputClass}
                  value={currentFactId}
                  onChange={(event) => setCurrentFactId(event.target.value)}
                  required
                >
                  <option value="">Choose a fact</option>
                  {observations.map((item) => (
                    <option key={item.fact.id} value={item.fact.id}>
                      {displayFact(item)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                disabled={comparison.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50"
              >
                Compare periods
              </button>
              {comparison.data && (
                <p
                  role="status"
                  className="text-sm text-slate-700 md:col-span-3"
                >
                  {comparison.data.status === 'comparable'
                    ? `Change ${comparison.data.absolute_change ?? 'unavailable'}; ${comparison.data.percent_change ?? 'percent unavailable'}%.`
                    : `Comparison unavailable: ${comparison.data.diagnostics.join(', ')}.`}
                </p>
              )}
              {comparison.isError && (
                <p role="alert" className="text-sm text-red-700 md:col-span-3">
                  {message(comparison.error, 'Facts could not be compared.')}
                </p>
              )}
            </form>
          )}

          <section className="space-y-4 rounded-xl border border-slate-200 p-4">
            <div>
              <h3 className="font-semibold text-slate-900">
                Private thesis and portfolio context
              </h3>
              <p className="mt-1 text-xs text-slate-600">
                Thesis edits are saved as local versions. Portfolio context is
                read from a frozen report and stays private to this finance app.
              </p>
            </div>
            <button
              type="button"
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50"
              disabled={watchlist.isPending || changeWatchlist.isPending}
              onClick={() =>
                changeWatchlist.mutate(
                  watchlist.data?.active ? 'removed' : 'added',
                )
              }
            >
              {changeWatchlist.isPending
                ? 'Saving…'
                : watchlist.data?.active
                  ? 'Remove from watchlist'
                  : 'Add to watchlist'}
            </button>
            {watchlist.isError && (
              <p role="alert" className="text-sm text-red-700">
                Watchlist state could not be loaded:{' '}
                {message(watchlist.error, 'Request failed.')}
              </p>
            )}
            {changeWatchlist.isError && (
              <p role="alert" className="text-sm text-red-700">
                Watchlist update failed:{' '}
                {message(changeWatchlist.error, 'Request failed.')}
              </p>
            )}
            <form className="space-y-3" onSubmit={saveThesisNote}>
              <label className="block text-sm text-slate-700">
                Add a thesis note revision
                <textarea
                  className={inputClass}
                  rows={3}
                  maxLength={4000}
                  value={thesisDraft}
                  onChange={(event) => setThesisDraft(event.target.value)}
                  placeholder="Your own assumptions or questions; this note is not external evidence."
                  required
                />
              </label>
              <button
                type="submit"
                disabled={saveThesis.isPending || !thesisDraft.trim()}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50"
              >
                {saveThesis.isPending ? 'Saving…' : 'Save note version'}
              </button>
              {saveThesis.isError && (
                <p role="alert" className="text-sm text-red-700">
                  Thesis note could not be saved:{' '}
                  {message(saveThesis.error, 'Request failed.')}
                </p>
              )}
            </form>
            {availableNotes.length > 0 && (
              <label className="block text-sm text-slate-700">
                Attach a user-authored note version to this offline baseline
                <select
                  className={inputClass}
                  value={activeThesisNoteId}
                  onChange={(event) =>
                    setSelectedThesisNoteId(event.target.value)
                  }
                >
                  <option value="">Do not attach a note</option>
                  {availableNotes.map((note) => (
                    <option key={note.id} value={note.id}>
                      Version {note.version} ·{' '}
                      {new Date(note.created_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {availableNotes.length > 0 && activeThesisNoteId && (
              <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                {
                  availableNotes.find((note) => note.id === activeThesisNoteId)
                    ?.text
                }
              </p>
            )}
            <label className="block text-sm text-slate-700">
              Frozen portfolio report ID (optional)
              <input
                className={inputClass}
                value={portfolioReportId}
                onChange={(event) => setPortfolioReportId(event.target.value)}
                placeholder="Paste a report ID from Portfolio reports above"
              />
            </label>
            <p className="text-xs text-slate-500">
              A saved run freezes issuer-mapped direct and ETF-derived exposure,
              account filters, position/quote/fund snapshot IDs, and valuation
              dates. Account labels and thesis text are never sent to search or
              AI.
            </p>
          </section>

          <form
            className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/50 p-4"
            onSubmit={createBaseline}
          >
            <div>
              <h3 className="font-semibold text-slate-900">
                Save deterministic research baseline
              </h3>
              <p className="mt-1 text-xs text-slate-600">
                Saves selected fact values and citations without model
                synthesis.
              </p>
            </div>
            <label className="block text-sm text-slate-700">
              Research question label
              <input
                className={inputClass}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                maxLength={500}
                required
              />
            </label>
            <button
              type="submit"
              disabled={run.isPending || selectedFactIds.length === 0}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {run.isPending ? 'Saving…' : 'Save offline baseline'}
            </button>
            {run.isError && (
              <p role="alert" className="text-sm text-red-700">
                {message(run.error, 'Research baseline could not be saved.')}
              </p>
            )}
            {run.data && (
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <p className="font-medium text-slate-900">
                  Saved at{' '}
                  {new Date(run.data.result.generated_at).toLocaleString()} ·{' '}
                  {run.data.duplicate
                    ? 'existing idempotent result'
                    : 'new baseline'}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Values are user-entered and unverified. No synthesis was run.
                </p>
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
                  {run.data.result.citations.map((citation) => (
                    <li key={citation.fact_id}>
                      <a
                        className="text-blue-700 underline"
                        href={citation.source_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {citation.title} · {citation.form_type} ·{' '}
                        {citation.accession_number}
                      </a>
                    </li>
                  ))}
                </ul>
                {run.data.result.portfolio_context && (
                  <section className="mt-4 rounded-lg border border-blue-100 bg-blue-50/50 p-3">
                    <p className="font-medium text-slate-900">
                      Portfolio exposure · valued{' '}
                      {new Date(
                        run.data.result.portfolio_context.valuation_at,
                      ).toLocaleString()}
                    </p>
                    {run.data.result.portfolio_context.status === 'matched' ? (
                      <>
                        <p className="mt-1 text-sm text-slate-700">
                          Direct $
                          {run.data.result.portfolio_context.direct_exposure} ·
                          ETF-derived $
                          {run.data.result.portfolio_context.indirect_exposure}{' '}
                          · total $
                          {run.data.result.portfolio_context.total_exposure}
                        </p>
                        <ul className="mt-2 space-y-1 text-xs text-slate-600">
                          {run.data.result.portfolio_context.contributions.map(
                            (contribution, index) => (
                              <li
                                key={`${contribution.position_snapshot_id}-${index}`}
                              >
                                {contribution.account_name} ·{' '}
                                {contribution.exposure_kind} · $
                                {contribution.amount} · position as of{' '}
                                {contribution.position_as_of}
                                {contribution.fund_snapshot_id
                                  ? ` · fund ${contribution.fund_source ?? 'source unavailable'} as of ${contribution.fund_as_of ?? 'date unavailable'}`
                                  : ''}
                              </li>
                            ),
                          )}
                        </ul>
                      </>
                    ) : (
                      <p className="mt-1 text-sm text-amber-800">
                        No position or ETF look-through mapping was found for
                        this issuer.
                      </p>
                    )}
                  </section>
                )}
                {run.data.result.thesis_note && (
                  <blockquote className="mt-3 border-l-2 border-slate-300 pl-3 text-sm text-slate-700">
                    User thesis v{run.data.result.thesis_note.version} (not
                    evidence): {run.data.result.thesis_note.text}
                  </blockquote>
                )}
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-800">
                  {run.data.result.unknowns.map((unknown) => (
                    <li key={unknown}>{unknown}</li>
                  ))}
                </ul>
              </div>
            )}
          </form>
        </>
      )}
    </section>
  )
}
