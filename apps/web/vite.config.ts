import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, searchForWorkspaceRoot } from 'vite'
import { resolveApiPort } from './src/dev-config.ts'

const processObject = (
  globalThis as typeof globalThis & {
    process: { cwd(): string; env: Record<string, string | undefined> }
  }
).process
const repositoryRoot = searchForWorkspaceRoot(processObject.cwd())

export default defineConfig(({ mode }) => {
  // Read only API_PORT from the repository-root env files. It configures the
  // development proxy and is never defined or bundled as a browser variable.
  const fileEnv = loadEnv(mode, repositoryRoot, 'API_PORT')
  const apiPort = resolveApiPort(fileEnv, processObject.env)

  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${apiPort}`,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
