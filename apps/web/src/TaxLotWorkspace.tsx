import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  correctTaxLotImportRow,
  createTaxLotAdjustment,
  fetchAccounts,
  fetchTaxLotImport,
  fetchTaxLots,
  fetchSecurities,
  previewTaxLotImport,
  publishTaxLotImport,
} from './api/client'
import type { components } from './api/schema'

type LotRow = components['schemas']['TaxLotImportRowRead']
type Review = components['schemas']['TaxLotImportReviewRead']
type Lot = components['schemas']['TaxLotRead']
type Correction = components['schemas']['TaxLotImportCorrection']
type LotField =
  | 'ticker'
  | 'source_lot_id'
  | 'acquired_at'
  | 'initial_quantity'
  | 'remaining_quantity'
  | 'initial_basis'
  | 'remaining_basis'
  | 'basis_currency'
  | 'evidence_ref'

const IMPORT_FIELDS: { key: LotField; label: string; required?: boolean }[] = [
  { key: 'ticker', label: 'Ticker', required: true },
  { key: 'source_lot_id', label: 'Source lot ID' },
  { key: 'acquired_at', label: 'Acquired date' },
  { key: 'initial_quantity', label: 'Initial quantity' },
  { key: 'remaining_quantity', label: 'Remaining quantity', required: true },
  { key: 'initial_basis', label: 'Initial basis' },
  { key: 'remaining_basis', label: 'Remaining basis' },
  { key: 'basis_currency', label: 'Basis currency' },
  { key: 'evidence_ref', label: 'Evidence reference' },
]

function today(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function csvHeaders(value: string): string[] {
  const line = value.split(/\r?\n/, 1)[0] ?? ''
  const headers: string[] = []
  let current = ''
  let quoted = false
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    if (char === '"' && line[index + 1] === '"' && quoted) {
      current += '"'
      index += 1
    } else if (char === '"') {
      quoted = !quoted
    } else if (char === ',' && !quoted) {
      headers.push(current.trim())
      current = ''
    } else {
      current += char
    }
  }
  headers.push(current.trim())
  return headers.map((header) => header.replace(/^\uFEFF/, ''))
}

function initialMapping(headers: string[]): Record<string, string> {
  const normalized = headers.map((header) => header.trim().toLowerCase())
  const aliases: Record<LotField, string[]> = {
    ticker: ['ticker', 'symbol', 'security'],
    source_lot_id: ['lot id', 'lot_id', 'source lot id', 'source_lot_id'],
    acquired_at: [
      'acquired date',
      'acquired_at',
      'date acquired',
      'purchase date',
    ],
    initial_quantity: [
      'initial quantity',
      'initial_quantity',
      'original quantity',
    ],
    remaining_quantity: [
      'remaining quantity',
      'remaining_quantity',
      'quantity',
      'shares',
    ],
    initial_basis: [
      'initial basis',
      'initial_basis',
      'original basis',
      'cost basis',
    ],
    remaining_basis: ['remaining basis', 'remaining_basis', 'adjusted basis'],
    basis_currency: ['basis currency', 'basis_currency', 'currency'],
    evidence_ref: ['evidence', 'evidence_ref', 'reference'],
  }
  return Object.fromEntries(
    IMPORT_FIELDS.flatMap(({ key }) => {
      const index = normalized.findIndex((header) =>
        aliases[key].includes(header),
      )
      return index < 0 ? [] : [[key, headers[index]]]
    }),
  )
}

function displayed(value: string | null | undefined): string {
  return value ?? 'Unavailable'
}

function ReviewRow({
  row,
  review,
  securities,
  onCorrect,
  busy,
}: {
  row: LotRow
  review: Review
  securities: Awaited<ReturnType<typeof fetchSecurities>>
  onCorrect: (data: Correction) => void
  busy: boolean
}) {
  const [securityId, setSecurityId] = useState(row.security_id ?? '')
  const [sourceLotId, setSourceLotId] = useState(row.raw_source_lot_id ?? '')
  const [acquiredAt, setAcquiredAt] = useState(row.acquired_at ?? '')
  const [initialQuantity, setInitialQuantity] = useState(
    row.initial_quantity ?? '',
  )
  const [remainingQuantity, setRemainingQuantity] = useState(
    row.remaining_quantity ?? '',
  )
  const [initialBasis, setInitialBasis] = useState(row.initial_basis ?? '')
  const [remainingBasis, setRemainingBasis] = useState(
    row.remaining_basis ?? '',
  )
  const [basisCurrency, setBasisCurrency] = useState(row.basis_currency ?? '')
  const [evidenceRef, setEvidenceRef] = useState(row.evidence_ref ?? '')
  const [reason, setReason] = useState('Corrected after source review')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const correction: Correction = {
      expected_revision: review.review_revision,
      reason,
    }
    if (securityId !== (row.security_id ?? ''))
      correction.security_id = securityId || null
    if (sourceLotId !== (row.raw_source_lot_id ?? ''))
      correction.source_lot_id = sourceLotId || null
    if (acquiredAt !== (row.acquired_at ?? ''))
      correction.acquired_at = acquiredAt || null
    if (initialQuantity !== (row.initial_quantity ?? ''))
      correction.initial_quantity = initialQuantity || null
    if (remainingQuantity !== (row.remaining_quantity ?? ''))
      correction.remaining_quantity = remainingQuantity || null
    if (initialBasis !== (row.initial_basis ?? ''))
      correction.initial_basis = initialBasis || null
    if (remainingBasis !== (row.remaining_basis ?? ''))
      correction.remaining_basis = remainingBasis || null
    if (basisCurrency !== (row.basis_currency ?? ''))
      correction.basis_currency = basisCurrency || null
    if (evidenceRef !== (row.evidence_ref ?? ''))
      correction.evidence_ref = evidenceRef || null
    onCorrect(correction)
  }

  return (
    <article className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="font-semibold text-slate-900">
            Row {row.row_number} · {row.raw_ticker ?? 'Missing ticker'}
          </h4>
          <p className="mt-1 text-xs text-slate-500">
            {row.row_status} · {row.quality_status}
          </p>
        </div>
        {Object.keys(row.diagnostics).length > 0 && (
          <p className="max-w-2xl text-sm text-amber-800">
            {Object.entries(row.diagnostics)
              .map(([field, issue]) => `${field}: ${String(issue)}`)
              .join(' · ')}
          </p>
        )}
      </div>
      <details className="mt-3 text-sm text-slate-600">
        <summary className="cursor-pointer">Original source row</summary>
        <pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-3 text-xs">
          {JSON.stringify(row.raw_payload, null, 2)}
        </pre>
      </details>
      {review.status === 'review' && row.row_status !== 'duplicate' && (
        <form className="mt-4 grid gap-3 md:grid-cols-4" onSubmit={submit}>
          <label className="grid gap-1 text-xs font-medium">
            Match actual security
            <select
              className="rounded border border-slate-300 p-2 text-sm"
              value={securityId}
              onChange={(event) => setSecurityId(event.target.value)}
            >
              <option value="">Unresolved</option>
              {securities
                .filter(
                  (security) =>
                    security.security_type === 'equity' ||
                    security.security_type === 'etf',
                )
                .map((security) => (
                  <option key={security.id} value={security.id}>
                    {security.display_ticker ?? security.name} · {security.name}
                  </option>
                ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Source lot ID
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              maxLength={200}
              value={sourceLotId}
              onChange={(event) => setSourceLotId(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Acquired date
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              type="date"
              value={acquiredAt}
              onChange={(event) => setAcquiredAt(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Initial quantity
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              inputMode="decimal"
              value={initialQuantity}
              onChange={(event) => setInitialQuantity(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Remaining quantity
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              inputMode="decimal"
              value={remainingQuantity}
              onChange={(event) => setRemainingQuantity(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Initial basis
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              inputMode="decimal"
              value={initialBasis}
              onChange={(event) => setInitialBasis(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Remaining basis
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              inputMode="decimal"
              value={remainingBasis}
              onChange={(event) => setRemainingBasis(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Basis currency
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              maxLength={3}
              value={basisCurrency}
              onChange={(event) =>
                setBasisCurrency(event.target.value.toUpperCase())
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-medium">
            Evidence reference
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              value={evidenceRef}
              onChange={(event) => setEvidenceRef(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium md:col-span-3">
            Correction reason
            <input
              className="rounded border border-slate-300 p-2 text-sm"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              required
            />
          </label>
          <button
            className="self-end rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            type="submit"
            disabled={busy}
          >
            Save reviewed correction
          </button>
        </form>
      )}
    </article>
  )
}

export default function TaxLotWorkspace() {
  const queryClient = useQueryClient()
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const securitiesQuery = useQuery({
    queryKey: ['securities'],
    queryFn: fetchSecurities,
  })
  const accounts = (accountsQuery.data ?? []).filter(
    (account) => account.active,
  )
  const securities = securitiesQuery.data ?? []
  const [accountId, setAccountId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [sourceLabel, setSourceLabel] = useState('Brokerage tax lots')
  const [importId, setImportId] = useState('')
  const [importNotice, setImportNotice] = useState('')
  const [acknowledgeDifferences, setAcknowledgeDifferences] = useState(false)
  const [publishReason, setPublishReason] = useState(
    'Accepted after reviewing supplied lot evidence',
  )
  const [page, setPage] = useState(0)
  const [lotQuality, setLotQuality] = useState<
    'all' | 'reported' | 'incomplete'
  >('all')
  const [adjustmentLotId, setAdjustmentLotId] = useState('')
  const [adjustmentType, setAdjustmentType] = useState<
    'split' | 'basis_adjustment' | 'return_of_capital' | 'correction' | 'other'
  >('correction')
  const [quantityDelta, setQuantityDelta] = useState('')
  const [basisDelta, setBasisDelta] = useState('')
  const [adjustmentCurrency, setAdjustmentCurrency] = useState('')
  const [adjustmentDate, setAdjustmentDate] = useState(today)
  const [adjustmentSource, setAdjustmentSource] = useState(
    'Manual source-backed adjustment',
  )
  const [adjustmentReason, setAdjustmentReason] = useState('')
  const [adjustmentEvidence, setAdjustmentEvidence] = useState('')

  const selectedAccountId = accountId || accounts[0]?.id || ''

  const lotsQuery = useQuery({
    queryKey: ['tax-lots', selectedAccountId, lotQuality],
    queryFn: () =>
      fetchTaxLots(
        selectedAccountId,
        lotQuality === 'all' ? undefined : lotQuality,
      ),
    enabled: Boolean(selectedAccountId),
  })
  const importQuery = useQuery({
    queryKey: ['tax-lot-import', importId],
    queryFn: () => fetchTaxLotImport(importId),
    enabled: Boolean(importId),
  })

  const preview = useMutation({
    mutationFn: () => {
      if (!selectedAccountId || !file)
        throw new Error('Select an account and a CSV file.')
      if (!mapping.ticker || !mapping.remaining_quantity)
        throw new Error('Map ticker and remaining quantity.')
      return previewTaxLotImport({
        accountId: selectedAccountId,
        sourceLabel,
        mapping,
        file,
      })
    },
    onSuccess: async (result) => {
      setImportId(result.id)
      setPage(0)
      setAcknowledgeDifferences(false)
      setImportNotice(
        result.duplicate
          ? 'This file already has a matching review/import. Showing that record.'
          : 'CSV staged for review; accepted lots have not changed.',
      )
      await queryClient.invalidateQueries({ queryKey: ['tax-lots'] })
    },
  })

  const correction = useMutation({
    mutationFn: ({ rowId, data }: { rowId: string; data: Correction }) =>
      correctTaxLotImportRow(importId, rowId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['tax-lot-import', importId],
      })
      setAcknowledgeDifferences(false)
    },
  })

  const publish = useMutation({
    mutationFn: () => {
      if (!importQuery.data) throw new Error('Load the import review first.')
      return publishTaxLotImport(importId, {
        expected_revision: importQuery.data.review_revision,
        acknowledge_quantity_differences: acknowledgeDifferences,
        reason: publishReason,
      })
    },
    onSuccess: async () => {
      setImportNotice(
        'Reviewed source-backed lots published. Position snapshots were not changed.',
      )
      await queryClient.invalidateQueries({
        queryKey: ['tax-lot-import', importId],
      })
      await queryClient.invalidateQueries({ queryKey: ['tax-lots'] })
    },
  })

  const adjustment = useMutation({
    mutationFn: () => {
      if (!adjustmentLotId || (!quantityDelta && !basisDelta))
        throw new Error(
          'Select a lot and enter a quantity or basis adjustment.',
        )
      return createTaxLotAdjustment(adjustmentLotId, {
        adjustment_type: adjustmentType,
        quantity_delta: quantityDelta || null,
        basis_delta: basisDelta || null,
        basis_currency: basisDelta ? adjustmentCurrency || null : null,
        effective_date: adjustmentDate,
        source_label: adjustmentSource,
        reason: adjustmentReason,
        evidence_ref: adjustmentEvidence || null,
        idempotency_key: crypto.randomUUID(),
      })
    },
    onSuccess: async () => {
      setQuantityDelta('')
      setBasisDelta('')
      setAdjustmentReason('')
      setAdjustmentEvidence('')
      await queryClient.invalidateQueries({
        queryKey: ['tax-lots', selectedAccountId],
      })
    },
  })

  const review = importQuery.data
  const rows = review?.rows ?? []
  const visibleRows = rows.slice(page * 50, page * 50 + 50)
  const lotRows: Lot[] = lotsQuery.data ?? []
  const selectedAdjustmentLot = lotRows.find(
    (lot) => lot.id === adjustmentLotId,
  )
  const blockingRows = rows.some((row) => row.row_status === 'needs_review')
  const needsAcknowledgement = Boolean(
    review?.gaps.length ||
    review?.quantity_differences.some((row) => Number(row.difference) !== 0),
  )

  return (
    <section className="mx-auto flex max-w-6xl flex-col gap-6 px-5 pb-12 sm:px-8">
      <header className="border-b border-slate-200 pb-5">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-700">
          Stage 3 · Source-backed tax lots
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
          Tax-lot evidence
        </h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Import actual account lots from a CSV, reconcile their remaining
          quantities with accepted positions, and retain source and correction
          history. Missing acquisition dates or basis stay unavailable.
          Look-through exposures never create lots.
        </p>
      </header>

      {(preview.error ||
        correction.error ||
        publish.error ||
        adjustment.error ||
        importQuery.error ||
        lotsQuery.error) && (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900"
        >
          {
            (
              preview.error ??
              correction.error ??
              publish.error ??
              adjustment.error ??
              importQuery.error ??
              lotsQuery.error
            )?.message
          }
        </p>
      )}
      {importNotice && (
        <p
          role="status"
          className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900"
        >
          {importNotice}
        </p>
      )}

      <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">
          Stage a supplied lot CSV
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          <label className="grid gap-1 text-sm font-medium">
            Account
            <select
              className="rounded-lg border border-slate-300 p-2"
              value={selectedAccountId}
              onChange={(event) => setAccountId(event.target.value)}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Source label
            <input
              className="rounded-lg border border-slate-300 p-2"
              value={sourceLabel}
              onChange={(event) => setSourceLabel(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm font-medium">
            CSV file
            <input
              className="rounded-lg border border-slate-300 p-2"
              type="file"
              accept=".csv,text/csv"
              onChange={async (event) => {
                const selected = event.target.files?.[0] ?? null
                setFile(selected)
                const found = selected
                  ? csvHeaders(await selected.slice(0, 128_000).text())
                  : []
                setHeaders(found)
                setMapping(initialMapping(found))
              }}
            />
          </label>
        </div>
        {headers.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {IMPORT_FIELDS.map(({ key, label, required }) => (
              <label
                key={key}
                className="grid gap-1 text-xs font-medium text-slate-700"
              >
                {label}
                {required ? ' · required' : ''}
                <select
                  className="rounded-lg border border-slate-300 p-2 text-sm"
                  value={mapping[key] ?? ''}
                  onChange={(event) =>
                    setMapping((current) => ({
                      ...current,
                      [key]: event.target.value,
                    }))
                  }
                >
                  <option value="">Not supplied</option>
                  {headers.map((header) => (
                    <option key={`${key}-${header}`} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <button
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            type="button"
            disabled={preview.isPending || !file || !selectedAccountId}
            onClick={() => preview.mutate()}
          >
            {preview.isPending ? 'Staging…' : 'Stage for review'}
          </button>
          <p className="text-xs text-slate-500">
            The original CSV is kept in private local storage. Uploads are
            limited by the configured file and row caps.
          </p>
        </div>
      </section>

      {review && (
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                Import review · {review.source_label}
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                {review.row_count} rows · revision {review.review_revision} ·{' '}
                {review.status}
              </p>
            </div>
            <p className="font-mono text-xs text-slate-500">
              SHA-256 {review.file_sha256}
            </p>
          </div>
          {review.gaps.map((gap) => (
            <p
              key={gap}
              className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900"
            >
              {gap}
            </p>
          ))}
          {review.quantity_differences.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                  <tr>
                    <th className="p-2">Security</th>
                    <th className="p-2">Accepted position</th>
                    <th className="p-2">Lot quantity</th>
                    <th className="p-2">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {review.quantity_differences.map((item) => (
                    <tr
                      className="border-t border-slate-100"
                      key={item.security_id}
                    >
                      <td className="p-2">{item.ticker ?? item.security_id}</td>
                      <td className="p-2">
                        {displayed(item.position_quantity)}
                      </td>
                      <td className="p-2">{item.lot_quantity}</td>
                      <td className="p-2 font-medium">
                        {displayed(item.difference)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="space-y-3">
            {visibleRows.map((row) => (
              <ReviewRow
                key={`${row.id}-${review.review_revision}`}
                row={row}
                review={review}
                securities={securities}
                busy={correction.isPending}
                onCorrect={(data) => correction.mutate({ rowId: row.id, data })}
              />
            ))}
          </div>
          {rows.length > 50 && (
            <div className="flex items-center gap-3 text-sm">
              <button
                className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50"
                disabled={page === 0}
                onClick={() => setPage((current) => current - 1)}
              >
                Previous
              </button>
              <span>
                Rows {page * 50 + 1}–{Math.min((page + 1) * 50, rows.length)} of{' '}
                {rows.length}
              </span>
              <button
                className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50"
                disabled={(page + 1) * 50 >= rows.length}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </button>
            </div>
          )}
          {review.status === 'review' && (
            <div className="space-y-3 border-t border-slate-200 pt-4">
              {(needsAcknowledgement || blockingRows) && (
                <label className="flex items-start gap-2 text-sm text-amber-900">
                  <input
                    className="mt-1"
                    type="checkbox"
                    checked={acknowledgeDifferences}
                    onChange={(event) =>
                      setAcknowledgeDifferences(event.target.checked)
                    }
                  />
                  <span>
                    I reviewed the displayed position differences and coverage
                    gaps. This confirms an acknowledged discrepancy; it does not
                    alter the accepted position.
                  </span>
                </label>
              )}
              <label className="grid max-w-xl gap-1 text-sm font-medium">
                Publication reason
                <input
                  className="rounded-lg border border-slate-300 p-2"
                  value={publishReason}
                  onChange={(event) => setPublishReason(event.target.value)}
                />
              </label>
              <button
                className="rounded-lg bg-cyan-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                type="button"
                disabled={
                  publish.isPending ||
                  blockingRows ||
                  (needsAcknowledgement && !acknowledgeDifferences)
                }
                onClick={() => publish.mutate()}
              >
                {publish.isPending ? 'Publishing…' : 'Publish reviewed lots'}
              </button>
              {blockingRows && (
                <p className="text-sm text-amber-800">
                  Resolve every row marked needs review before publication.
                  Duplicate rows will be skipped.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-900">
            Published lots for this account
          </h2>
          <label className="grid gap-1 text-xs font-medium text-slate-700">
            Evidence quality
            <select
              className="rounded-lg border border-slate-300 p-2 text-sm"
              value={lotQuality}
              onChange={(event) =>
                setLotQuality(event.target.value as typeof lotQuality)
              }
            >
              <option value="all">All lots</option>
              <option value="reported">Complete source fields</option>
              <option value="incomplete">Missing source fields</option>
            </select>
          </label>
        </div>
        {lotRows.length === 0 ? (
          <p className="text-sm text-slate-600">
            No published lots match this account and evidence filter.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                <tr>
                  <th className="p-2">Security / lot</th>
                  <th className="p-2">Acquired</th>
                  <th className="p-2">Current quantity</th>
                  <th className="p-2">Current basis</th>
                  <th className="p-2">Quality / source</th>
                </tr>
              </thead>
              <tbody>
                {lotRows.map((lot) => (
                  <tr className="border-t border-slate-100" key={lot.id}>
                    <td className="p-2">
                      <span className="font-semibold">
                        {lot.ticker ?? lot.security_name}
                      </span>
                      <span className="block text-xs text-slate-500">
                        {lot.source_lot_id ?? lot.id}
                      </span>
                    </td>
                    <td className="p-2">{lot.acquired_at ?? 'Unavailable'}</td>
                    <td className="p-2">{lot.current_remaining_quantity}</td>
                    <td className="p-2">
                      {lot.current_remaining_basis === null
                        ? 'Unavailable'
                        : `${lot.current_remaining_basis} ${lot.basis_currency ?? ''}`}
                    </td>
                    <td className="p-2">
                      {lot.quality_status}
                      <span className="block text-xs text-slate-500">
                        {lot.source_label}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {lotRows.length > 0 && (
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">
            Record a source-backed lot adjustment
          </h2>
          <p className="text-sm text-slate-600">
            Adjustments append to the original imported values. Each needs a
            date, source and reason; unsupported basis changes remain
            unavailable.
          </p>
          <form
            className="grid gap-3 md:grid-cols-3"
            onSubmit={(event) => {
              event.preventDefault()
              adjustment.mutate()
            }}
          >
            <label className="grid gap-1 text-sm font-medium">
              Tax lot
              <select
                className="rounded-lg border border-slate-300 p-2"
                value={adjustmentLotId}
                onChange={(event) => {
                  setAdjustmentLotId(event.target.value)
                  const selected = lotRows.find(
                    (lot) => lot.id === event.target.value,
                  )
                  setAdjustmentCurrency(selected?.basis_currency ?? '')
                }}
              >
                <option value="">Select a published lot</option>
                {lotRows.map((lot) => (
                  <option key={lot.id} value={lot.id}>
                    {lot.ticker ?? lot.security_name} ·{' '}
                    {lot.source_lot_id ?? lot.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Adjustment type
              <select
                className="rounded-lg border border-slate-300 p-2"
                value={adjustmentType}
                onChange={(event) =>
                  setAdjustmentType(event.target.value as typeof adjustmentType)
                }
              >
                <option value="correction">Correction</option>
                <option value="split">Split</option>
                <option value="basis_adjustment">Basis adjustment</option>
                <option value="return_of_capital">Return of capital</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Effective date
              <input
                className="rounded-lg border border-slate-300 p-2"
                type="date"
                max={today()}
                value={adjustmentDate}
                onChange={(event) => setAdjustmentDate(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Quantity change
              <input
                className="rounded-lg border border-slate-300 p-2"
                inputMode="decimal"
                value={quantityDelta}
                onChange={(event) => setQuantityDelta(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Basis change
              <input
                className="rounded-lg border border-slate-300 p-2"
                inputMode="decimal"
                value={basisDelta}
                onChange={(event) => setBasisDelta(event.target.value)}
                disabled={Boolean(
                  selectedAdjustmentLot &&
                  selectedAdjustmentLot.current_remaining_basis === null,
                )}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Basis currency
              <input
                className="rounded-lg border border-slate-300 p-2"
                maxLength={3}
                value={adjustmentCurrency}
                onChange={(event) =>
                  setAdjustmentCurrency(event.target.value.toUpperCase())
                }
              />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Source
              <input
                className="rounded-lg border border-slate-300 p-2"
                value={adjustmentSource}
                onChange={(event) => setAdjustmentSource(event.target.value)}
                required
              />
            </label>
            <label className="grid gap-1 text-sm font-medium md:col-span-2">
              Reason
              <input
                className="rounded-lg border border-slate-300 p-2"
                value={adjustmentReason}
                onChange={(event) => setAdjustmentReason(event.target.value)}
                required
              />
            </label>
            <label className="grid gap-1 text-sm font-medium md:col-span-2">
              Evidence reference
              <input
                className="rounded-lg border border-slate-300 p-2"
                value={adjustmentEvidence}
                onChange={(event) => setAdjustmentEvidence(event.target.value)}
              />
            </label>
            <button
              className="self-end rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              type="submit"
              disabled={adjustment.isPending || !adjustmentLotId}
            >
              {adjustment.isPending ? 'Saving…' : 'Append adjustment'}
            </button>
          </form>
        </section>
      )}
    </section>
  )
}
