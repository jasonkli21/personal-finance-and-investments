import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import {
  createReport,
  fetchAccounts,
  fetchBreakdown,
  fetchReport,
  fetchReportRows,
} from './api/client'
import type { components } from './api/schema'
import { decimalDisplay } from './decimal-display'

type Row =
  | components['schemas']['OwnedReportLine']
  | components['schemas']['ExposureRowRead']
type View = 'owned' | 'security' | 'issuer'
const box = 'rounded-xl border border-slate-200 bg-white p-5 space-y-3'
const control = 'rounded border border-slate-300 px-3 py-2'

export default function ReportWorkspace() {
  const [id, setId] = useState(
    () => new URL(location.href).searchParams.get('report') ?? '',
  )
  const [accounts, setAccounts] = useState<string[]>([])
  const [asOf, setAsOf] = useState('')
  const [view, setView] = useState<View>('security')
  const [q, setQ] = useState('')
  const [source, setSource] = useState('')
  const [offset, setOffset] = useState(0)
  const [sort, setSort] = useState<'label' | 'value'>('value')
  const [descending, setDescending] = useState(true)
  const [target, setTarget] = useState<{
    id: string
    level: 'security' | 'issuer' | 'category'
  } | null>(null)
  const [detailOffset, setDetailOffset] = useState(0)
  const accountQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })
  const report = useQuery({
    queryKey: ['report', id],
    queryFn: () => fetchReport(id),
    enabled: !!id,
  })
  const rows = useQuery({
    queryKey: ['report-rows', id, view, offset, q, source, sort, descending],
    queryFn: () =>
      fetchReportRows(id, view, offset, q, source, sort, descending),
    enabled: !!id,
  })
  const detail = useQuery({
    queryKey: ['report-detail', id, target, detailOffset],
    queryFn: () => fetchBreakdown(id, target!.id, target!.level, detailOffset),
    enabled: !!id && !!target,
  })
  const generate = useMutation({
    mutationFn: () =>
      createReport({
        account_ids: accounts,
        include_archived: false,
        as_of: asOf ? new Date(asOf).toISOString() : null,
      }),
    onSuccess: (data) => {
      setId(data.id)
      setOffset(0)
      setTarget(null)
      const url = new URL(location.href)
      url.searchParams.set('report', data.id)
      history.replaceState(null, '', url)
    },
  })
  const columns: ColumnDef<Row>[] = [
    {
      accessorKey: 'label',
      header: 'Security / issuer',
      cell: ({ row }) =>
        'id' in row.original ? (
          <button
            className="underline text-blue-800"
            onClick={() => {
              setTarget({
                id: (row.original as components['schemas']['ExposureRowRead'])
                  .id,
                level: view === 'issuer' ? 'issuer' : 'security',
              })
              setDetailOffset(0)
            }}
          >
            {row.original.label}
          </button>
        ) : (
          row.original.label
        ),
    },
    {
      id: 'direct',
      header: 'Direct USD',
      cell: ({ row }) =>
        'direct' in row.original ? decimalDisplay(row.original.direct) : '—',
    },
    {
      id: 'indirect',
      header: 'ETF-derived USD',
      cell: ({ row }) =>
        'indirect' in row.original
          ? decimalDisplay(row.original.indirect)
          : '—',
    },
    {
      id: 'value',
      header: 'Value USD / original currency',
      cell: ({ row }) =>
        'total' in row.original
          ? decimalDisplay(row.original.total)
          : `${row.original.currency} ${decimalDisplay(row.original.value)}`,
    },
    {
      id: 'percentage',
      header: '% of total portfolio',
      cell: ({ row }) =>
        'percentage' in row.original
          ? decimalDisplay(row.original.percentage)
          : '—',
    },
    {
      id: 'status',
      header: 'Evidence',
      cell: ({ row }) =>
        'status' in row.original
          ? `${row.original.account_name} · ${row.original.status} · ${row.original.quality_status} · positions ${row.original.position_as_of} · price ${row.original.quote_as_of ?? 'unavailable'} · ${row.original.quote_source ?? 'unavailable'}`
          : 'Derived; select row for sources',
    },
  ]
  // TanStack v8 manages table state; this component does not use React Compiler.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: rows.data?.rows ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
  })
  return (
    <section className={box} aria-label="Portfolio reports">
      <h2 className="text-xl font-semibold">Portfolio reports</h2>
      <p>
        Create a frozen report from selected published snapshots and eligible
        dated prices. Refresh creates a new report; this report link survives
        reload.
      </p>
      <fieldset className="flex flex-wrap gap-4">
        <legend>
          Included accounts (none selected means all active accounts)
        </legend>
        {accountQuery.data
          ?.filter((a) => a.active)
          .map((a) => (
            <label key={a.id}>
              <input
                type="checkbox"
                checked={accounts.includes(a.id)}
                onChange={(e) =>
                  setAccounts(
                    e.target.checked
                      ? [...accounts, a.id]
                      : accounts.filter((x) => x !== a.id),
                  )
                }
              />{' '}
              {a.name}
            </label>
          ))}
      </fieldset>
      <label>
        Historical valuation (local time; optional){' '}
        <input
          aria-label="Historical valuation"
          type="datetime-local"
          className={control}
          value={asOf}
          onChange={(e) => setAsOf(e.target.value)}
        />
      </label>
      <button
        className={control}
        disabled={generate.isPending}
        onClick={() => generate.mutate()}
      >
        {generate.isPending ? 'Calculating…' : 'Create / refresh report'}
      </button>
      {(generate.error || report.error || rows.error) && (
        <p role="alert">
          {(generate.error || report.error || rows.error)?.message}
        </p>
      )}
      {report.isFetching && id && <p role="status">Loading frozen report…</p>}
      {report.data && (
        <>
          <p>
            Calculation {id} · {report.data.calculation_version} · valued{' '}
            {report.data.valuation_at} · generated {report.data.generated_at}
          </p>
          <p className="font-semibold">
            {report.data.nav_status === 'complete'
              ? 'Total portfolio NAV'
              : 'Included valued USD subtotal (incomplete NAV)'}
            : USD {decimalDisplay(report.data.included_valued_nav)}
          </p>
          <p>
            Security attribution {decimalDisplay(report.data.security_coverage)}
            % · issuer attribution {decimalDisplay(report.data.issuer_coverage)}
            % · resolved equity USD{' '}
            {decimalDisplay(report.data.attribution_numerator)} / valued USD{' '}
            {decimalDisplay(report.data.coverage_denominator)}
          </p>
          {!report.data.percentages_available && (
            <p>
              Portfolio percentages unavailable: incomplete, zero or signed
              allocation.
            </p>
          )}
          {report.data.warnings.map((w) => (
            <p key={w} className="text-amber-900">
              Warning: {w}
            </p>
          ))}
          <p>
            USD decomposition reconciles exactly to owned valued NAV. Display
            rounds to cents; displayed sums may differ by $0.01 per displayed
            row. Derived values never increase owned NAV.
          </p>
          <div className="flex flex-wrap gap-3">
            {(['owned', 'security', 'issuer'] as const).map((v) => (
              <button
                className={control}
                aria-pressed={view === v}
                key={v}
                onClick={() => {
                  setView(v)
                  setOffset(0)
                  setTarget(null)
                }}
              >
                {v === 'owned'
                  ? 'Owned positions'
                  : v === 'security'
                    ? 'Look-through exposure'
                    : 'Issuer exposure'}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-3">
            <label>
              Search report rows{' '}
              <input
                className={control}
                value={q}
                onChange={(e) => {
                  setQ(e.target.value)
                  setOffset(0)
                }}
              />
            </label>
            <label>
              Source filter{' '}
              <input
                className={control}
                value={source}
                onChange={(e) => {
                  setSource(e.target.value)
                  setOffset(0)
                }}
              />
            </label>
            <label>
              Sort{' '}
              <select
                className={control}
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value as 'label' | 'value')
                  setOffset(0)
                }}
              >
                <option value="value">Value (top exposures)</option>
                <option value="label">Name</option>
              </select>
            </label>
            <button
              className={control}
              onClick={() => {
                setDescending(!descending)
                setOffset(0)
              }}
            >
              {descending ? 'Descending' : 'Ascending'}
            </button>
          </div>
          <p>
            Search, source and paging filter rows only. Account selection
            changes NAV when a new report is created.
          </p>
          <div className="overflow-auto">
            <table className="w-full text-left text-sm">
              <thead>
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((h) => (
                      <th className="p-2" key={h.id}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr className="border-t" key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <td className="p-2" key={cell.id}>
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.isFetching && <p role="status">Loading rows…</p>}
          {rows.data?.total_rows === 0 && (
            <p>No matching rows. Cash and residuals remain below.</p>
          )}
          <p>
            {offset + 1}–{Math.min(offset + 50, rows.data?.total_rows ?? 0)} of{' '}
            {rows.data?.total_rows ?? 0} rows
          </p>
          <button
            className={control}
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Previous rows
          </button>{' '}
          <button
            className={control}
            disabled={offset + 50 >= (rows.data?.total_rows ?? 0)}
            onClick={() => setOffset(offset + 50)}
          >
            Next rows
          </button>
          <a
            className="underline text-blue-800"
            href={`/api/v1/portfolio/reports/${id}/export?${new URLSearchParams({ view, q, source })}`}
          >
            Export frozen CSV
          </a>
          <h3 className="font-semibold">
            Full portfolio decomposition / residuals
          </h3>
          <ul>
            {Object.entries(report.data.categories).map(([category, value]) => (
              <li key={category}>
                <button
                  className="underline"
                  onClick={() => {
                    setTarget({ id: category, level: 'category' })
                    setDetailOffset(0)
                  }}
                >
                  {category.replaceAll('_', ' ')}
                </button>
                : USD {decimalDisplay(value)}
              </li>
            ))}
          </ul>
          <p>
            <button
              className="underline"
              onClick={() => {
                setTarget({ id: 'issuer_unmapped', level: 'category' })
                setDetailOffset(0)
              }}
            >
              Issuer-unmapped resolved equity
            </button>
            : USD {decimalDisplay(report.data.issuer_unmapped_value)}. Issuer
            coverage excludes unmapped securities.
          </p>
          {target && (
            <section className={box} aria-label="Contribution breakdown">
              <h3 className="font-semibold">Contribution breakdown</h3>
              {detail.error && <p role="alert">{detail.error.message}</p>}
              {detail.isFetching && <p role="status">Loading contributions…</p>}
              <ul>
                {detail.data?.map((c, i) => (
                  <li className="border-b py-2" key={i}>
                    {c.account_name} · {c.owned_label} → {c.label} ·{' '}
                    {c.category}: USD {decimalDisplay(c.amount)}
                    {c.weight !== null && ` · weight ${c.weight}`}
                    <br />
                    Position {c.position_snapshot_id} as of {c.position_as_of} ·
                    quote {c.quote_as_of ?? 'unavailable'} /{' '}
                    {c.quote_source ?? 'unavailable'} / {c.quality_status}
                    {c.fund_snapshot_id && (
                      <>
                        <br />
                        Fund {c.fund_snapshot_id} · holdings {c.fund_as_of} ·
                        fetched {c.fund_fetched_at} · {c.fund_source} ·{' '}
                        {c.fund_quality}
                        {c.fund_stale && ' · STALE'}
                        {c.fund_source_url && (
                          <a href={c.fund_source_url} className="underline">
                            {' '}
                            Source
                          </a>
                        )}
                      </>
                    )}
                  </li>
                ))}
              </ul>
              <button
                className={control}
                disabled={!detailOffset}
                onClick={() => setDetailOffset(Math.max(0, detailOffset - 50))}
              >
                Previous contributions
              </button>{' '}
              <button
                className={control}
                disabled={(detail.data?.length ?? 0) < 50}
                onClick={() => setDetailOffset(detailOffset + 50)}
              >
                Next contributions
              </button>
            </section>
          )}
        </>
      )}
      {!id && (
        <p>
          No frozen report yet. Create accounts and reviewed positions, then
          create a report.
        </p>
      )}
    </section>
  )
}
