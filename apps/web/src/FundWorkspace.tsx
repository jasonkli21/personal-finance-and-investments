import { localDate } from './local-date'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelImport,
  correctFundRow,
  fetchFundSnapshots,
  fetchImport,
  fetchSecurities,
  previewFundImport,
  publishFundImport,
} from './api/client'

export default function FundWorkspace() {
  const queries = useQueryClient()
  const catalog = useQuery({
    queryKey: ['securities'],
    queryFn: fetchSecurities,
  })
  const [fund, setFund] = useState('')
  const [format, setFormat] = useState('manual')
  const [date, setDate] = useState(localDate)
  const [unit, setUnit] = useState('percent')
  const [file, setFile] = useState<File | null>(null)
  const [identifier, setIdentifier] = useState('ticker')
  const [weight, setWeight] = useState('weight')
  const [assetClass, setAssetClass] = useState('type')
  const [importId, setImportId] = useState('')
  const [page, setPage] = useState(0)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Record<string, string>>({})
  const [baseRevisions, setBaseRevisions] = useState<Record<string, number>>({})
  function captureBase(rowId: string) {
    setBaseRevisions((previous) => ({
      ...previous,
      [rowId]: previous[rowId] ?? review.data?.review_revision ?? 0,
    }))
  }
  const [weights, setWeights] = useState<Record<string, string>>({})
  const review = useQuery({
    queryKey: ['fund-review', importId],
    queryFn: () => fetchImport(importId),
    enabled: !!importId,
  })
  const history = useQuery({
    queryKey: ['fund-history', fund],
    queryFn: () => fetchFundSnapshots(fund),
    enabled: !!fund,
  })
  async function refresh() {
    await queries.invalidateQueries({ queryKey: ['fund-review', importId] })
    await queries.invalidateQueries({ queryKey: ['fund-history', fund] })
  }
  const upload = useMutation({
    mutationFn: async () => {
      if (!file || !fund) throw new Error('Choose a fund and holdings file')
      return previewFundImport({
        fundId: fund,
        date,
        format,
        unit,
        file,
        mapping: {
          identifier,
          weight,
          ...(assetClass ? { asset_type: assetClass } : {}),
        },
      })
    },
    onSuccess: (result) => {
      setImportId(result.id)
      setBaseRevisions({})
      setWeights({})
      setSelected({})
      setPage(0)
      setError('')
    },
    onError: (e) => setError(e.message),
  })
  const accept = useMutation({
    mutationFn: () => {
      if (Object.keys(baseRevisions).length)
        throw new Error(
          'Save corrections or discard fund drafts before accepting.',
        )
      return publishFundImport(importId, review.data?.review_revision ?? 0)
    },
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  })
  const cancel = useMutation({
    mutationFn: () => cancelImport(importId, review.data?.review_revision ?? 0),
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  })
  const correct = useMutation({
    mutationFn: ({
      rowId,
      security,
      weightValue,
    }: {
      rowId: string
      security: string
      weightValue: string
    }) =>
      correctFundRow(importId, rowId, {
        expected_review_revision:
          baseRevisions[rowId] ?? review.data?.review_revision ?? 0,
        reason: 'Reviewed in composition table',
        ...(security ? { security_id: security } : {}),
        ...(weightValue ? { weight: weightValue } : {}),
      }),
    onSuccess: async (_result, { rowId }) => {
      const remove = <T,>(values: Record<string, T>) =>
        Object.fromEntries(
          Object.entries(values).filter(([key]) => key !== rowId),
        )
      setBaseRevisions(remove)
      setWeights(remove)
      setSelected(remove)
      await refresh()
    },
    onError: (e) => setError(e.message),
  })
  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">ETF compositions</h2>
      <p>
        Upload full holdings, confirm their effective date, then review and
        accept. Unknown constituents remain visible in residual exposure.
        Negative, leveraged or overweight files remain opaque.
      </p>
      <div className="flex flex-wrap gap-4">
        <label>
          Fund
          <select
            aria-label="Fund composition security"
            value={fund}
            disabled={
              upload.isPending ||
              accept.isPending ||
              cancel.isPending ||
              correct.isPending
            }
            onChange={(e) => {
              setBaseRevisions({})
              setWeights({})
              setSelected({})
              setFund(e.target.value)
              setImportId('')
            }}
          >
            <option value="">Choose ETF</option>
            {catalog.data
              ?.filter((s) => s.security_type === 'etf')
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.display_ticker ?? s.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Format
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="manual">Generic CSV</option>
            <option value="ishares">iShares IVV CSV</option>
            <option value="spdr">SPDR SPY Excel</option>
          </select>
        </label>
        <label>
          Holdings as of
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label>
          Holdings file
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
      </div>
      {format === 'manual' && (
        <fieldset className="flex flex-wrap gap-3">
          <legend>Map exact CSV column names</legend>
          <label>
            Identifier column
            <input
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
            />
          </label>
          <label>
            Weight column
            <input value={weight} onChange={(e) => setWeight(e.target.value)} />
          </label>
          <label>
            Class column
            <input
              value={assetClass}
              onChange={(e) => setAssetClass(e.target.value)}
            />
          </label>
          <label>
            Weight unit
            <select value={unit} onChange={(e) => setUnit(e.target.value)}>
              <option value="percent">Percent (8)</option>
              <option value="decimal">Decimal (0.08)</option>
            </select>
          </label>
        </fieldset>
      )}
      <button
        disabled={upload.isPending || !file || !fund}
        onClick={() => upload.mutate()}
      >
        Preview fund holdings
      </button>
      {error && <p role="alert">{error}</p>}
      {review.data && (
        <div className="space-y-3">
          <p>
            Review revision {review.data.review_revision} · {review.data.status}{' '}
            · {review.data.row_count} source rows · {review.data.effective_date}
          </p>
          <p>
            All source rows are retained. Accepting acknowledges unresolved
            identifiers and unusual weights.
          </p>
          <div className="overflow-auto">
            <table>
              <thead>
                <tr>
                  <th>Source identifier/class</th>
                  <th>Raw weight/unit</th>
                  <th>Normalized decimal</th>
                  <th>Match</th>
                  <th>Correction</th>
                </tr>
              </thead>
              <tbody>
                {review.data.rows
                  .slice(page * 50, page * 50 + 50)
                  .map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.raw_identifier ?? row.raw_name} ·{' '}
                        {row.raw_asset_type}
                      </td>
                      <td>
                        {row.raw_weight_value} {row.raw_weight_unit}
                      </td>
                      <td>{row.normalized_weight ?? 'Invalid'}</td>
                      <td>
                        {row.security_label ?? 'Unresolved'}
                        <select
                          aria-label={`Resolve fund row ${row.row_number}`}
                          value={selected[row.id] ?? row.security_id ?? ''}
                          onChange={(e) => {
                            captureBase(row.id)
                            setSelected({
                              ...selected,
                              [row.id]: e.target.value,
                            })
                          }}
                        >
                          <option value="">Keep unresolved</option>
                          {catalog.data?.map((s) => (
                            <option value={s.id} key={s.id}>
                              {s.display_ticker ?? s.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          aria-label={`Correct fund weight ${row.row_number}`}
                          placeholder="Decimal weight"
                          value={weights[row.id] ?? ''}
                          onChange={(e) => {
                            captureBase(row.id)
                            setWeights({ ...weights, [row.id]: e.target.value })
                          }}
                        />
                        <button
                          disabled={
                            correct.isPending ||
                            review.data?.status !== 'review'
                          }
                          onClick={() =>
                            correct.mutate({
                              rowId: row.id,
                              security: selected[row.id] ?? '',
                              weightValue: weights[row.id] ?? '',
                            })
                          }
                        >
                          Save correction
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous fund rows
          </button>
          <button
            disabled={(page + 1) * 50 >= review.data.row_count}
            onClick={() => setPage(page + 1)}
          >
            Next fund rows
          </button>
          <button
            onClick={() => {
              setBaseRevisions({})
              setWeights({})
              setSelected({})
              void refresh()
            }}
          >
            Discard fund drafts and reload review
          </button>
          <button
            disabled={accept.isPending || review.data.status !== 'review'}
            onClick={() => accept.mutate()}
          >
            Accept fund composition
          </button>
          <button
            disabled={cancel.isPending || review.data.status !== 'review'}
            onClick={() => cancel.mutate()}
          >
            Cancel fund review
          </button>
        </div>
      )}
      <h3 className="font-semibold">Published composition history</h3>
      <ul>
        {history.data?.map((s) => (
          <li key={s.id}>
            {s.as_of} · {s.source} · {s.quality_status} · reported weight{' '}
            {s.reported_weight} · recognized {s.recognized_weight} ·{' '}
            {s.row_count} rows {s.warnings.join(', ')}{' '}
            {s.source_url && (
              <a href={s.source_url} target="_blank" rel="noreferrer">
                Source
              </a>
            )}
          </li>
        ))}
      </ul>
      <p>
        Automatic network refresh is disabled pending verified access rights.
        Official-download uploads and cached compositions work offline.
      </p>
    </section>
  )
}
