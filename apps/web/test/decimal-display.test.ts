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
