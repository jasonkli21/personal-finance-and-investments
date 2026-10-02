import { afterEach, describe, expect, it, vi } from 'vitest'

import { startReadinessPolling } from '../src/readiness'

describe('startReadinessPolling', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('retries a timed out readiness request and can recover', async () => {
    vi.useFakeTimers()
    const statuses: Array<'ready' | 'unavailable'> = []
    let calls = 0
    const stop = startReadinessPolling({
      intervalMs: 5,
      timeoutMs: 15,
      onStatus: (status) => statuses.push(status),
      fetcher: (_url, { signal }) => {
        calls += 1
        if (calls === 1) {
          return new Promise((_, reject) => {
            signal.addEventListener(
              'abort',
              () => reject(new DOMException('Aborted', 'AbortError')),
              { once: true },
            )
          })
        }
        return Promise.resolve({ ok: true })
      },
    })

    await vi.advanceTimersByTimeAsync(20)
    stop()

    expect(statuses.slice(0, 2)).toEqual(['unavailable', 'ready'])
    expect(calls).toBe(2)
  })

  it('updates status when a ready service becomes unavailable without overlapping requests', async () => {
    vi.useFakeTimers()
    const statuses: Array<'ready' | 'unavailable'> = []
    let activeRequests = 0
    let maxActiveRequests = 0
    let calls = 0
    const stop = startReadinessPolling({
      intervalMs: 5,
      timeoutMs: 100,
      onStatus: (status) => statuses.push(status),
      fetcher: async () => {
        activeRequests += 1
        maxActiveRequests = Math.max(maxActiveRequests, activeRequests)
        calls += 1
        await new Promise<void>((resolve) => setTimeout(resolve, 8))
        activeRequests -= 1
        return { ok: calls === 1 }
      },
    })

    await vi.advanceTimersByTimeAsync(21)
    stop()

    expect(statuses).toEqual(['ready', 'unavailable'])
    expect(maxActiveRequests).toBe(1)
  })

  it('aborts the active request on cleanup and prevents further requests or status updates', async () => {
    vi.useFakeTimers()
    const statuses: Array<'ready' | 'unavailable'> = []
    let calls = 0
    let signal: AbortSignal | undefined
    const stop = startReadinessPolling({
      intervalMs: 5,
      timeoutMs: 100,
      onStatus: (status) => statuses.push(status),
      fetcher: (_url, init) => {
        calls += 1
        signal = init.signal
        return new Promise(() => {})
      },
    })

    await Promise.resolve()
    stop()
    await vi.advanceTimersByTimeAsync(20)

    expect(signal?.aborted).toBe(true)
    expect(calls).toBe(1)
    expect(statuses).toEqual([])
  })
})
