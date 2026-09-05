import type { components } from './schema'
export type Job = components['schemas']['JobView']
export type Asset = components['schemas']['AssetView']
export type Model = components['schemas']['ModelCapability']
export type Options = components['schemas']['TranscriptionOptions']
export type Upload = components['schemas']['UploadView']
export type Page = components['schemas']['TranscriptPage']
export type JobPage = components['schemas']['JobPage']
export type Segment = components['schemas']['Segment']
export type Format = 'json' | 'txt' | 'markdown' | 'srt' | 'vtt'
export const terminal = new Set(['succeeded', 'failed', 'cancelled', 'needs_attention'])
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message)
  }
}
export class Api {
  constructor(private key: string) {}
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`/api${path}`, {
      ...init,
      credentials: 'omit',
      redirect: 'error',
      headers: {
        'Content-Type': 'application/json',
        ...init.headers,
        Authorization: `Bearer ${this.key}`,
      },
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      const error = body.error || body
      throw new ApiError(
        error.code || 'request_failed',
        error.message || `Request failed (${response.status})`,
        response.status,
      )
    }
    return response.status === 204 ? (undefined as T) : response.json()
  }
  async export(id: string, format: Format) {
    const response = await fetch(
      `/api/v1/transcriptions/${encodeURIComponent(id)}/exports/${format}`,
      {
        headers: { Authorization: `Bearer ${this.key}` },
        credentials: 'omit',
        redirect: 'error',
      },
    )
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.error?.message || `Export failed (${response.status})`)
    }
    return response.blob()
  }
  async scope() {
    const hash = await crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(`${location.origin}:${this.key}`),
    )
    return Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('')
  }
}
export function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function time(ms?: number | null) {
  if (ms == null) return '—'
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)
    .toString()
    .padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`
}
