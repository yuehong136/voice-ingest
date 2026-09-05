import { useQuery } from '@tanstack/react-query'
import { FileAudio } from 'lucide-react'
import { Api, time, type Asset, type Job } from '../api'
import { demoAssets } from '../demo'
import { labels } from '../status'

export function JobRow({
  job,
  api,
  active,
  zh,
  onSelect,
}: {
  job: Job
  api: Api | null
  active: boolean
  zh: boolean
  onSelect: () => void
}) {
  const asset = useQuery({
    queryKey: ['asset', job.asset_id],
    queryFn: ({ signal }) => api!.request<Asset>(`/v1/assets/${job.asset_id}`, { signal }),
    enabled: !!api,
  })
  const data = api ? asset.data : demoAssets.find((a) => a.id === job.asset_id)
  return (
    <button
      className={`recording ${active ? 'selected' : ''}`}
      onClick={onSelect}
      aria-pressed={active}
    >
      <span className="file-icon">
        <FileAudio size={20} />
      </span>
      <span className="recording-info">
        <strong>{data?.filename || job.asset_id.slice(0, 12)}</strong>
        <span>
          {time(data?.duration_ms)} <span className="dot">·</span>{' '}
          {api
            ? new Date(job.created_at).toLocaleDateString(zh ? 'zh-CN' : 'en', {
                month: 'short',
                day: 'numeric',
              })
            : zh
              ? '示例录音'
              : 'Sample recording'}
        </span>
      </span>
      <span className={`status-dot ${job.state}`} title={labels[job.state]?.[zh ? 1 : 0]} />
    </button>
  )
}
