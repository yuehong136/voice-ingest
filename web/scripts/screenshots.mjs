import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'
import { preview } from 'vite'

// Capture the production UI with the app's public, explicitly labeled fixtures.
// This server and fresh browser context never connect to a transcription backend.
const output = fileURLToPath(new URL('../../docs/assets/screenshots/', import.meta.url))
await mkdir(output, { recursive: true })
const server = await preview({
  preview: { host: '127.0.0.1', port: 4174, strictPort: true, open: false },
})
let browser
try {
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' })
  for (const language of ['en', 'zh-CN']) {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1200 },
      deviceScaleFactor: 1,
      locale: language,
      timezoneId: 'UTC',
      colorScheme: 'light',
      reducedMotion: 'reduce',
      serviceWorkers: 'block',
    })
    const unexpectedRequests = []
    await context.route('**/*', async (route) => {
      const url = new URL(route.request().url())
      if (url.origin !== 'http://127.0.0.1:4174' || url.pathname.startsWith('/api/')) {
        unexpectedRequests.push('Non-static request blocked')
        await route.abort()
      } else {
        await route.continue()
      }
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto('http://127.0.0.1:4174')
    await page.getByRole('button', { name: 'Explore sample transcript', exact: true }).click()
    if (language === 'zh-CN') {
      await page.getByRole('button', { name: '中文', exact: true }).click()
    }
    await expect(page.locator('.segment')).toHaveCount(7)
    await page.evaluate(() => document.fonts.ready)
    await page.screenshot({
      path: `${output}/workspace-${language}.png`,
      fullPage: true,
      animations: 'disabled',
    })

    // Show the real mobile reader at its normal scroll position, without restyling it.
    await page.setViewportSize({ width: 390, height: 844 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.locator('.reader').evaluate((element) => element.scrollIntoView())
    await page.screenshot({
      path: `${output}/reader-mobile-${language}.png`,
      animations: 'disabled',
    })
    assert.deepEqual(unexpectedRequests, [], 'Screenshots must use only local static assets')
    assert.deepEqual(errors, [], 'The sample workspace must render without browser errors')
    await context.close()
  }
  console.log('Saved four sample-workspace screenshots to docs/assets/screenshots.')
} finally {
  await browser?.close()
  await new Promise((resolve, reject) =>
    server.httpServer.close((error) => (error ? reject(error) : resolve())),
  )
}
