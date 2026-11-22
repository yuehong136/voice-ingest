import assert from 'node:assert/strict'
import { copyFile, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium, expect } from '@playwright/test'

if (!process.argv[2]) throw new Error('Pass the generated clip-demo.html')
const input = resolve(process.argv[2])
const workspace = await mkdtemp(join(tmpdir(), 'voice-clip-demo-'))

try {
  const isolatedPage = join(workspace, 'clip-demo.html')
  await copyFile(input, isolatedPage)
  const browser = await chromium.launch({ channel: 'chrome' })
  try {
    const context = await browser.newContext({
      offline: true,
      viewport: { width: 1120, height: 680 },
    })
    const page = await context.newPage()
    const httpRequests = []
    const errors = []
    page.on('request', (request) => {
      if (/^https?:/.test(request.url())) httpRequests.push(request.url())
    })
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto(pathToFileURL(isolatedPage).href)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Interview clip checklist')
    await expect(page.locator('#quote')).toHaveText(
      'We lowered the review time from nine hours to four.',
    )
    await expect(page.locator('#range')).toHaveText('00:00:07,000 – 00:00:09,750')

    async function playAndStop(button, playing, finished, start, end) {
      const status = page.getByRole('status')
      await page.getByRole('button', { name: button }).click()
      await expect(status).toHaveText(playing)
      const currentTime = () => page.locator('#audio').evaluate((audio) => audio.currentTime)
      const firstTime = await currentTime()
      assert.ok(firstTime >= start - 0.01 && firstTime < start + 1, `Unexpected start ${firstTime}`)
      await expect(status).toHaveText(finished)
      const stopped = await currentTime()
      assert.ok(stopped >= end && stopped < end + 0.15, `Unexpected end ${stopped}`)
      assert.equal(await page.locator('#audio').evaluate((audio) => audio.paused), true)
      return stopped
    }

    async function download(button, expected) {
      const pending = page.waitForEvent('download')
      await page.getByRole('link', { name: button }).click()
      const file = await pending
      assert.equal(file.suggestedFilename(), expected)
      assert.deepEqual(
        await readFile(await file.path()),
        await readFile(join(dirname(input), expected)),
      )
    }

    const original = await playAndStop(
      'Play this quote',
      'Playing the selected quote',
      'End of selected quote',
      7,
      9.75,
    )
    await download('Download SRT', 'interview-original.srt')
    await download('Download the full checklist', 'example-checklist.md')
    await page.getByRole('button', { name: '切换到中文' }).click()
    await expect(page).toHaveTitle('Voice Ingest · 采访剪辑清单')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '裁首 5 秒 · 11 秒' }).click()
    await expect(page.locator('#filename')).toHaveText('interview-trim-5s.mp4')
    await expect(page.locator('#range')).toHaveText('00:00:02,000 – 00:00:04,750')
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      true,
    )
    const trimmed = await playAndStop(
      '播放这段原话',
      '正在播放所选原话',
      '所选片段播放结束',
      2,
      4.75,
    )
    await download('下载 SRT', 'interview-trim-5s.srt')
    const walkthrough = page.locator('#video')
    await expect(walkthrough).toBeVisible()
    const recording = await walkthrough.evaluate(async (video) => {
      video.muted = true
      await video.play()
      video.pause()
      return { width: video.videoWidth, height: video.videoHeight, duration: video.duration }
    })
    assert.ok(recording.width >= 640 && recording.height >= 360 && recording.duration > 6)
    assert.deepEqual(httpRequests, [])
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ standalone: true, offline: true, original, trimmed, recording }))
  } finally {
    await browser.close()
  }
} finally {
  await rm(workspace, { recursive: true, force: true })
}
