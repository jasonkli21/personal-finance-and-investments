import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const temporaryDirectory = mkdtempSync(join(tmpdir(), 'portfolio-api-contract-'))
const generatedOpenApi = join(temporaryDirectory, 'openapi.json')
const generatedTypes = join(temporaryDirectory, 'schema.d.ts')

try {
  execFileSync(
    'uv',
    [
      'run',
      '--directory',
      'services/api',
      '--locked',
      'python',
      '-m',
      'app.export_openapi',
      generatedOpenApi,
    ],
    { cwd: repositoryRoot, stdio: 'inherit' },
  )
  execFileSync(
    'pnpm',
    [
      '--filter',
      'web',
      'exec',
      'openapi-typescript',
      generatedOpenApi,
      '-o',
      generatedTypes,
    ],
    { cwd: repositoryRoot, stdio: 'inherit' },
  )
  execFileSync(
    'pnpm',
    [
      '--filter',
      'web',
      'exec',
      'prettier',
      '--config',
      join(repositoryRoot, 'apps/web/.prettierrc.json'),
      '--write',
      generatedTypes,
    ],
    { cwd: repositoryRoot, stdio: 'inherit' },
  )

  for (const [generated, committed] of [
    [generatedOpenApi, 'apps/web/src/api/openapi.json'],
    [generatedTypes, 'apps/web/src/api/schema.d.ts'],
  ]) {
    // Compare independently generated files so this check works with other
    // edits already present in the working tree and never rewrites artifacts.
    const generatedText = readFileSync(generated, 'utf8')
    const committedText = readFileSync(join(repositoryRoot, committed), 'utf8')
    if (generatedText !== committedText) {
      throw new Error(`${committed} is stale; run pnpm api:generate and commit the result.`)
    }
  }
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true })
}
