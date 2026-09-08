import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  workers: 2,
  reporter: 'list',
  timeout: 30000,
  use: {
    baseURL: process.env.VOICE_WEB_TEST_BASE_URL || 'http://127.0.0.1:5174',
    trace: 'off',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
  },
  webServer: process.env.VOICE_WEB_TEST_BASE_URL
    ? undefined
    : {
        command: 'npm run test:serve',
        url: 'http://127.0.0.1:5174',
        reuseExistingServer: false,
      },
})
