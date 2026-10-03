/** Read one CSV record, including quoted commas, newlines and escaped quotes. */
export function parseCsvHeader(source: string): string[] {
  const input = source.replace(/^\uFEFF/, '')
  const headers: string[] = []
  let field = ''
  let quoted = false
  for (let index = 0; index < input.length; index += 1) {
    const character = input[index]
    if (character === '"') {
      if (quoted && input[index + 1] === '"') {
        field += '"'
        index += 1
      } else quoted = !quoted
    } else if (!quoted && [',', '\n', '\r'].includes(character)) {
      headers.push(field.trim())
      field = ''
      if (character !== ',') return validate(headers)
    } else field += character
  }
  if (quoted) throw new Error('The first CSV header row has an unclosed quote.')
  headers.push(field.trim())
  return validate(headers)
}

function validate(headers: string[]): string[] {
  if (
    headers.some((header) => !header) ||
    new Set(headers).size !== headers.length
  ) {
    throw new Error('CSV headers must be non-empty and unique.')
  }
  return headers
}
