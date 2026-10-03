/** Keep retries of an unchanged submission from duplicating a committed write. */
export function createSubmissionKey() {
  let previousPayload: string | undefined
  let key: string | undefined
  return {
    forPayload(payload: unknown): string {
      const serialized = JSON.stringify(payload)
      if (key === undefined || serialized !== previousPayload) {
        previousPayload = serialized
        key = crypto.randomUUID()
      }
      return key
    },
    reset() {
      key = undefined
      previousPayload = undefined
    },
  }
}
