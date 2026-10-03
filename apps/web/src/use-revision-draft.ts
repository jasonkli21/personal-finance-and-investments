import { useState } from 'react'

type RevisionDraft<T> = { value: T; revision: number }

/** Refetches update pristine forms; edited forms keep their original evidence and revision. */
export function useRevisionDraft<T>(
  source: T,
  revision: number,
  onDirty?: () => void,
) {
  const [draft, setDraft] = useState<RevisionDraft<T> | null>(null)
  return {
    value: draft?.value ?? source,
    revision: draft?.revision ?? revision,
    dirty: draft !== null,
    update(patch: Partial<T>) {
      onDirty?.()
      setDraft((current) => ({
        value: { ...(current?.value ?? source), ...patch },
        revision: current?.revision ?? revision,
      }))
    },
    discard() {
      setDraft(null)
    },
  }
}
