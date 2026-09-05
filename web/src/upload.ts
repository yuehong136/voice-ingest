import { Api, ApiError, type Upload, type Options, type Job } from './api'
export type Progress = { stage: 'hashing' | 'uploading' | 'submitting'; percent: number }
function fingerprint(
  file: File,
  signal: AbortSignal,
  progress: (p: Progress) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./hash.worker.ts', import.meta.url), { type: 'module' })
    const finish = () => {
      worker.terminate()
      signal.removeEventListener('abort', abort)
    }
    const abort = () => {
      finish()
      reject(new DOMException('Upload paused', 'AbortError'))
    }
    if (signal.aborted) return abort()
    signal.addEventListener('abort', abort, { once: true })
    worker.onmessage = ({ data }) => {
      if (data.hash) {
        finish()
        resolve(data.hash)
      } else if (data.error) {
        finish()
        reject(new Error(data.error))
      } else progress({ stage: 'hashing', percent: Math.round(data.progress * 100) })
    }
    worker.onerror = () => {
      finish()
      reject(new Error('File verification failed.'))
    }
    worker.postMessage(file)
  })
}
// Only fingerprints and upload/job identifiers persist. Audio, transcript and credentials do not.
function load(key: string): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(key) || '{}')
  } catch {
    return {}
  }
}
function save(key: string, value: Record<string, string>) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    throw new Error('Browser storage is unavailable. Enable site storage to resume safely.')
  }
}
export type PreparedUpload = { assetId: string; submissionPrefix: string }
export async function uploadFile(
  api: Api,
  file: File,
  signal: AbortSignal,
  progress: (p: Progress) => void,
) {
  if (!file.size || file.size > 2_000_000_000)
    throw new Error('Choose a non-empty file smaller than 2 GB.')
  const hash = await fingerprint(file, signal, progress)
  const prefix = `voice-upload:${await api.scope()}:${hash}`
  const record = load(prefix)
  let upload: Upload | undefined
  if (record.upload) {
    try {
      upload = await api.request<Upload>(`/v1/uploads/${record.upload}`, { signal })
    } catch (error) {
      if (!(error instanceof ApiError) || ![404, 410].includes(error.status)) throw error
    }
    if (upload && ['aborted', 'expired'].includes(upload.state)) upload = undefined
  }
  if (!upload) {
    upload = await api.request<Upload>('/v1/uploads', {
      method: 'POST',
      signal,
      body: JSON.stringify({ filename: file.name, size: file.size, sha256: hash }),
    })
    save(prefix, { upload: upload.id })
  }
  if (upload.state !== 'complete') {
    const session = upload
    const completed = new Set((session.parts || []).map((p) => p.number))
    let bytes = (session.parts || []).reduce((sum, p) => sum + p.size, 0)
    const count = Math.ceil(file.size / session.part_size!)
    let next = 1
    const controller = new AbortController()
    const combined = AbortSignal.any([signal, controller.signal])
    const tasks = Array.from({ length: Math.min(4, count) }, async () => {
      while (next <= count) {
        const part = next++
        if (completed.has(part)) continue
        const chunk = file.slice((part - 1) * session.part_size!, part * session.part_size!)
        for (let attempt = 0; attempt < 3; attempt++) {
          combined.throwIfAborted()
          const signed = await api.request<{ url: string }>(
            `/v1/uploads/${session.id}/parts/${part}`,
            { method: 'POST', signal: combined },
          )
          const response = await fetch(signed.url, {
            method: 'PUT',
            body: chunk,
            signal: combined,
            credentials: 'omit',
            redirect: 'error',
          })
          if (response.ok) break
          if (attempt === 2)
            throw new Error(
              `Upload part failed (${response.status}). Re-select this file to resume.`,
            )
        }
        bytes += chunk.size
        progress({ stage: 'uploading', percent: Math.round((bytes / file.size) * 100) })
      }
    })
    try {
      await Promise.all(tasks)
    } catch (error) {
      controller.abort()
      await Promise.allSettled(tasks)
      throw error
    }
    upload = await api.request<Upload>(`/v1/uploads/${session.id}/complete`, {
      method: 'POST',
      signal,
    })
  }
  return { assetId: upload.asset_id!, submissionPrefix: prefix }
}
export async function submitUploaded(
  api: Api,
  uploaded: PreparedUpload,
  options: Options,
  signal: AbortSignal,
) {
  const submissionKey = `${uploaded.submissionPrefix}:${JSON.stringify(options)}`
  const submission = load(submissionKey)
  if (submission.job) return api.request<Job>(`/v1/transcriptions/${submission.job}`, { signal })
  const idempotency = submission.idempotency || crypto.randomUUID()
  save(submissionKey, { idempotency })
  const job = await api.request<Job>('/v1/transcriptions', {
    method: 'POST',
    signal,
    headers: { 'Idempotency-Key': idempotency },
    body: JSON.stringify({ asset_id: uploaded.assetId, options }),
  })
  save(submissionKey, { idempotency, job: job.id })
  return job
}
