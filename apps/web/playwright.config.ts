import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'
const root = resolve(import.meta.dirname, '../..')
export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: 'http://127.0.0.1:5179',
    headless: true,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `uv run --directory services/api --locked python ${root}/scripts/stage1-browser-api.py`,
      cwd: root,
      url: 'http://127.0.0.1:8051/health/ready',
      timeout: 30000,
      reuseExistingServer: false,
    },
    {
      command: 'pnpm --filter web dev --port 5179 --strictPort',
      cwd: root,
      url: 'http://127.0.0.1:5179',
      env: { API_PORT: '8051' },
      timeout: 30000,
      reuseExistingServer: false,
    },
  ],
})
