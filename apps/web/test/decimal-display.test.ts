import { expect, test } from 'vitest'
import { decimalDisplay } from '../src/decimal-display'
test('financial display rounds half up without float precision loss', () => {
  expect(decimalDisplay('35200.0000000000')).toBe('35,200.00')
  expect(decimalDisplay('0.005')).toBe('0.01')
  expect(decimalDisplay('-0.005')).toBe('-0.01')
  expect(decimalDisplay('999999999999999999.995')).toBe(
    '1,000,000,000,000,000,000.00',
  )
  expect(decimalDisplay(null)).toBe('Unavailable')
})

test('display handles whole numbers and validates fractional places', () => {
  expect(decimalDisplay('999.5', 0)).toBe('1,000')
  expect(decimalDisplay('-0.4', 0)).toBe('0')
  for (const places of [-1, 1.5, 21])
    expect(() => decimalDisplay('1', places)).toThrow(RangeError)
})
