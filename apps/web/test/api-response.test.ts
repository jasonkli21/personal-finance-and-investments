import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, readJsonResponse, unwrap } from '../src/api/response'

describe('API errors', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('retains HTTP status and safe server error details', async () => {
    const response = new Response(
      JSON.stringify({ detail: 'Review revision changed.' }),
      { status: 409 },
    )
    const error = await readJsonResponse(response, 'Upload failed.').catch(
      (cause: unknown) => cause,
    )
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 409,
      message: 'Review revision changed.',
    })
  })

  it('shows FastAPI validation messages without echoing raw submitted input', async () => {
    await expect(
      unwrap({
        response: new Response('', { status: 422 }),
        error: {
          detail: [
            {
              loc: ['body', 'amount'],
              msg: 'Expected a decimal string',
              input: 'private amount',
            },
          ],
        },
      }),
    ).rejects.toMatchObject({
      status: 422,
      message: 'body.amount: Expected a decimal string',
    })
  })

  it('maps an HTML gateway failure to the operation fallback', async () => {
    await expect(
      readJsonResponse(
        new Response('<h1>Bad gateway</h1>', { status: 502 }),
        'Statement review could not be started.',
      ),
    ).rejects.toMatchObject({
      status: 502,
      message: 'Statement review could not be started.',
    })
  })

  it('expires authentication even when a 401 response has no JSON body', async () => {
    const dispatchEvent = vi.fn()
    vi.stubGlobal('window', { dispatchEvent })
    await expect(
      readJsonResponse(new Response('', { status: 401 }), 'Sign in again.'),
    ).rejects.toMatchObject({ status: 401 })
    expect(dispatchEvent).toHaveBeenCalledOnce()
    expect(dispatchEvent.mock.calls[0][0].type).toBe('finance:unauthorized')
  })

  it('rejects missing or malformed successful responses', async () => {
    await expect(unwrap({ response: new Response('') })).rejects.toThrow(
      'The server returned no data.',
    )
    await expect(
      readJsonResponse(new Response('broken'), 'Failed.'),
    ).rejects.toThrow('The server returned invalid JSON.')
    await expect(
      readJsonResponse(new Response('null'), 'Failed.'),
    ).rejects.toThrow('The server returned no data.')
  })
})
