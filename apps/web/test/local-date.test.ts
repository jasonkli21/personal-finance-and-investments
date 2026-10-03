import { describe, expect, it } from 'vitest'
import { localDate, localDateTime } from '../src/local-date'

describe('local calendar controls', () => {
  it('uses calendar components rather than converting the instant to UTC', () => {
    const evening = new Date(2026, 9, 3, 23, 40)
    expect(localDate(evening)).toBe('2026-10-03')
    expect(localDateTime(evening)).toBe('2026-10-03T23:40')
  })

  it('pads single-digit month, day, hour and minute', () => {
    expect(localDateTime(new Date(2026, 0, 2, 3, 4))).toBe('2026-01-02T03:04')
  })
})
