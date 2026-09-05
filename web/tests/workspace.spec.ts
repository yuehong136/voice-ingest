import { test, expect, type Page } from '@playwright/test'
const model = {
  id: 'qwen-audio-3.0-asr-flash-filetrans',
  provider: 'mock',
  diarization: true,
  context: true,
}
const asset = { id: 'a1', filename: 'meeting.wav', size: 128, duration_ms: 180000 }
const job = {
  id: 'j1',
  asset_id: 'a1',
  state: 'succeeded',
  options: { model: model.id },
  created_at: '2026-09-05T00:00:00Z',
  updated_at: '2026-09-05T00:00:00Z',
  attempt: 1,
  remote_may_run: false,
}
async function connect(page: Page) {
  await page.getByRole('button', { name: 'Connect backend', exact: true }).click()
  await page.getByLabel('Workspace access key').fill('browser-test-key')
  await page.getByRole('button', { name: 'Connect workspace', exact: true }).click()
}
test('demo supports search, exports, language switching and narrow screens', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Your audio, in words.' })).toBeVisible()
  await page.getByLabel('Search loaded transcript').fill('timestamps')
  await expect(page.locator('.segment')).toHaveCount(1)
  await page.getByLabel('Clear search').click()
  await expect(page.locator('.segment')).toHaveCount(7)
  const exported = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  expect((await exported).suggestedFilename()).toBe('sample-transcript.md')
  await page.getByRole('button', { name: '中文', exact: true }).click()
  await expect(page.getByRole('heading', { name: '把声音，变成文字。' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: '连接后端', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
test('auth errors are visible and service keys never persist', async ({ page }) => {
  await page.route('**/api/v1/models', (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: 'unauthorized', message: 'Invalid service key' } },
    }),
  )
  await page.goto('/')
  await connect(page)
  await expect(page.getByRole('alert')).toContainText('Workspace access key is incorrect')
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('browser-test-key')
})
test('upload submits one idempotent job and does not forward credentials to storage', async ({
  page,
}) => {
  let submitted = false
  let submitCount = 0
  let puts = 0
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    expect(request.headers().authorization).toBe('Bearer browser-test-key')
    if (path.endsWith('/models')) return route.fulfill({ json: [model] })
    if (path === '/api/v1/transcriptions' && request.method() === 'POST') {
      expect(request.headers()['idempotency-key']).toBeTruthy()
      submitted = true
      submitCount++
      return route.fulfill({ status: 202, json: job })
    }
    if (path === '/api/v1/transcriptions')
      return route.fulfill({ json: { items: submitted ? [job] : [] } })
    if (path.endsWith('/assets/a1')) return route.fulfill({ json: asset })
    if (path.endsWith('/transcriptions/j1')) return route.fulfill({ json: job })
    if (path.endsWith('/segments'))
      return route.fulfill({
        json: { job_id: 'j1', segments: [{ text: 'Upload worked.', start_ms: 0, end_ms: 1000 }] },
      })
    if (path.endsWith('/parts/1'))
      return route.fulfill({
        json: { url: 'http://127.0.0.1:5174/storage-test?signature=private' },
      })
    if (path.endsWith('/uploads'))
      return route.fulfill({
        json: { id: 'u1', asset_id: 'a1', state: 'uploading', part_size: 16777216, parts: [] },
      })
    if (path.endsWith('/uploads/u1'))
      return route.fulfill({ json: { id: 'u1', asset_id: 'a1', state: 'complete' } })
    if (path.endsWith('/complete'))
      return route.fulfill({ json: { id: 'u1', asset_id: 'a1', state: 'complete' } })
    return route.fulfill({ status: 404 })
  })
  await page.route('**/storage-test?*', (route) => {
    expect(route.request().headers().authorization).toBeUndefined()
    puts++
    return route.fulfill({ status: 200 })
  })
  await page.goto('/')
  await connect(page)
  await page.getByRole('button', { name: 'New transcription', exact: true }).first().click()
  await page.getByLabel('Choose audio').setInputFiles({
    name: 'meeting.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('small audio test fixture'),
  })
  await page.getByRole('button', { name: 'Upload & transcribe' }).click()
  await expect(page.getByText('Upload worked.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'New transcription', exact: true }).first().click()
  await page.getByLabel('Choose audio').setInputFiles({
    name: 'meeting.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('small audio test fixture'),
  })
  await page.getByRole('button', { name: 'Upload & transcribe' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(puts).toBe(1)
  expect(submitCount).toBe(1)
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('browser-test-key')
})
test('uncertain jobs require explicit duplicate-charge acknowledgement', async ({ page }) => {
  const uncertain = {
    ...job,
    state: 'needs_attention',
    remote_may_run: true,
    error: { message: 'Submission outcome unknown' },
  }
  let ack = false
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/models')) return route.fulfill({ json: [model] })
    if (path.endsWith('/retry')) {
      ack = route.request().postDataJSON().acknowledge_duplicate_risk
      return route.fulfill({ json: { ...job, state: 'queued' } })
    }
    if (path === '/api/v1/transcriptions') return route.fulfill({ json: { items: [uncertain] } })
    if (path.endsWith('/assets/a1')) return route.fulfill({ json: asset })
    return route.fulfill({ json: uncertain })
  })
  await page.goto('/')
  await connect(page)
  await page.getByRole('button', { name: /meeting.wav/ }).click()
  await expect(page.getByRole('button', { name: 'Retry job' })).toBeDisabled()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Retry job' }).click()
  await expect.poll(() => ack).toBe(true)
})

test('real browser uploads to private MinIO and observes a durable mock job', async ({ page }) => {
  test.skip(!process.env.VOICE_WEB_TEST_KEY, 'Opt in with a dedicated mock backend only')
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect backend', exact: true }).click()
  await page.getByLabel('Workspace access key').fill(process.env.VOICE_WEB_TEST_KEY!)
  await page.getByRole('button', { name: 'Connect workspace', exact: true }).click()
  await expect(page.locator('.live-banner')).toContainText('Mock provider')
  const samples = 16000 * 4
  const wav = Buffer.alloc(44 + samples * 2)
  wav.write('RIFF')
  wav.writeUInt32LE(wav.length - 8, 4)
  wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16)
  wav.writeUInt16LE(1, 20)
  wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(16000, 24)
  wav.writeUInt32LE(32000, 28)
  wav.writeUInt16LE(2, 32)
  wav.writeUInt16LE(16, 34)
  wav.write('data', 36)
  wav.writeUInt32LE(samples * 2, 40)
  for (let i = 0; i < samples; i++)
    wav.writeInt16LE(Math.round(Math.sin(i / 16) * 1000), 44 + i * 2)
  await page.getByRole('button', { name: 'New transcription', exact: true }).first().click()
  await page
    .getByLabel('Choose audio')
    .setInputFiles({ name: `browser-${Date.now()}.wav`, mimeType: 'audio/wav', buffer: wav })
  await page.getByRole('button', { name: 'Upload & transcribe' }).click()
  await expect(page.locator('.status-badge')).toHaveText('Ready', { timeout: 30000 })
  await expect(page.locator('.segment').first()).toContainText('MOCK')
  const exported = page.waitForEvent('download')
  await page.getByLabel('Export format').selectOption('json')
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  expect((await exported).suggestedFilename()).toBe('transcript.json')
  await page.screenshot({ path: 'test-results/live-workspace.png', fullPage: true })
})
