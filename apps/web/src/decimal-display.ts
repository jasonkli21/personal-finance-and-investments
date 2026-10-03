/** Decimal string formatting with integer arithmetic and ROUND_HALF_UP. */
export function decimalDisplay(value: string | null, places = 2): string {
  if (value === null) return 'Unavailable'
  if (!Number.isInteger(places) || places < 0 || places > 20)
    throw new RangeError(
      'Decimal display places must be an integer between 0 and 20.',
    )
  const match = /^(-?)(\d+)(?:\.(\d*))?$/.exec(value)
  if (!match) return value
  const fraction = (match[3] ?? '').padEnd(places + 1, '0')
  let units =
    BigInt(match[2]) * 10n ** BigInt(places) +
    BigInt(fraction.slice(0, places) || '0')
  if (fraction[places] >= '5') units += 1n
  if (places === 0)
    return `${match[1] && units !== 0n ? '-' : ''}${units.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`
  const digits = units.toString().padStart(places + 1, '0')
  return `${match[1] && units !== 0n ? '-' : ''}${digits.slice(0, -places).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${digits.slice(-places)}`
}

export function moneyDisplay(
  value: string | null | undefined,
  currency = 'USD',
): string {
  return value === null || value === undefined
    ? 'Unavailable'
    : `${currency} ${decimalDisplay(value)}`
}
