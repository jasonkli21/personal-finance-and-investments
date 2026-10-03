import { describe, expect, it } from 'vitest'
import { createSubmissionKey } from '../src/submission-key'

describe('write submission identity', () => {
  it('reuses the same identity when an unchanged write is retried after an uncertain response', () => {
    const store = createSubmissionKey()
    const first = store.forPayload({ lot: 'synthetic-lot', quantity: '1.25' })
    expect(store.forPayload({ lot: 'synthetic-lot', quantity: '1.25' })).toBe(
      first,
    )
    expect(
      store.forPayload({ lot: 'synthetic-lot', quantity: '1.5' }),
    ).not.toBe(first)
  })

  it('permits a distinct intentional write after the prior write succeeds', () => {
    const store = createSubmissionKey()
    const first = store.forPayload({ amount: '100' })
    store.reset()
    expect(store.forPayload({ amount: '100' })).not.toBe(first)
  })
})
