import { test, expect, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
const model = {
  id: 'qwen-audio-3.0-asr-flash-filetrans',
  provider: 'mock',
  kind: 'transcription',
  deployment_id: 'default',
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
async function submitConnection(page: Page) {
  await page.getByRole('button', { name: 'Connect backend', exact: true }).click()
  await page.getByLabel('Workspace access key').fill('browser-test-key')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Connect workspace', exact: true })
    .click()
}
async function connect(page: Page) {
  await submitConnection(page)
  await expect(
    page.getByRole('dialog', { name: 'Connect your workspace', exact: true }),
  ).toHaveCount(0)
  await expect(page.locator('.connection-pill')).toHaveText('Connected')
  await expect(
    page.getByRole('button', { name: 'New transcription', exact: true }).first(),
  ).toBeEnabled()
}

function syntheticWav(seconds: number, audible: boolean) {
  const samples = 16000 * seconds
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
  if (audible) {
    for (let i = 0; i < samples; i++)
      wav.writeInt16LE(Math.round(Math.sin(i / 16) * 1000), 44 + i * 2)
  }
  return wav
}

async function connectLiveMock(page: Page, key: string) {
  await page.getByRole('button', { name: 'Connect backend', exact: true }).click()
  await page.getByLabel('Workspace access key').fill(key)
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Connect workspace', exact: true })
    .click()
  await expect(page.locator('.live-banner')).toContainText('Mock provider')
}

test('demo supports search, exports, language switching and narrow screens', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Transcriptions', exact: true })).toBeVisible()
  await expect(page.locator('.segment')).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByRole('button', { name: 'Explore sample transcript' }).click()
  await page.getByLabel('Search loaded transcript').fill('timestamps')
  await expect(page.locator('.segment')).toHaveCount(1)
  await page.getByLabel('Clear search').click()
  await expect(page.locator('.segment')).toHaveCount(7)
  const exported = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  expect((await exported).suggestedFilename()).toBe('sample-transcript.md')
  await page.getByRole('button', { name: '中文', exact: true }).click()
  await expect(page.getByRole('heading', { name: '转写工作台' })).toBeVisible()
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
  await submitConnection(page)
  await expect(page.getByRole('alert')).toContainText('Workspace access key is incorrect')
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('browser-test-key')
})

for (const clipboard of ['available', 'unavailable', 'denied'] as const) {
  test(`Agent handoff with clipboard ${clipboard}`, async ({ page, context }) => {
    if (clipboard === 'available') {
      await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    } else {
      await page.addInitScript((mode) => {
        Object.defineProperty(navigator, 'clipboard', {
          value:
            mode === 'denied'
              ? { writeText: () => Promise.reject(new DOMException('Denied', 'NotAllowedError')) }
              : undefined,
        })
      }, clipboard)
    }
    const other = { ...job, id: 'other-job-id', asset_id: 'other-asset-id' }
    const writes: string[] = []
    await page.route('**/api/**', (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (request.method() !== 'GET') writes.push(path)
      if (path.endsWith('/models')) return route.fulfill({ json: [model] })
      if (path === '/api/v1/transcriptions') return route.fulfill({ json: { items: [other, job] } })
      if (path.endsWith(`/assets/${asset.id}`)) return route.fulfill({ json: asset })
      if (path.endsWith(`/assets/${other.asset_id}`)) {
        return route.fulfill({ json: { ...asset, id: other.asset_id, filename: 'Other.wav' } })
      }
      if (path.endsWith('/segments')) {
        return route.fulfill({
          json: { segments: [{ text: 'Private words from the interview.' }] },
        })
      }
      return route.fulfill({ json: path.endsWith(`/${other.id}`) ? other : job })
    })
    await page.goto('/')
    await connect(page)
    await page.getByRole('button', { name: /meeting\.wav/ }).click()
    await expect(page.getByText('Private words from the interview.')).toBeVisible()
    await page.setViewportSize({ width: 390, height: 844 })

    await page.getByRole('button', { name: 'Copy job ID', exact: true }).click()
    if (clipboard === 'available') {
      await expect(page.getByText('Job ID copied.')).toBeVisible()
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(job.id)
    } else {
      await expect(page.getByRole('textbox', { name: 'Job ID to copy' })).toHaveValue(job.id)
    }
    await page.getByRole('button', { name: 'Copy for Agent', exact: true }).click()
    let prompt: string
    if (clipboard === 'available') {
      await expect(page.getByText('Agent instructions copied.')).toBeVisible()
      prompt = await page.evaluate(() => navigator.clipboard.readText())
    } else {
      const fallback = page.getByRole('textbox', { name: 'Agent instructions to copy' })
      await expect(fallback).toBeVisible()
      prompt = await fallback.inputValue()
      await fallback.focus()
      expect(await fallback.evaluate((box) => (box as HTMLTextAreaElement).selectionEnd)).toBe(
        prompt.length,
      )
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
    }
    expect(prompt).toMatch(/^Job ID: j1\n\n/)
    expect(prompt).toContain('get_transcription')
    expect(prompt).toContain('next_cursor')
    expect(prompt).toContain('JSON')
    for (const privateValue of [other.id, asset.filename, 'Private words', 'browser-test-key']) {
      expect(prompt).not.toContain(privateValue)
    }
    expect(prompt).not.toMatch(/https?:\/\//)
    expect(writes).toEqual([])
    await page.getByRole('button', { name: /Other\.wav/ }).click()
    await expect(page.getByRole('textbox', { name: 'Agent instructions to copy' })).toHaveCount(0)
  })
}

test('the subtitle error offers a downloadable JSON export for the same job', async ({ page }) => {
  const fallback = {
    job_id: job.id,
    asset_id: asset.id,
    segments: [{ text: 'Synthetic line.', start_ms: 900, end_ms: null, speaker_id: null }],
  }
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/models')) return route.fulfill({ json: [model] })
    if (path === '/api/v1/transcriptions') return route.fulfill({ json: { items: [job] } })
    if (path.endsWith(`/assets/${asset.id}`)) return route.fulfill({ json: asset })
    if (path === `/api/v1/transcriptions/${job.id}`) return route.fulfill({ json: job })
    if (path.endsWith('/segments')) return route.fulfill({ json: fallback })
    if (path === `/api/v1/transcriptions/${job.id}/exports/srt`) {
      return route.fulfill({ status: 409, json: { error: { code: 'timestamps_unavailable' } } })
    }
    if (path === `/api/v1/transcriptions/${job.id}/exports/json`) {
      return route.fulfill({ json: fallback })
    }
    return route.fulfill({ status: 404 })
  })
  await page.goto('/')
  await connect(page)
  await page.getByRole('button', { name: /meeting\.wav/ }).click()
  await page.getByLabel('Export format').selectOption('srt')
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Some segments lack valid times')
  const exported = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download JSON' }).click()
  const file = await exported
  expect(file.suggestedFilename()).toBe('transcript.json')
  expect(JSON.parse(await readFile(await file.path(), 'utf8'))).toEqual(fallback)
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
  await page.getByRole('button', { name: 'Upload file', exact: true }).click()
  await expect(page.getByText('File uploaded. Transcription has not started.')).toBeVisible()
  expect(submitCount).toBe(0)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect(page.getByRole('button', { name: 'Start transcription', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByRole('button', { name: 'Transcribe later', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Continue setup', exact: true }).click()
  await expect(page.getByText('File uploaded. Transcription has not started.')).toBeVisible()
  await page.getByRole('button', { name: 'Start transcription', exact: true }).click()
  await expect(page.getByText('Upload worked.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Processing', exact: true }).click()
  await expect(page.getByText('No recordings in this view.')).toBeVisible()
  await page.getByRole('button', { name: 'All', exact: true }).click()
  await page.getByRole('button', { name: 'New transcription', exact: true }).first().click()
  await page.getByLabel('Choose audio').setInputFiles({
    name: 'meeting.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('small audio test fixture'),
  })
  await page.getByRole('button', { name: 'Upload file', exact: true }).click()
  await expect(page.getByText('File uploaded. Transcription has not started.')).toBeVisible()
  await page.getByRole('button', { name: 'Start transcription', exact: true }).click()
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

test('real browser uploads to private storage and downloads native SRT from a durable mock job', async ({
  page,
}) => {
  test.skip(!process.env.VOICE_WEB_TEST_KEY, 'Opt in with a dedicated mock backend only')
  test.setTimeout(120000)
  await page.goto('/')
  await connectLiveMock(page, process.env.VOICE_WEB_TEST_KEY!)
  await page.getByRole('button', { name: 'New transcription', exact: true }).first().click()
  await page.getByLabel('Choose audio').setInputFiles({
    name: `browser-${Date.now()}.wav`,
    mimeType: 'audio/wav',
    buffer: syntheticWav(4, true),
  })
  await page.getByRole('button', { name: 'Upload file', exact: true }).click()
  await expect(page.getByText('File uploaded. Transcription has not started.')).toBeVisible({
    timeout: 30000,
  })
  await page.getByRole('button', { name: 'Start transcription', exact: true }).click()
  await expect(page.locator('.status-badge')).toHaveText('Ready', { timeout: 60000 })
  await expect(page.locator('.segment').first()).toContainText('MOCK')
  const exported = page.waitForEvent('download')
  await page.getByLabel('Export format').selectOption('srt')
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  const srt = await exported
  expect(srt.suggestedFilename()).toBe('transcript.srt')
  expect(await readFile(await srt.path(), 'utf8')).toContain(
    '1\n00:00:00,000 --> 00:00:01,000\n[MOCK] Synthetic segment 1; not speech recognition.',
  )
  await page.screenshot({ path: 'test-results/live-workspace.png', fullPage: true })
})

test('real multipart upload resumes after a failed part and a page reload', async ({ page }) => {
  const key = process.env.VOICE_WEB_TEST_KEY
  test.skip(!key, 'Opt in with a dedicated mock backend only')
  test.setTimeout(120000)
  const file = {
    name: `interrupted-${Date.now()}.wav`,
    mimeType: 'audio/wav',
    buffer: syntheticWav(530, false),
  }
  const uploadedParts: number[] = []
  const resumedParts: number[] = []
  let resumed = false
  let uploadsCreated = 0
  let jobsCreated = 0
  let acceptFirstPart!: () => void
  const firstPartCommitted = new Promise<void>((resolve) => {
    acceptFirstPart = resolve
  })
  page.on('request', (request) => {
    if (request.method() !== 'POST') return
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/uploads') uploadsCreated++
    if (path === '/api/v1/transcriptions') jobsCreated++
  })
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (
      response.request().method() === 'PUT' &&
      response.ok() &&
      url.searchParams.get('partNumber') === '1'
    ) {
      acceptFirstPart()
    }
  })
  await page.route(
    (url) => url.searchParams.has('partNumber') && url.searchParams.has('uploadId'),
    async (route) => {
      const request = route.request()
      if (request.method() !== 'PUT') return route.continue()
      expect(request.headers().authorization).toBeUndefined()
      const part = Number(new URL(request.url()).searchParams.get('partNumber'))
      if (resumed) resumedParts.push(part)
      else uploadedParts.push(part)
      if (!resumed && part === 2) {
        await firstPartCommitted
        return route.abort('failed')
      }
      return route.continue()
    },
  )
  async function selectAudioAndUpload() {
    await page.getByRole('button', { name: 'New transcription', exact: true }).first().click()
    await page.getByLabel('Choose audio').setInputFiles(file)
    await page.getByRole('button', { name: 'Upload file', exact: true }).click()
  }
  await page.goto('/')
  await connectLiveMock(page, key!)
  const initialUpload = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/api/v1/uploads',
  )
  await selectAudioAndUpload()
  const { id: uploadId } = await (await initialUpload).json()
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible({ timeout: 30000 })
  expect(uploadedParts.sort()).toEqual([1, 2])
  expect(jobsCreated).toBe(0)

  resumed = true
  await page.reload()
  await connectLiveMock(page, key!)
  const recovered = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname === `/api/v1/uploads/${uploadId}`,
  )
  await selectAudioAndUpload()
  const saved = await (await recovered).json()
  expect(saved.state).toBe('uploading')
  expect(saved.parts.map((part: { number: number }) => part.number)).toEqual([1])
  await expect(page.getByText('File uploaded. Transcription has not started.')).toBeVisible({
    timeout: 30000,
  })
  expect(resumedParts).toEqual([2])
  expect(uploadsCreated).toBe(1)
  expect(jobsCreated).toBe(0)
  await page.getByRole('button', { name: 'Start transcription', exact: true }).click()
  await expect(page.locator('.status-badge')).toHaveText('Ready', { timeout: 60000 })
  expect(jobsCreated).toBe(1)
})
