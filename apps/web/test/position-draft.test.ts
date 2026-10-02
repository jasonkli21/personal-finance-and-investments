import { describe, expect, it } from 'vitest'
import { captureDraftBaseRevision } from '../src/position-draft'

describe('position draft revision', () => {
  it('keeps the original base after another tab saves and a background refetch advances server state', () => {
    let capturedBase: number | undefined

    // First tab reads revision 1 and starts an edit.
    capturedBase = captureDraftBaseRevision(capturedBase, 1)
    expect(capturedBase).toBe(1)

    // Second tab saves revision 2; a window-focus refetch sees it. Capturing
    // again must not silently rebase the first tab's draft to revision 2.
    const refreshedServerRevision = 2
    capturedBase = captureDraftBaseRevision(
      capturedBase,
      refreshedServerRevision,
    )

    expect(capturedBase).toBe(1)
  })
})
