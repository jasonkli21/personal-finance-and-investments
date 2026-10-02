import { describe, expect, it } from 'vitest'

import { resolveApiPort } from '../src/dev-config'

describe('resolveApiPort', () => {
  it('uses API_PORT from root env files when the shell does not override it', () => {
    expect(resolveApiPort({ API_PORT: '8123' }, {})).toBe(8123)
  })

  it('gives shell API_PORT precedence over root env files', () => {
    expect(resolveApiPort({ API_PORT: '8123' }, { API_PORT: '9123' })).toBe(
      9123,
    )
  })

  it('defaults API_PORT to the local API port', () => {
    expect(resolveApiPort({}, {})).toBe(8000)
  })

  it('rejects invalid API_PORT values', () => {
    for (const value of ['0', '65536', '8000x', '']) {
      expect(() => resolveApiPort({}, { API_PORT: value })).toThrow(/API_PORT/)
    }
  })
})
