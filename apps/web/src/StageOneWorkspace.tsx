import { createSubmissionKey } from './submission-key'
import { localDateTime } from './local-date'
import { parseCsvHeader } from './csv-headers'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelImport,
  cancelJob,
  correctImportRow,
  createIssuer,
  createManualQuote,
  createSecurity,
  fetchImport,
  fetchJob,
  fetchIssuers,
  fetchOwnedPortfolio,
  fetchSecurities,
  previewPositionImport,
  previewBrokeragePdf,
  publishImport,
} from './api/client'
import type { components } from './api/schema'

type ImportRow = components['schemas']['ImportRowRead']
type ImportReview = components['schemas']['ImportReviewRead']
type FieldMap = {
  identifier: string
  name: string
  quantity: string
  price: string
  currency: string
  asset_type: string
}

const EMPTY_MAP: FieldMap = {
  identifier: '',
  name: '',
  quantity: '',
  price: '',
  currency: '',
  asset_type: '',
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section
      aria-label={title}
      className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      {children}
    </section>
  )
}

export default function StageOneWorkspace({
  accountId,
  effectiveDate,
  expectedRevision,
  onPublished,
}: {
  accountId: string
  effectiveDate: string
  expectedRevision: number
  onPublished: (accountId: string) => Promise<void> | void
}) {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [mapping, setMapping] = useState<FieldMap>(EMPTY_MAP)
  const [sourceLabel, setSourceLabel] = useState('Broker CSV')
  const [replaceExisting, setReplaceExisting] = useState(false)
  const [importId, setImportId] = useState('')
  const [pendingJobId, setPendingJobId] = useState(
    () => localStorage.getItem('stage2-pdf-job-id') ?? '',
  )
  const uploadKey = useRef(createSubmissionKey())
  const fileSelection = useRef(0)
  const [rowDrafts, setRowDrafts] = useState<
    Record<
      string,
      {
        securityId: string
        quantity: string
        price: string
        currency: string
        reviewRevision: number
      }
    >
  >({})
  const [issuerName, setIssuerName] = useState('')
  const [securityType, setSecurityType] = useState('equity')
  const [securityTicker, setSecurityTicker] = useState('')
  const [securityName, setSecurityName] = useState('')
  const [securityCurrency, setSecurityCurrency] = useState('USD')
  const [securityIssuer, setSecurityIssuer] = useState('')
  const [identifierNamespace, setIdentifierNamespace] = useState('ticker')
  const [identifierValue, setIdentifierValue] = useState('')
  const [quoteSecurityId, setQuoteSecurityId] = useState('')
  const [quotePrice, setQuotePrice] = useState('')
  const [quoteDate, setQuoteDate] = useState(localDateTime)
  const [quoteReason, setQuoteReason] = useState('')
  const [page, setPage] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const catalogQuery = useQuery({
    queryKey: ['securities'],
    queryFn: fetchSecurities,
  })
  const issuersQuery = useQuery({
    queryKey: ['issuers'],
    queryFn: fetchIssuers,
  })
  const ownedQuery = useQuery({
    queryKey: ['owned-portfolio', accountId],
    queryFn: () => fetchOwnedPortfolio(accountId),
    enabled: Boolean(accountId),
  })
  const importQuery = useQuery({
    queryKey: ['import-review', importId],
    queryFn: () => fetchImport(importId),
    enabled: Boolean(importId),
  })
  const jobQuery = useQuery({
    queryKey: ['job', pendingJobId],
    queryFn: () => fetchJob(pendingJobId),
    enabled: Boolean(pendingJobId),
    refetchInterval: (query) =>
      ['pending', 'running'].includes(query.state.data?.status ?? '')
        ? 1000
        : false,
  })
  const securities = catalogQuery.data ?? []
  const issuers = issuersQuery.data ?? []
  const review = importQuery.data as ImportReview | undefined
  const visibleRows = useMemo(
    () => review?.rows.slice(page * 50, page * 50 + 50) ?? [],
    [page, review],
  )

  useEffect(() => {
    if (pendingJobId) localStorage.setItem('stage2-pdf-job-id', pendingJobId)
    else localStorage.removeItem('stage2-pdf-job-id')
  }, [pendingJobId])

  useEffect(() => {
    const processJob = (job: components['schemas']['JobRead'] | undefined) => {
      if (!pendingJobId || !job) return
      if (job.status === 'completed' && job.result) {
        const positionImportId = job.result.position_import_id
        if (typeof positionImportId !== 'string') {
          setError('The document job completed without a review reference.')
          setPendingJobId('')
          return
        }
        setImportId(positionImportId)
        setRowDrafts({})
        setPage(0)
        setNotice(
          job.result.duplicate === true
            ? 'This source was already reviewed; its prior result is shown.'
            : 'PDF staged privately. Review every row, evidence reference, and discrepancy before publishing.',
        )
        setError('')
        setPendingJobId('')
        void queryClient.invalidateQueries({
          queryKey: ['import-review', positionImportId],
        })
      } else if (job.status === 'failed') {
        setError(
          `Document processing failed (${job.safe_error_code ?? 'unknown_error'}). Use a CSV export or retry the same source.`,
        )
        uploadKey.current.reset()
        setPendingJobId('')
      } else if (job.status === 'cancelled') {
        setNotice('Document processing was cancelled before publication.')
        uploadKey.current.reset()
        setPendingJobId('')
      }
    }
    return queryClient.getQueryCache().subscribe((event) => {
      if (
        event.type === 'updated' &&
        event.query.queryKey[0] === 'job' &&
        event.query.queryKey[1] === pendingJobId &&
        event.query.state.status === 'success'
      ) {
        processJob(
          event.query.state.data as
            components['schemas']['JobRead'] | undefined,
        )
      }
    })
  }, [pendingJobId, queryClient])

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a CSV or supported brokerage PDF.')
      if (file.name.toLowerCase().endsWith('.pdf')) {
        const result = await previewBrokeragePdf({
          accountId,
          effectiveDate,
          expectedRevision,
          sourceLabel,
          file,
          idempotencyKey: uploadKey.current.forPayload({
            accountId,
            effectiveDate,
            expectedRevision,
            sourceLabel,
            replaceExisting,
            fileSelection: fileSelection.current,
          }),
          replaceExisting,
        })
        return { kind: 'job' as const, jobId: result.id }
      }
      if (!mapping.quantity || (!mapping.identifier && !mapping.name)) {
        throw new Error('Map quantity and a ticker or security name.')
      }
      const selected = Object.fromEntries(
        Object.entries(mapping).filter(([, header]) => Boolean(header)),
      )
      const result = await previewPositionImport({
        accountId,
        effectiveDate,
        expectedRevision,
        sourceLabel,
        mapping: selected,
        file,
        replaceExisting,
      })
      return {
        kind: 'review' as const,
        id: result.id,
        duplicate: result.duplicate,
        sourceFormat: 'CSV' as const,
      }
    },
    onSuccess: async (result) => {
      if (result.kind === 'job') {
        setPendingJobId(result.jobId)
        setNotice('PDF stored privately. Background extraction is queued.')
        setError('')
        return
      }
      setImportId(result.id)
      setRowDrafts({})
      setPage(0)
      setNotice(
        result.duplicate
          ? 'This source was already reviewed; its prior result is shown.'
          : `${result.sourceFormat} staged privately. Review every row, evidence reference, and discrepancy before publishing.`,
      )
      setError('')
      await queryClient.invalidateQueries({
        queryKey: ['import-review', result.id],
      })
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  const cancelJobMutation = useMutation({
    mutationFn: () => cancelJob(pendingJobId),
    onSuccess: async (job) => {
      await queryClient.invalidateQueries({ queryKey: ['job', pendingJobId] })
      if (job.status === 'cancelled') {
        uploadKey.current.reset()
        setPendingJobId('')
        setNotice('Document processing cancelled.')
      } else {
        setNotice(
          'Cancellation requested. The worker will stop before publication.',
        )
      }
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  const correctionMutation = useMutation({
    mutationFn: ({ row, excluded }: { row: ImportRow; excluded?: boolean }) => {
      if (!review) throw new Error('Load an import review first.')
      const draft = rowDrafts[row.id] ?? {
        securityId: row.security_id ?? '',
        quantity: row.normalized_quantity ?? row.raw_quantity ?? '',
        price: row.normalized_price ?? row.raw_price ?? '',
        currency: row.currency ?? row.raw_currency ?? 'USD',
        reviewRevision: review?.review_revision ?? 0,
      }
      return correctImportRow(importId, row.id, {
        expected_review_revision: draft.reviewRevision,
        reason: excluded
          ? 'Explicitly excluded during review'
          : 'Corrected during row review',
        ...(draft.securityId ? { security_id: draft.securityId } : {}),
        quantity: draft.quantity,
        price: draft.price,
        currency: draft.currency.toUpperCase(),
        ...(excluded === undefined ? {} : { excluded }),
      })
    },
    onSuccess: async (_result, { row }) => {
      setRowDrafts((current) =>
        Object.fromEntries(
          Object.entries(current).filter(([key]) => key !== row.id),
        ),
      )
      await queryClient.invalidateQueries({
        queryKey: ['import-review', importId],
      })
      setNotice('Correction saved. Earlier review batches were invalidated.')
      setError('')
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  const publishMutation = useMutation({
    mutationFn: () => {
      if (!review) throw new Error('Load an import review first.')
      if (review.account_id !== accountId)
        throw new Error(
          'Select the account captured by this review before publishing.',
        )
      if (Object.keys(rowDrafts).length)
        throw new Error(
          'Save corrections or discard row drafts before publishing.',
        )
      const publishedAccountId = review.account_id
      return publishImport(importId, review.review_revision).then(() => ({
        publishedAccountId,
      }))
    },
    onSuccess: async ({ publishedAccountId }) => {
      setNotice(
        'Reviewed position snapshot published atomically to the account.',
      )
      setError('')
      await Promise.all([
        onPublished(publishedAccountId),
        queryClient.invalidateQueries({
          queryKey: ['owned-portfolio', publishedAccountId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['import-review', importId],
        }),
      ])
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!review) throw new Error('Load an import review first.')
      return cancelImport(importId, review.review_revision)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['import-review', importId],
      })
      setNotice('Import cancelled. It cannot publish to the account.')
      setError('')
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  const issuerMutation = useMutation({
    mutationFn: () => createIssuer({ display_name: issuerName.trim() }),
    onSuccess: async (issuer) => {
      setIssuerName('')
      setSecurityIssuer(issuer.id)
      await queryClient.invalidateQueries({ queryKey: ['issuers'] })
      setNotice(`Issuer “${issuer.display_name}” added to the local catalog.`)
      setError('')
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  const securityMutation = useMutation({
    mutationFn: () =>
      createSecurity({
        security_type: securityType as 'equity' | 'etf' | 'cash' | 'other',
        display_ticker: securityTicker.trim() || null,
        name: securityName.trim(),
        currency: securityCurrency,
        issuer_id: securityIssuer || null,
        identifier_namespace: identifierValue.trim()
          ? identifierNamespace
          : null,
        identifier_exchange: '',
        identifier_value: identifierValue.trim() || null,
      }),
    onSuccess: async (security) => {
      setSecurityTicker('')
      setSecurityName('')
      setIdentifierValue('')
      setQuoteSecurityId(security.id)
      await queryClient.invalidateQueries({ queryKey: ['securities'] })
      setNotice(`Security “${security.display_ticker ?? security.name}” added.`)
      setError('')
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  const quoteMutation = useMutation({
    mutationFn: () => {
      const security = securities.find((item) => item.id === quoteSecurityId)
      if (!security) throw new Error('Select a security for this manual quote.')
      if (!quoteReason.trim())
        throw new Error('Add a source note for the manual quote.')
      return createManualQuote({
        security_id: security.id,
        as_of: new Date(quoteDate).toISOString(),
        price: quotePrice.trim(),
        currency: security.currency,
        reason: quoteReason.trim(),
      })
    },
    onSuccess: async () => {
      setQuoteReason('')
      setQuotePrice('')
      await queryClient.invalidateQueries({
        queryKey: ['owned-portfolio', accountId],
      })
      setNotice('Reviewed cached quote saved with its date and source note.')
      setError('')
    },
    onError: (reason) => setError(messageFor(reason)),
  })

  async function chooseFile(nextFile: File | null) {
    const selection = ++fileSelection.current
    uploadKey.current.reset()
    setFile(nextFile)
    setHeaders([])
    setMapping(EMPTY_MAP)
    setImportId('')
    setRowDrafts({})
    setNotice('')
    setError('')
    if (!nextFile) return
    if (nextFile.name.toLowerCase().endsWith('.pdf')) {
      setNotice(
        'The local text PDF adapter supports a holdings table with symbol, security, quantity, price, and market value columns. Scanned PDFs remain manual review only.',
      )
      return
    }
    try {
      const found = parseCsvHeader(await nextFile.slice(0, 64_000).text())
      if (selection === fileSelection.current) setHeaders(found)
    } catch (reason) {
      if (selection === fileSelection.current) setError(messageFor(reason))
    }
  }

  function rowDraft(row: ImportRow) {
    return (
      rowDrafts[row.id] ?? {
        securityId: row.security_id ?? '',
        quantity: row.normalized_quantity ?? row.raw_quantity ?? '',
        price: row.normalized_price ?? row.raw_price ?? '',
        currency: row.currency ?? row.raw_currency ?? 'USD',
        reviewRevision: review?.review_revision ?? 0,
      }
    )
  }

  return (
    <div className="mt-10 space-y-6">
      {(error || notice) && (
        <p
          className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-rose-200 bg-rose-50 text-rose-900' : 'border-emerald-200 bg-emerald-50 text-emerald-900'}`}
          role={error ? 'alert' : 'status'}
        >
          {error || notice}
        </p>
      )}

      {accountId && (
        <Section title="Snapshot-date owned value">
          {ownedQuery.isPending ? (
            <p className="text-sm text-slate-600">Loading dated valuation…</p>
          ) : ownedQuery.data ? (
            <>
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-500">
                    {ownedQuery.data.completeness} · as of{' '}
                    {ownedQuery.data.effective_date ?? 'no snapshot'}
                  </p>
                  <p className="mt-1 text-2xl font-semibold text-slate-950">
                    {ownedQuery.data.total_usd === null
                      ? `Known USD subtotal ${ownedQuery.data.known_usd_subtotal}`
                      : `USD ${ownedQuery.data.total_usd}`}
                  </p>
                </div>
                <p className="max-w-xl text-xs text-slate-500">
                  This editor inspects prices at the position snapshot date. Use
                  Portfolio reports above for a current or historical frozen
                  valuation. Total value and percentages are withheld when a
                  held row is unpriced, stale, foreign currency, or signed.
                  Owned positions remain separate from derived exposure.
                </p>
              </div>
              {ownedQuery.data.lines.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[42rem] text-left text-sm">
                    <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
                      <tr>
                        <th className="py-2 pr-4">Security</th>
                        <th className="py-2 pr-4">Quantity</th>
                        <th className="py-2 pr-4">Value</th>
                        <th className="py-2 pr-4">Price source</th>
                        <th className="py-2">State</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {ownedQuery.data.lines.map((line) => (
                        <tr key={line.position_id}>
                          <td className="py-2 pr-4 font-medium">
                            {line.ticker ?? line.name}
                          </td>
                          <td className="py-2 pr-4">{line.quantity}</td>
                          <td className="py-2 pr-4">
                            {line.value === null
                              ? 'Unavailable'
                              : `${line.value_currency} ${line.value}`}
                          </td>
                          <td className="py-2 pr-4 text-slate-600">
                            {line.price_source ?? 'No price'}
                            {line.price_as_of
                              ? ` · ${line.price_as_of.slice(0, 10)}`
                              : ''}
                          </td>
                          <td className="py-2 text-slate-600">
                            {line.quality_status === 'stale'
                              ? 'stale'
                              : line.status}
                            {line.allocation_percent
                              ? ` · ${line.allocation_percent}%`
                              : ''}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-600">
              No owned snapshot is available yet.
            </p>
          )}
        </Section>
      )}

      <Section title="Local security and issuer catalog">
        <p className="text-sm text-slate-600">
          Start from an empty catalog. Add only securities and issuer links you
          have reviewed. The CSV mapper will use exact local ticker or exact
          name matches only.
        </p>
        <div className="grid gap-6 lg:grid-cols-2">
          <form
            className="space-y-3 rounded-xl bg-slate-50 p-4"
            onSubmit={(event) => {
              event.preventDefault()
              issuerMutation.mutate()
            }}
          >
            <h3 className="font-semibold text-slate-900">Add issuer</h3>
            <label className="block text-sm" htmlFor="issuer-name">
              Issuer name
            </label>
            <input
              id="issuer-name"
              className="w-full rounded-lg border border-slate-300 px-3 py-2"
              value={issuerName}
              onChange={(event) => setIssuerName(event.target.value)}
              required
              maxLength={200}
            />
            <button
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold"
              disabled={issuerMutation.isPending}
            >
              Add issuer
            </button>
          </form>
          <form
            className="space-y-3 rounded-xl bg-slate-50 p-4"
            onSubmit={(event) => {
              event.preventDefault()
              securityMutation.mutate()
            }}
          >
            <h3 className="font-semibold text-slate-900">Add security</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm">
                Name
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={securityName}
                  onChange={(event) => setSecurityName(event.target.value)}
                  required
                  maxLength={200}
                />
              </label>
              <label className="text-sm">
                Ticker (optional)
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={securityTicker}
                  onChange={(event) => setSecurityTicker(event.target.value)}
                  maxLength={32}
                />
              </label>
              <label className="text-sm">
                Type
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                  value={securityType}
                  onChange={(event) => setSecurityType(event.target.value)}
                >
                  <option value="equity">Equity</option>
                  <option value="etf">ETF</option>
                  <option value="cash">Cash</option>
                  <option value="other">Other</option>
                </select>
              </label>
              <label className="text-sm">
                Currency
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                  value={securityCurrency}
                  onChange={(event) => setSecurityCurrency(event.target.value)}
                >
                  {['USD', 'CAD', 'EUR', 'GBP', 'JPY'].map((currency) => (
                    <option key={currency}>{currency}</option>
                  ))}
                </select>
              </label>
              <label className="text-sm">
                Reviewed issuer
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                  value={securityIssuer}
                  onChange={(event) => setSecurityIssuer(event.target.value)}
                >
                  <option value="">No issuer mapping</option>
                  {issuers.map((issuer) => (
                    <option key={issuer.id} value={issuer.id}>
                      {issuer.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm">
                Identifier namespace
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={identifierNamespace}
                  onChange={(event) =>
                    setIdentifierNamespace(event.target.value)
                  }
                  maxLength={40}
                />
              </label>
              <label className="text-sm sm:col-span-2">
                Identifier value (optional)
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={identifierValue}
                  onChange={(event) => setIdentifierValue(event.target.value)}
                  maxLength={128}
                />
              </label>
            </div>
            <button
              className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white"
              disabled={securityMutation.isPending}
            >
              Add to local catalog
            </button>
          </form>
        </div>
        <p className="text-xs text-slate-500">
          {securities.length} local securities · {issuers.length} issuers
          {catalogQuery.isError || issuersQuery.isError
            ? ' · Catalog could not be loaded.'
            : ''}
        </p>
      </Section>

      <Section title="Reviewed CSV or brokerage statement import">
        {!accountId ? (
          <p className="text-sm text-slate-600">
            Choose or create an account to stage positions.
          </p>
        ) : (
          <>
            <p className="text-sm text-slate-600">
              Originals stay in private local storage. CSV columns are mapped by
              you; text PDFs use a deterministic holdings-table adapter. Check
              page and row evidence, correct discrepancies, and resolve or
              explicitly exclude every unparsed row before publication.
            </p>
            <div className="grid gap-3 md:grid-cols-3">
              <label className="text-sm">
                CSV or supported text PDF
                <input
                  className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                  type="file"
                  accept=".csv,text/csv,.pdf,application/pdf"
                  onChange={(event) =>
                    void chooseFile(event.target.files?.[0] ?? null)
                  }
                />
              </label>
              <label className="text-sm">
                Source label
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={sourceLabel}
                  onChange={(event) => setSourceLabel(event.target.value)}
                  maxLength={100}
                />
              </label>
              <div className="text-sm">
                <span className="block">
                  Snapshot date and account revision
                </span>
                <span className="mt-2 block rounded-lg bg-slate-50 px-3 py-2">
                  {effectiveDate} · revision {expectedRevision}
                </span>
              </div>
            </div>
            {headers.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {(
                  [
                    ['identifier', 'Ticker / identifier'],
                    ['name', 'Security name'],
                    ['quantity', 'Quantity or cash balance'],
                    ['price', 'Price (optional)'],
                    ['currency', 'Currency (optional)'],
                    ['asset_type', 'Source asset type (optional)'],
                  ] as const
                ).map(([field, label]) => (
                  <label key={field} className="text-sm">
                    {label}
                    <select
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                      value={mapping[field]}
                      onChange={(event) =>
                        setMapping((current) => ({
                          ...current,
                          [field]: event.target.value,
                        }))
                      }
                    >
                      <option value="">Do not map</option>
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
            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input
                className="mt-1"
                type="checkbox"
                checked={replaceExisting}
                onChange={(event) => setReplaceExisting(event.target.checked)}
              />
              Treat this as an explicit replacement if this exact file, account,
              and date were already reviewed with another column mapping.
            </label>
            <button
              className="rounded-lg bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
              type="button"
              disabled={
                !file || previewMutation.isPending || Boolean(pendingJobId)
              }
              onClick={() => previewMutation.mutate()}
            >
              {previewMutation.isPending
                ? 'Extracting and staging…'
                : 'Stage for review'}
            </button>
            {pendingJobId && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">
                <p role="status">
                  PDF job {jobQuery.data?.status ?? 'loading'} •{' '}
                  {jobQuery.data?.progress_stage ?? 'loading status'}
                  {jobQuery.data?.progress_total
                    ? ` • ${jobQuery.data.progress_current}/${jobQuery.data.progress_total}`
                    : ''}
                </p>
                <button
                  className="rounded border border-blue-300 px-3 py-1.5 disabled:opacity-50"
                  type="button"
                  disabled={cancelJobMutation.isPending}
                  onClick={() => cancelJobMutation.mutate()}
                >
                  {cancelJobMutation.isPending
                    ? 'Requesting…'
                    : 'Cancel processing'}
                </button>
              </div>
            )}
            {jobQuery.error && pendingJobId && (
              <p role="alert" className="text-sm text-rose-800">
                Job status is temporarily unavailable. This job can be resumed
                after the API is reachable.
              </p>
            )}
            {importId && importQuery.isPending && (
              <p role="status" className="text-sm text-slate-600">
                Loading review rows…
              </p>
            )}
            {review && review.account_id !== accountId && (
              <p
                role="alert"
                className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900"
              >
                This review belongs to another account. Select its captured
                account before publishing.
              </p>
            )}
            {review && (
              <div className="space-y-4 border-t border-slate-200 pt-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900">
                      {review.source_label} · {review.row_count} rows ·{' '}
                      {review.status}
                    </p>
                    <p className="text-xs text-slate-500">
                      Review revision {review.review_revision}; captured account
                      revision {review.expected_account_revision} · account{' '}
                      {review.account_id} · effective {review.effective_date}
                    </p>
                  </div>
                  {review.rows.length > 50 && (
                    <div className="flex items-center gap-2 text-sm">
                      <button
                        className="rounded border px-2 py-1 disabled:opacity-40"
                        type="button"
                        disabled={page === 0}
                        onClick={() =>
                          setPage((current) => Math.max(0, current - 1))
                        }
                      >
                        Previous
                      </button>
                      <span>
                        {page + 1} / {Math.ceil(review.rows.length / 50)}
                      </span>
                      <button
                        className="rounded border px-2 py-1 disabled:opacity-40"
                        type="button"
                        disabled={(page + 1) * 50 >= review.rows.length}
                        onClick={() => setPage((current) => current + 1)}
                      >
                        Next
                      </button>
                    </div>
                  )}
                </div>
                <div className="space-y-3">
                  {visibleRows.map((row) => {
                    const draft = rowDraft(row)
                    return (
                      <article
                        key={row.id}
                        className="space-y-3 rounded-xl border border-slate-200 p-4"
                      >
                        <div className="flex flex-wrap justify-between gap-2">
                          <div>
                            <p className="font-medium">
                              Row {row.row_number} ·{' '}
                              {row.raw_identifier ||
                                row.raw_name ||
                                'Unidentified source row'}
                            </p>
                            <p className="text-xs text-slate-600">
                              {row.row_status}
                              {row.excluded ? ' · excluded' : ''} · raw{' '}
                              {JSON.stringify(row.raw_payload)}
                            </p>
                            {Object.values(row.diagnostics).map(
                              (diagnostic) => (
                                <p
                                  key={diagnostic}
                                  className="mt-1 text-xs text-amber-800"
                                >
                                  {diagnostic}
                                </p>
                              ),
                            )}
                          </div>
                          <span className="text-xs text-slate-500">
                            {row.security_id
                              ? `Mapped: ${row.security_label}`
                              : 'No local security match'}
                          </span>
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                          <label className="text-xs">
                            Local security
                            <select
                              className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-2 text-sm"
                              value={draft.securityId}
                              onChange={(event) =>
                                setRowDrafts((current) => ({
                                  ...current,
                                  [row.id]: {
                                    ...draft,
                                    securityId: event.target.value,
                                  },
                                }))
                              }
                            >
                              <option value="">
                                Choose after catalog review
                              </option>
                              {securities.map((security) => (
                                <option key={security.id} value={security.id}>
                                  {security.display_ticker ?? security.name} ·{' '}
                                  {security.currency}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="text-xs">
                            Quantity / cash balance
                            <input
                              className="mt-1 w-full rounded border border-slate-300 px-2 py-2 text-sm"
                              value={draft.quantity}
                              onChange={(event) =>
                                setRowDrafts((current) => ({
                                  ...current,
                                  [row.id]: {
                                    ...draft,
                                    quantity: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <label className="text-xs">
                            Price (blank means unavailable)
                            <input
                              className="mt-1 w-full rounded border border-slate-300 px-2 py-2 text-sm"
                              value={draft.price}
                              onChange={(event) =>
                                setRowDrafts((current) => ({
                                  ...current,
                                  [row.id]: {
                                    ...draft,
                                    price: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <label className="text-xs">
                            Currency
                            <input
                              className="mt-1 w-full rounded border border-slate-300 px-2 py-2 text-sm uppercase"
                              value={draft.currency}
                              onChange={(event) =>
                                setRowDrafts((current) => ({
                                  ...current,
                                  [row.id]: {
                                    ...draft,
                                    currency: event.target.value,
                                  },
                                }))
                              }
                              maxLength={3}
                            />
                          </label>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="rounded border border-slate-300 px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
                            type="button"
                            disabled={
                              correctionMutation.isPending || row.excluded
                            }
                            onClick={() => correctionMutation.mutate({ row })}
                          >
                            Save correction
                          </button>
                          <button
                            className="rounded border border-amber-400 px-3 py-1.5 text-sm font-semibold text-amber-900 disabled:opacity-50"
                            type="button"
                            disabled={
                              correctionMutation.isPending || row.excluded
                            }
                            onClick={() =>
                              correctionMutation.mutate({ row, excluded: true })
                            }
                          >
                            Explicitly exclude row
                          </button>
                          {row.excluded && (
                            <button
                              className="rounded border border-slate-300 px-3 py-1.5 text-sm"
                              type="button"
                              disabled={correctionMutation.isPending}
                              onClick={() =>
                                correctionMutation.mutate({
                                  row,
                                  excluded: false,
                                })
                              }
                            >
                              Reinclude for review
                            </button>
                          )}
                        </div>
                      </article>
                    )
                  })}
                </div>
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setRowDrafts({})
                      void queryClient.invalidateQueries({
                        queryKey: ['import-review', importId],
                      })
                    }}
                  >
                    Discard row drafts and reload review
                  </button>
                  <button
                    className="rounded-lg bg-emerald-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
                    type="button"
                    disabled={
                      publishMutation.isPending ||
                      review.status !== 'review' ||
                      review.account_id !== accountId ||
                      !review.rows.every(
                        (row) => row.row_status === 'ready' || row.excluded,
                      )
                    }
                    onClick={() => publishMutation.mutate()}
                  >
                    {publishMutation.isPending
                      ? 'Publishing…'
                      : 'Publish reviewed snapshot'}
                  </button>
                  <button
                    className="rounded-lg border border-rose-300 px-4 py-2.5 font-semibold text-rose-800 disabled:opacity-50"
                    type="button"
                    disabled={
                      cancelMutation.isPending ||
                      ['cancelled', 'published', 'replaced'].includes(
                        review.status,
                      )
                    }
                    onClick={() => cancelMutation.mutate()}
                  >
                    Cancel import
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </Section>

      {accountId && (
        <Section title="Manual cached quote">
          <p className="text-sm text-slate-600">
            Add a dated quote from a source you checked. It applies only to an
            owned security row without a line-level snapshot price, and only
            when its date is not later than the snapshot date.
          </p>
          <div className="grid gap-3 md:grid-cols-4">
            <label className="text-sm">
              Security
              <select
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                value={quoteSecurityId}
                onChange={(event) => setQuoteSecurityId(event.target.value)}
              >
                <option value="">Choose security</option>
                {securities.map((security) => (
                  <option key={security.id} value={security.id}>
                    {security.display_ticker ?? security.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              As of
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                type="datetime-local"
                value={quoteDate}
                onChange={(event) => setQuoteDate(event.target.value)}
              />
            </label>
            <label className="text-sm">
              Price
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                inputMode="decimal"
                value={quotePrice}
                onChange={(event) => setQuotePrice(event.target.value)}
              />
            </label>
            <label className="text-sm">
              Source note
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                value={quoteReason}
                onChange={(event) => setQuoteReason(event.target.value)}
                maxLength={500}
              />
            </label>
          </div>
          <button
            className="rounded-lg border border-slate-300 px-4 py-2.5 font-semibold disabled:opacity-50"
            type="button"
            disabled={quoteMutation.isPending || !accountId}
            onClick={() => quoteMutation.mutate()}
          >
            {quoteMutation.isPending ? 'Saving…' : 'Save reviewed quote'}
          </button>
        </Section>
      )}
    </div>
  )
}

function messageFor(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The request could not be completed.'
}
