import { describe, expect, it } from 'vitest'
import { parseCsvHeader } from '../src/csv-headers'

describe('CSV mapping headers', () => {
  it('reads only the first record and preserves quoted commas and escaped quotes', () => {
    expect(
      parseCsvHeader(
        '\uFEFFticker,"security, name","quote ""date"""\r\nNVDA,test,2026-10-01',
      ),
    ).toEqual(['ticker', 'security, name', 'quote "date"'])
  })

  it('accepts a quoted multiline header and a file with no trailing newline', () => {
    expect(parseCsvHeader('ticker,"reported\nquantity"\nNVDA,1')).toEqual([
      'ticker',
      'reported\nquantity',
    ])
    expect(parseCsvHeader('ticker,quantity')).toEqual(['ticker', 'quantity'])
  })

  it('rejects ambiguous and incomplete header records', () => {
    for (const source of [
      '',
      'ticker,ticker',
      'ticker,',
      'ticker,\nNVDA,1',
      'ticker,"quantity',
    ]) {
      expect(() => parseCsvHeader(source)).toThrow(/header/i)
    }
  })
})
