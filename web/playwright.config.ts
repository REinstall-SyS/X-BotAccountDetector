import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: {
    baseURL: process.env.E2E_URL || 'http://127.0.0.1:5173',
    browserName: 'chromium',
    channel: process.env.E2E_CHROME_CHANNEL || undefined,
    screenshot: 'only-on-failure',
  },
  timeout: 40_000,
})
