import { useEffect, useRef, useState, type ComponentType } from 'react'
import { useQueryClient } from '@tanstack/react-query'

type SessionState = { authenticated: boolean; local_mode: boolean }

async function readSession(signal: AbortSignal): Promise<SessionState> {
  const response = await fetch('/api/v1/auth/session', {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    signal,
  })
  if (response.status === 401)
    return { authenticated: false, local_mode: false }
  if (!response.ok) throw new Error('Authentication status is unavailable.')
  const state = (await response.json()) as unknown
  if (
    typeof state !== 'object' ||
    state === null ||
    !('authenticated' in state) ||
    typeof state.authenticated !== 'boolean' ||
    !('local_mode' in state) ||
    typeof state.local_mode !== 'boolean'
  ) {
    throw new Error('Authentication status is invalid.')
  }
  return { authenticated: state.authenticated, local_mode: state.local_mode }
}

async function signOut() {
  const response = await fetch('/api/v1/auth/logout', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (response.status === 401) return
  if (!response.ok) throw new Error('Sign-out could not be completed.')
}

export default function AuthenticationGate({
  workspace: Workspace,
}: {
  workspace: ComponentType<{ onLogout: () => void; authenticated: boolean }>
}) {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<SessionState | null>(null)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const request = useRef<AbortController | null>(null)

  useEffect(() => {
    let active = true
    const refresh = async () => {
      if (request.current) return
      const controller = new AbortController()
      request.current = controller
      const startedGeneration = generation.current
      const timeout = window.setTimeout(() => controller.abort(), 10_000)
      try {
        const current = await readSession(controller.signal)
        if (active && startedGeneration === generation.current) {
          if (!current.authenticated) queryClient.clear()
          setSession(current)
          setError('')
        }
      } catch {
        if (active && startedGeneration === generation.current)
          setError('The private session service is unavailable.')
      } finally {
        window.clearTimeout(timeout)
        if (request.current === controller) request.current = null
        if (active) setChecking(false)
      }
    }
    const expire = () => {
      // A successful response issued before expiry must never reopen the workspace.
      generation.current += 1
      request.current?.abort()
      request.current = null
      setSession({ authenticated: false, local_mode: false })
      queryClient.clear()
    }
    const onFocus = () => void refresh()
    window.addEventListener('finance:unauthorized', expire)
    window.addEventListener('focus', onFocus)
    const timer = window.setInterval(() => void refresh(), 60_000)
    void refresh()
    return () => {
      active = false
      request.current?.abort()
      request.current = null
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      window.removeEventListener('finance:unauthorized', expire)
    }
  }, [queryClient])

  async function logout() {
    setError('')
    try {
      await signOut()
      generation.current += 1
      request.current?.abort()
      request.current = null
      queryClient.clear()
      setSession({ authenticated: false, local_mode: false })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Sign-out failed.')
    }
  }

  if (checking && session === null) {
    return (
      <main className="mx-auto flex min-h-screen max-w-lg items-center px-5 py-10">
        <p className="text-sm text-slate-600" role="status">
          Checking private session…
        </p>
      </main>
    )
  }
  if (session?.authenticated) {
    return (
      <>
        {error && (
          <p
            className="mx-auto max-w-6xl rounded-lg bg-rose-50 p-3 text-sm text-rose-900"
            role="alert"
          >
            {error}
          </p>
        )}
        <Workspace onLogout={logout} authenticated={!session.local_mode} />
      </>
    )
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-5 py-10">
      <section className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">
          Private finance workspace
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
          Sign in
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Your financial workspace requires an active private session.
        </p>
        {error && (
          <p
            className="mt-5 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
            role="alert"
          >
            {error}
          </p>
        )}
        <button
          className="mt-6 w-full rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          type="button"
          onClick={() => window.location.assign('/api/v1/auth/login')}
        >
          Continue with identity provider
        </button>
      </section>
    </main>
  )
}
