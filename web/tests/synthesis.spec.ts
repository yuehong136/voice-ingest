import { test, expect } from '@playwright/test'

function wav() {
  const body = Buffer.alloc(44 + 44100)
  body.write('RIFF')
  body.writeUInt32LE(body.length - 8, 4)
  body.write('WAVEfmt ', 8)
  body.writeUInt32LE(16, 16)
  body.writeUInt16LE(1, 20)
  body.writeUInt16LE(1, 22)
  body.writeUInt32LE(22050, 24)
  body.writeUInt32LE(44100, 28)
  body.writeUInt16LE(2, 32)
  body.writeUInt16LE(16, 34)
  body.write('data', 36)
  body.writeUInt32LE(44100, 40)
  return body
}

test('synthesis requires explicit submission, plays complete audio and supports narrow screens', async ({
  page,
}) => {
  const model = {
    id: 'mock-tts',
    provider: 'mock',
    kind: 'synthesis',
    deployment_id: 'test',
    location: 'test',
    formats: ['wav'],
    sample_rates: [22050],
    max_text_characters: 20000,
  }
  const job = {
    id: 'tts-test',
    state: 'succeeded',
    options: { model: 'mock-tts', voice: 'mock-voice' },
    deployment_id: 'test',
    attempt: 1,
  }
  let submissions = 0
  await page.route('**/api/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    expect(request.headers().authorization).toBe('Bearer browser-test-key')
    if (path.endsWith('/models')) return route.fulfill({ json: [model] })
    if (path.endsWith('/voices'))
      return route.fulfill({ json: [{ id: 'mock-voice', name: 'Mock voice' }] })
    if (path === '/api/v1/syntheses' && request.method() === 'POST') {
      submissions++
      expect(request.postDataJSON().options.deployment_id).toBe('test')
      expect(request.headers()['idempotency-key']).toBeTruthy()
      return route.fulfill({ status: 202, json: job })
    }
    if (path.endsWith('/syntheses'))
      return route.fulfill({ json: { items: submissions ? [job] : [] } })
    if (path.endsWith('/tts-test')) return route.fulfill({ json: job })
    if (path.endsWith('/result'))
      return route.fulfill({ json: { format: 'wav', duration_ms: 1000, size: wav().length } })
    if (path.endsWith('/audio')) return route.fulfill({ contentType: 'audio/wav', body: wav() })
    return route.fulfill({ json: { items: [] } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect backend', exact: true }).click()
  await page.getByLabel('Workspace access key').fill('browser-test-key')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Connect workspace', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Speech synthesis', exact: true }).click()
  await page.getByLabel('Text to speak').fill('Only synthesize when explicitly submitted.')
  expect(submissions).toBe(0)
  await page.getByRole('button', { name: 'Create synthesis', exact: true }).click()
  await expect(page.getByLabel('Generated speech')).toBeVisible()
  await expect
    .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.readyState))
    .toBeGreaterThan(0)
  await page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.play())
  await expect
    .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.currentTime))
    .toBeGreaterThan(0)
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download audio', exact: true }).click()
  expect((await downloading).suggestedFilename()).toBe('speech.wav')
  expect(submissions).toBe(1)
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('Only synthesize')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/synthesis-mobile.png', fullPage: true })
})

test('real browser completes synthesis against isolated PostgreSQL and S3', async ({ page }) => {
  test.skip(!process.env.VOICE_WEB_TEST_KEY, 'Dedicated mock backend required')
  test.setTimeout(120000)
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect backend', exact: true }).click()
  await page.getByLabel('Workspace access key').fill(process.env.VOICE_WEB_TEST_KEY!)
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Connect workspace', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Speech synthesis', exact: true }).click()
  await page.getByLabel('Text to speak').fill('Synthetic browser acceptance.')
  await page.getByRole('button', { name: 'Create synthesis', exact: true }).click()
  await expect(page.getByLabel('Generated speech')).toBeVisible({ timeout: 60000 })
  await expect(page.locator('.synthesis-row.selected')).toContainText('Ready')
  await expect
    .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.duration))
    .toBe(1)
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download audio', exact: true }).click()
  expect((await downloading).suggestedFilename()).toBe('speech.wav')
  await page.screenshot({ path: 'test-results/synthesis-live.png', fullPage: true })
})
