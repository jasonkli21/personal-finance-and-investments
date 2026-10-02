export function resolveApiPort(
  fileEnv: Record<string, string>,
  shellEnv: Record<string, string | undefined>,
): number {
  const value = shellEnv.API_PORT ?? fileEnv.API_PORT ?? '8000'
  if (!/^\d+$/.test(value)) {
    throw new Error('API_PORT must be an integer between 1 and 65535')
  }

  const port = Number(value)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('API_PORT must be an integer between 1 and 65535')
  }
  return port
}
