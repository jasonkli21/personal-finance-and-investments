import { useEffect, useState } from 'react'
import { startReadinessPolling, type ApiStatus } from './readiness'

export default function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')

  useEffect(() => {
    return startReadinessPolling({ onStatus: setApiStatus })
  }, [])

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-6 px-6 py-16">
      <p className="text-sm font-semibold tracking-wide text-slate-500">
        LOCAL DEVELOPMENT
      </p>
      <h1 className="text-4xl font-semibold tracking-tight text-slate-900">
        Portfolio Intelligence
      </h1>
      <p className="max-w-xl text-lg leading-relaxed text-slate-600">
        Stage 0 foundation. Accounts, holdings, and look-through exposure will
        arrive in later work packages.
      </p>
      <p className="text-sm text-slate-600" role="status">
        API and database: {apiStatus}
      </p>
    </main>
  )
}
