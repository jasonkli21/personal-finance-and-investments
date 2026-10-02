/** Keep a dirty draft tied to the server revision it was created from. */
export function captureDraftBaseRevision(
  capturedRevision: number | undefined,
  serverRevision: number,
): number {
  return capturedRevision ?? serverRevision
}
