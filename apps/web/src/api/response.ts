export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function noteAuthenticationFailure(response: Response) {
  if (response.status === 401 && typeof window !== 'undefined') {
    window.dispatchEvent(new Event('finance:unauthorized'))
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (typeof body !== 'object' || body === null || !('detail' in body))
    return fallback
  const detail = body.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (!Array.isArray(detail)) return fallback
  // FastAPI validation errors also contain raw submitted values; show only the
  // field path and safe validation message, never echo the financial payload.
  const messages = detail.flatMap((issue: unknown) => {
    if (
      typeof issue !== 'object' ||
      issue === null ||
      !('msg' in issue) ||
      typeof issue.msg !== 'string'
    )
      return []
    const location =
      'loc' in issue && Array.isArray(issue.loc)
        ? issue.loc
            .filter(
              (part: unknown) =>
                typeof part === 'string' || typeof part === 'number',
            )
            .join('.')
        : ''
    return [location ? `${location}: ${issue.msg}` : issue.msg]
  })
  return messages.length ? messages.join('; ') : fallback
}

export async function unwrap<T>(result: {
  data?: T
  error?: unknown
  response: Response
}): Promise<T> {
  if (!result.response.ok) {
    noteAuthenticationFailure(result.response)
    throw new ApiError(
      result.response.status,
      errorMessage(result.error, 'The request could not be completed.'),
    )
  }
  if (result.data === undefined)
    throw new ApiError(result.response.status, 'The server returned no data.')
  return result.data
}

/** Upload endpoints use raw bodies, but share JSON/error semantics with the generated client. */
export async function readJsonResponse<T>(
  response: Response,
  fallback: string,
): Promise<T> {
  noteAuthenticationFailure(response)
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError(
      response.status,
      response.ok ? 'The server returned invalid JSON.' : fallback,
    )
  }
  if (!response.ok)
    throw new ApiError(response.status, errorMessage(body, fallback))
  if (body === null || body === undefined)
    throw new ApiError(response.status, 'The server returned no data.')
  return body as T
}
