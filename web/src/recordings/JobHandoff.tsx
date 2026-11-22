import { useRef, useState } from 'react'
import { Copy } from 'lucide-react'

function agentPrompt(id: string, zh: boolean) {
  const instruction = zh
    ? '请用 Voice Ingest 剪辑清单 Skill 接续这个已有转写任务。用 get_transcription 查状态，成功后用 read_transcript 按 next_cursor 翻到末页，逐条核对候选原话。每条给出素材标识（asset_id 或已确认的素材版本）、原话及源音频起止时间，另写选段理由。缺失或无效时间的句段标为待核对，不补时间或说话人。仅在我要求时导出；SRT 缺少有效时间时用 JSON。不重新上传、创建或重试任务。'
    : 'Use the Voice Ingest clip checklist skill to continue this existing transcription. Check get_transcription and, once successful, follow read_transcript next_cursor until the last page to verify quotes. For each candidate give the source reference (asset_id or confirmed media version), verbatim quote and source start/end times, with a separate reason. Flag segments with missing or invalid times for review and keep unknown times and speakers unknown. Export only if requested; use JSON if SRT fails for missing or invalid times. Do not upload, create or retry a job.'
  return `${zh ? '任务 ID' : 'Job ID'}: ${id}\n\n${instruction}`
}

export function JobHandoff({ id, zh }: { id: string; zh: boolean }) {
  const t = (en: string, cn: string) => (zh ? cn : en)
  const [result, setResult] = useState<{ kind: 'id' | 'agent'; copied: boolean } | null>(null)
  const sequence = useRef(0)
  const instruction = agentPrompt(id, zh)

  async function copy(kind: 'id' | 'agent') {
    const current = ++sequence.current
    let copied = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(kind === 'id' ? id : instruction)
        copied = true
      }
    } catch {
      // Keep the same text available for manual copying when the browser denies access.
    }
    if (current === sequence.current) setResult({ kind, copied })
  }

  const status = result?.copied
    ? result.kind === 'id'
      ? t('Job ID copied.', '任务 ID 已复制。')
      : t('Agent instructions copied.', 'Agent 指令已复制。')
    : t('Copy unavailable. Select and copy the text below.', '无法自动复制，请选择并复制下方文本。')

  return (
    <div className="job-handoff">
      <div className="job-handoff-actions">
        <button className="text-button" onClick={() => void copy('id')}>
          <Copy size={13} />
          {t('Copy job ID', '复制任务 ID')}
        </button>
        <button className="text-button" onClick={() => void copy('agent')}>
          <Copy size={13} />
          {t('Copy for Agent', '复制给 Agent')}
        </button>
      </div>
      <div role="status">{result && status}</div>
      {result && !result.copied && (
        <textarea
          aria-label={
            result.kind === 'id'
              ? t('Job ID to copy', '待复制任务 ID')
              : t('Agent instructions to copy', '待复制 Agent 指令')
          }
          readOnly
          rows={result.kind === 'id' ? 1 : 5}
          value={result.kind === 'id' ? id : instruction}
          onFocus={(event) => event.currentTarget.select()}
        />
      )}
    </div>
  )
}
