import { defineConfig, devices } from '@playwright/test'

// Browser-level checks against the real backend and frontend. Uses the system
// Chrome (channel 'chrome'; no browser download). Servers are started
// automatically unless already running. Override ports with
// SKYSHIFT_WEB_PORT / SKYSHIFT_API_PORT to run isolated instances.
const webPort = Number(process.env.SKYSHIFT_WEB_PORT ?? 5173)
const apiPort = Number(process.env.SKYSHIFT_API_PORT ?? 8000)
const env = { ...process.env, SKYSHIFT_WEB_PORT: String(webPort), SKYSHIFT_API_PORT: String(apiPort) } as Record<string, string>

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: process.env.SKYSHIFT_PW_JSON ?? '../validation/results/playwright.json' }]],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], channel: 'chrome', viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: `uv run uvicorn skyshift.api.app:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${apiPort}/api/health`,
      reuseExistingServer: true,
      timeout: 120_000,
      env,
    },
    {
      command: 'npx vite',
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: true,
      timeout: 120_000,
      env,
    },
  ],
})
