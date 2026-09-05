import { useState, useEffect, useRef, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { UploadCloud, AudioLines, Pause, CheckCircle2 } from 'lucide-react'
import { Api, type Model, type Job, type Options } from '../api'
import { uploadFile, submitUploaded, type PreparedUpload, type Progress } from '../upload'
import { Modal } from '../components/Modal'

export type UploadDraft = { file: File; uploaded: PreparedUpload }
export function UploadModal({
  api,
  models,
  zh,
  close,
  complete,
  draft,
  prepared,
}: {
  api: Api
  models: Model[]
  zh: boolean
  close: () => void
  complete: (job: Job, file: File) => void
  draft: UploadDraft | null
  prepared: (draft: UploadDraft | null) => void
}) {
  const [file, setFile] = useState<File | null>(draft?.file || null)
  const [uploaded, setUploaded] = useState<PreparedUpload | null>(draft?.uploaded || null)
  const [model, setModel] = useState(models[0]?.id || '')
  const [language, setLanguage] = useState('')
  const [diarization, setDiarization] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const controller = useRef<AbortController | null>(null)
  const capability = models.find((m) => m.id === model)
  const validFile = !!file && file.size > 0 && file.size <= 2_000_000_000
  useEffect(() => () => controller.current?.abort(), [])
  const mutation = useMutation({
    mutationFn: async () => {
      controller.current = new AbortController()
      if (!uploaded) {
        const result = await uploadFile(api, file!, controller.current.signal, setProgress)
        setUploaded(result)
        prepared({ file: file!, uploaded: result })
        setProgress(null)
        return null
      }
      const options: Options = { model, language_hints: language ? [language] : [], diarization }
      return submitUploaded(api, uploaded, options, controller.current.signal)
    },
    onSuccess: (job) => {
      if (job) complete(job, file!)
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    mutation.mutate()
  }
  return (
    <Modal title={zh ? '新建转写' : 'New transcription'} close={close}>
      <form onSubmit={submit}>
        <ol className="upload-steps" aria-label={zh ? '转写步骤' : 'Transcription steps'}>
          <li
            className={!uploaded ? 'current' : 'done'}
            aria-current={!uploaded ? 'step' : undefined}
          >
            <span>{uploaded ? <CheckCircle2 size={16} /> : '1'}</span>
            {zh ? '上传文件' : 'Upload file'}
          </li>
          <li className={uploaded ? 'current' : ''} aria-current={uploaded ? 'step' : undefined}>
            <span>2</span>
            {zh ? '确认并转写' : 'Review & transcribe'}
          </li>
        </ol>
        {uploaded ? (
          <div className="upload-ready" role="status">
            <CheckCircle2 size={24} />
            <div>
              <strong>
                {zh ? '文件已上传，尚未开始转写' : 'File uploaded. Transcription has not started.'}
              </strong>
              <p>
                {file?.name} · {((file?.size || 0) / 1e6).toFixed(1)} MB
              </p>
              <label className="asset-reference">
                {zh ? '文件 ID（可交给 Agent）' : 'Asset ID for your agent'}
                <input readOnly value={uploaded.assetId} onFocus={(e) => e.target.select()} />
              </label>
            </div>
          </div>
        ) : (
          <label
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              if (!mutation.isPending) {
                setFile(e.dataTransfer.files[0] || null)
                mutation.reset()
                setProgress(null)
              }
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
              onChange={(e) => {
                setFile(e.target.files?.[0] || null)
                mutation.reset()
                setProgress(null)
              }}
            />
          </label>
        )}
        {!uploaded && (
          <p className="help">
            {zh
              ? '音频或视频文件，最大 2 GB。视频仅识别音轨中的讲话。上传完成后再确认转写设置。'
              : 'Audio or video up to 2 GB. Video transcription uses its audio track. Review transcription settings after uploading.'}
          </p>
        )}
        {file && !validFile && (
          <p role="alert" className="error">
            {zh
              ? '请选择非空且不超过 2 GB 的文件。'
              : 'Choose a non-empty file no larger than 2 GB.'}
          </p>
        )}
        {uploaded && (
          <>
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
              {zh
                ? '区分说话人（录音不超过 2 小时）'
                : 'Identify speakers (recordings up to 2 hours)'}
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
          </>
        )}
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
          {uploaded && !mutation.isPending && (
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setUploaded(null)
                setFile(null)
                prepared(null)
                mutation.reset()
                setProgress(null)
              }}
            >
              {zh ? '更换文件' : 'Change file'}
            </button>
          )}
          {mutation.isPending && !uploaded && (
            <button type="button" className="secondary" onClick={() => controller.current?.abort()}>
              <Pause size={16} />
              {zh ? '暂停' : 'Pause'}
            </button>
          )}
          {uploaded && !mutation.isPending && (
            <button type="button" className="secondary" onClick={close}>
              {zh ? '稍后转写' : 'Transcribe later'}
            </button>
          )}
          <button
            className="primary"
            disabled={!validFile || (!!uploaded && !model) || mutation.isPending}
          >
            <AudioLines size={18} />
            {mutation.isPending
              ? uploaded
                ? zh
                  ? '正在提交…'
                  : 'Submitting…'
                : zh
                  ? '正在上传…'
                  : 'Uploading…'
              : uploaded
                ? zh
                  ? '开始转写'
                  : 'Start transcription'
                : zh
                  ? '上传文件'
                  : 'Upload file'}
          </button>
        </div>
        <p className="help">
          {zh
            ? '单独上传不会触发识别费用。本页保留待转写文件；刷新后重新选择同一文件可恢复。开始转写后，关闭页面不会取消任务。'
            : 'Uploading alone does not start paid recognition. This tab keeps your pending file; after a refresh, re-select it to resume. Submitted jobs continue after you leave.'}
        </p>
      </form>
    </Modal>
  )
}
