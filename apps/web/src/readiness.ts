export type ApiStatus = 'checking' | 'ready' | 'unavailable'

type ReadinessResponse = { ok: boolean }
type ReadinessFetch = (
  input: string,
  init: { signal: AbortSignal },
) => Promise<ReadinessResponse>

type ReadinessPollingOptions = {
  onStatus: (status: Exclude<ApiStatus, 'checking'>) => void
  fetcher?: ReadinessFetch
  intervalMs?: number
  timeoutMs?: number
}

const DEFAULT_INTERVAL_MS = 5_000
const DEFAULT_TIMEOUT_MS = 2_000

/** Poll readiness serially so transient startup and database failures are visible and recoverable. */
export function startReadinessPolling({
  onStatus,
  fetcher = fetch,
  intervalMs = DEFAULT_INTERVAL_MS,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}: ReadinessPollingOptions): () => void {
  let stopped = false
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let cancelRequest: (() => void) | undefined

  const poll = async () => {
    const controller = new AbortController()
    let timeoutTimer: ReturnType<typeof setTimeout> | undefined
    let rejectCancellation: ((reason?: unknown) => void) | undefined
    const cancellation = new Promise<never>((_, reject) => {
      rejectCancellation = reject
      timeoutTimer = setTimeout(() => {
        controller.abort()
        reject(new Error('Readiness request timed out'))
      }, timeoutMs)
    })

    cancelRequest = () => {
      if (timeoutTimer !== undefined) clearTimeout(timeoutTimer)
      controller.abort()
      rejectCancellation?.(new Error('Readiness polling stopped'))
    }

    try {
      const response = await Promise.race([
        fetcher('/api/health/ready', { signal: controller.signal }),
        cancellation,
      ])
      if (!response.ok) throw new Error('API readiness check failed')
      if (!stopped) onStatus('ready')
    } catch {
      if (!stopped) onStatus('unavailable')
    } finally {
      if (timeoutTimer !== undefined) clearTimeout(timeoutTimer)
      cancelRequest = undefined
      if (!stopped) pollTimer = setTimeout(() => void poll(), intervalMs)
    }
  }

  void poll()

  return () => {
    stopped = true
    if (pollTimer !== undefined) clearTimeout(pollTimer)
    cancelRequest?.()
  }
}
