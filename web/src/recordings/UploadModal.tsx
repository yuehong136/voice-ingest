import { useState, useEffect, useRef, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { UploadCloud, AudioLines, Pause } from 'lucide-react'
import { Api, type Model, type Job, type Options } from '../api'
import { uploadAndSubmit, type Progress } from '../upload'
import { Modal } from '../components/Modal'

export function UploadModal({
  api,
  models,
  zh,
  close,
  complete,
}: {
  api: Api
  models: Model[]
  zh: boolean
  close: () => void
  complete: (job: Job, file: File) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [model, setModel] = useState(models[0]?.id || '')
  const [language, setLanguage] = useState('')
  const [diarization, setDiarization] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const controller = useRef<AbortController | null>(null)
  const capability = models.find((m) => m.id === model)
  useEffect(() => () => controller.current?.abort(), [])
  const mutation = useMutation({
    mutationFn: async () => {
      controller.current = new AbortController()
      const options: Options = { model, language_hints: language ? [language] : [], diarization }
      return uploadAndSubmit(api, file!, options, controller.current.signal, setProgress)
    },
    onSuccess: (job) => complete(job, file!),
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    mutation.mutate()
  }
  return (
    <Modal title={zh ? '新建转写' : 'New transcription'} close={close}>
      <form onSubmit={submit}>
        <label
          className="dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            if (!mutation.isPending) setFile(e.dataTransfer.files[0] || null)
          }}
        >
          <UploadCloud size={32} />
          <strong>{file?.name || (zh ? '将录音拖放到这里' : 'Drop your recording here')}</strong>
          <span>
            {file
              ? `${(file.size / 1e6).toFixed(1)} MB`
              : zh
                ? '或点击选择文件 · 最大 2 GB'
                : 'or click to browse · up to 2 GB'}
          </span>
          <input
            type="file"
            aria-label={zh ? '选择音频' : 'Choose audio'}
            accept="audio/*,video/mp4,video/webm"
            disabled={mutation.isPending}
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </label>
        <div className="form-grid">
          <label className="field">
            {zh ? '模型' : 'Model'}
            <select
              disabled={mutation.isPending}
              value={model}
              onChange={(e) => {
                setModel(e.target.value)
                setDiarization(false)
              }}
            >
              {models.map((m) => (
                <option key={m.id}>{m.id}</option>
              ))}
            </select>
          </label>
          <label className="field">
            {zh ? '录音语言' : 'Language'}
            <select
              value={language}
              disabled={mutation.isPending}
              onChange={(e) => setLanguage(e.target.value)}
            >
              <option value="">{zh ? '自动识别' : 'Auto detect'}</option>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </label>
        </div>
        <label className="check-field">
          <input
            type="checkbox"
            checked={diarization}
            disabled={!capability?.diarization || mutation.isPending}
            onChange={(e) => setDiarization(e.target.checked)}
          />
          {zh ? '区分说话人（录音不超过 2 小时）' : 'Identify speakers (recordings up to 2 hours)'}
        </label>
        <p className="callout">
          {capability?.provider === 'mock'
            ? zh
              ? '当前后端使用模拟供应商，生成示例文本，不产生识别费用。'
              : 'This backend uses the mock provider. It returns synthetic text without recognition charges.'
            : zh
              ? '提交后将使用云端 ASR，可能产生识别费用。'
              : 'Submitting starts cloud ASR and may incur recognition charges.'}
        </p>
        {progress && (
          <div role="status" className="upload-progress">
            <span>
              {
                {
                  hashing: zh ? '校验文件' : 'Verifying file',
                  uploading: zh ? '上传录音' : 'Uploading audio',
                  submitting: zh ? '创建任务' : 'Creating job',
                }[progress.stage]
              }{' '}
              <b>{progress.percent}%</b>
            </span>
            <progress max="100" value={progress.percent} />
          </div>
        )}
        {mutation.error && (
          <p role="alert" className="error">
            {mutation.error.name === 'AbortError'
              ? zh
                ? '上传已暂停，重新提交可续传。'
                : 'Upload paused. Submit again to resume.'
              : mutation.error.message}
          </p>
        )}
        <div className="modal-actions">
          {mutation.isPending && (
            <button type="button" className="secondary" onClick={() => controller.current?.abort()}>
              <Pause size={16} />
              {zh ? '暂停' : 'Pause'}
            </button>
          )}
          <button className="primary" disabled={!file || !model || mutation.isPending}>
            <AudioLines size={18} />
            {zh ? '上传并转写' : 'Upload & transcribe'}
          </button>
        </div>
        <p className="help">
          {zh
            ? '上传中断后可重新选择同一文件续传。转写开始后，关闭页面不会取消任务。'
            : 'Re-select the same file to resume an interrupted upload. Once submitted, jobs continue after you close this page.'}
        </p>
      </form>
    </Modal>
  )
}
