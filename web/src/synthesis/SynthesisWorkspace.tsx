import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Api, download, terminal, type Model } from '../api'
import type { components } from '../schema'
import { labels } from '../status'
import './synthesis.css'

type Job = components['schemas']['SynthesisJob']
type Page = components['schemas']['SynthesisPage']
type Voice = components['schemas']['Voice']
type Result = components['schemas']['SynthesisResult']

export function SynthesisWorkspace({
  api,
  models,
  zh,
  connect,
}: {
  api: Api | null
  models: Model[]
  zh: boolean
  connect: () => void
}) {
  const t = (en: string, cn: string) => (zh ? cn : en)
  const [selection, setSelection] = useState('')
  const [voice, setVoice] = useState('')
  const [text, setText] = useState('')
  const [selected, setSelected] = useState('')
  const [risk, setRisk] = useState(false)
  const [audio, setAudio] = useState<{ url: string; blob: Blob } | null>(null)
  const submission = useRef<{ body: string; key: string } | null>(null)
  const client = useQueryClient()
  const choices = models.filter((m) => m.kind === 'synthesis')
  const model = choices.find((m) => `${m.deployment_id}:${m.id}` === selection) || choices[0]
  const voices = useQuery({
    queryKey: ['voices', model?.id, model?.deployment_id],
    enabled: !!api && !!model,
    queryFn: ({ signal }) =>
      api!.request<Voice[]>(
        `/v1/voices?model=${encodeURIComponent(model!.id)}&deployment_id=${encodeURIComponent(model!.deployment_id || 'default')}`,
        { signal },
      ),
  })
  const chosenVoice = voices.data?.find((v) => v.id === voice)?.id || voices.data?.[0]?.id || ''
  const jobs = useInfiniteQuery({
    queryKey: ['syntheses'],
    initialPageParam: '',
    enabled: !!api,
    queryFn: ({ pageParam, signal }) =>
      api!.request<Page>(
        `/v1/syntheses?limit=30${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ''}`,
        { signal },
      ),
    getNextPageParam: (last) => last.next_cursor || undefined,
    refetchInterval: 4000,
  })
  const status = useQuery({
    queryKey: ['synthesis', selected],
    enabled: !!api && !!selected,
    queryFn: ({ signal }) => api!.request<Job>(`/v1/syntheses/${selected}`, { signal }),
    refetchInterval: (q) => (q.state.data && terminal.has(q.state.data.state) ? false : 2000),
  })
  const job = status.data
  const result = useQuery({
    queryKey: ['synthesis-result', selected, job?.attempt],
    enabled: !!api && job?.state === 'succeeded',
    queryFn: ({ signal }) => api!.request<Result>(`/v1/syntheses/${selected}/result`, { signal }),
  })
  useEffect(() => {
    if (!api || job?.state !== 'succeeded') return
    const controller = new AbortController()
    let url = ''
    void api
      .audio(selected, controller.signal)
      .then((blob) => {
        if (!controller.signal.aborted) {
          url = URL.createObjectURL(blob)
          setAudio({ url, blob })
        }
      })
      .catch(() => {
        /* The download button can retry a failed audio fetch. */
      })
    return () => {
      controller.abort()
      if (url) URL.revokeObjectURL(url)
      setAudio(null)
    }
  }, [api, selected, job?.state, job?.attempt])
  const submit = useMutation({
    retry: false,
    mutationFn: async () => {
      const body = JSON.stringify({
        text,
        options: {
          model: model!.id,
          deployment_id: model!.deployment_id,
          voice: chosenVoice,
          format: model!.formats?.[0] || 'mp3',
          sample_rate: model!.sample_rates?.[0] || 22050,
        },
      })
      if (submission.current?.body !== body) submission.current = { body, key: crypto.randomUUID() }
      return api!.request<Job>('/v1/syntheses', {
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': submission.current.key },
      })
    },
    onSuccess: (data) => {
      setSelected(data.id)
      setText('')
      submission.current = null
      client.setQueryData(['synthesis', data.id], data)
      void client.invalidateQueries({ queryKey: ['syntheses'] })
    },
  })
  const action = useMutation({
    retry: false,
    mutationFn: (kind: 'retry' | 'cancel') =>
      api!.request<Job>(`/v1/syntheses/${selected}/${kind}`, {
        method: 'POST',
        body: kind === 'retry' ? JSON.stringify({ acknowledge_duplicate_risk: risk }) : undefined,
      }),
    onSuccess: (data) => {
      setRisk(false)
      client.setQueryData(['synthesis', data.id], data)
      void client.invalidateQueries({ queryKey: ['syntheses'] })
    },
  })
  const downloading = useMutation({
    mutationFn: async () => audio?.blob || api!.audio(selected),
    onSuccess: (blob) => download(blob, `speech.${result.data?.format || 'mp3'}`),
  })
  const error =
    submit.error ||
    action.error ||
    jobs.error ||
    status.error ||
    result.error ||
    voices.error ||
    downloading.error
  return (
    <div className="workspace-content synthesis-workspace">
      <div className="page-heading">
        <div>
          <h1>{t('Speech synthesis', '语音合成')}</h1>
          <p>
            {t('Turn your text into a complete audio file.', '将文字合成为完整音频，试听后下载。')}
          </p>
        </div>
      </div>
      {!api ? (
        <div className="synthesis-card">
          <p>
            {t(
              'Connect your workspace to create and listen to speech.',
              '连接工作区后即可创建合成任务并试听。',
            )}
          </p>
          <button className="primary" onClick={connect}>
            {t('Connect workspace', '连接工作区')}
          </button>
        </div>
      ) : (
        <>
          <form
            className="synthesis-card"
            onSubmit={(e) => {
              e.preventDefault()
              submit.mutate()
            }}
          >
            <div className="form-grid">
              <label className="field">
                {t('Model and deployment', '模型与部署')}
                <select
                  value={model ? `${model.deployment_id}:${model.id}` : ''}
                  disabled={submit.isPending || !choices.length}
                  onChange={(e) => {
                    setSelection(e.target.value)
                    setVoice('')
                  }}
                >
                  {choices.map((m) => (
                    <option key={`${m.deployment_id}:${m.id}`} value={`${m.deployment_id}:${m.id}`}>
                      {m.id} · {m.deployment_id} ({m.location})
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                {t('Voice', '音色')}
                <select
                  value={chosenVoice}
                  onChange={(e) => setVoice(e.target.value)}
                  disabled={submit.isPending || !voices.data?.length}
                >
                  {voices.data?.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field">
              {t('Text to speak', '待合成文本')}
              <textarea
                rows={7}
                maxLength={model?.max_text_characters || 20000}
                value={text}
                disabled={submit.isPending}
                onChange={(e) => setText(e.target.value)}
                placeholder={t('Enter the complete text…', '输入完整文本…')}
              />
            </label>
            <p className="synthesis-hint">
              {text.length} / {model?.max_text_characters || 20000} ·{' '}
              {model?.formats?.join(', ').toUpperCase()} ·{' '}
              {t('Submitting may incur provider charges.', '提交后可能产生厂商费用。')}
            </p>
            {!choices.length && (
              <p role="status">
                {t('No synthesis deployment is configured.', '尚未配置可用的合成部署。')}
              </p>
            )}
            <button
              className="primary"
              disabled={!text.trim() || !chosenVoice || !model || submit.isPending}
            >
              {submit.isPending
                ? t('Submitting…', '正在提交…')
                : t('Create synthesis', '确认并合成')}
            </button>
          </form>
          {error && (
            <p className="error" role="alert">
              {error.message}
            </p>
          )}
          <div className="synthesis-columns">
            <section className="synthesis-card">
              <h2>{t('Synthesis history', '合成记录')}</h2>
              {jobs.data?.pages
                .flatMap((p) => p.items)
                .map((j) => (
                  <button
                    className={`synthesis-row ${selected === j.id ? 'selected' : ''}`}
                    key={j.id}
                    onClick={() => {
                      setSelected(j.id)
                      setRisk(false)
                      action.reset()
                    }}
                  >
                    <span>
                      {j.options.voice}
                      <small>
                        {j.id.slice(0, 12)} · {j.deployment_id}
                      </small>
                    </span>
                    <span>{labels[job?.id === j.id ? job.state : j.state][zh ? 1 : 0]}</span>
                  </button>
                ))}
              {!jobs.isLoading && !jobs.data?.pages[0]?.items.length && (
                <p>{t('Your audio will appear here.', '合成任务会显示在这里。')}</p>
              )}
              {jobs.hasNextPage && (
                <button
                  className="secondary"
                  disabled={jobs.isFetchingNextPage}
                  onClick={() => void jobs.fetchNextPage()}
                >
                  {t('Load more', '加载更多')}
                </button>
              )}
            </section>
            <section className="synthesis-card" aria-live="polite">
              <h2>{t('Audio preview', '音频试听')}</h2>
              {!job ? (
                <p>{t('Select a synthesis to view its progress.', '选择一个合成任务查看进度。')}</p>
              ) : (
                <>
                  <p>
                    {labels[job.state][zh ? 1 : 0]} · {t('Attempt', '尝试')} {job.attempt}
                  </p>
                  <p className="synthesis-id">{job.id}</p>
                  <p>
                    {job.options.model} · {job.options.voice}
                  </p>
                  {job.error && (
                    <p role="alert" className="error">
                      {job.error.message}
                    </p>
                  )}
                  {job.remote_may_run && (
                    <p>
                      {t(
                        'The provider may still be processing this task.',
                        '厂商侧可能仍在处理此任务。',
                      )}
                    </p>
                  )}
                  {audio && (
                    <audio
                      controls
                      src={audio.url}
                      aria-label={t('Generated speech', '合成音频')}
                    />
                  )}
                  {result.data && (
                    <p>
                      {result.data.format.toUpperCase()} ·{' '}
                      {(result.data.duration_ms / 1000).toFixed(1)}s ·{' '}
                      {result.data.size.toLocaleString()} B
                    </p>
                  )}
                  {job.state === 'succeeded' && (
                    <button
                      className="secondary"
                      disabled={downloading.isPending}
                      onClick={() => downloading.mutate()}
                    >
                      {t('Download audio', '下载音频')}
                    </button>
                  )}
                  {!terminal.has(job.state) && (
                    <button
                      className="secondary"
                      disabled={action.isPending || job.state === 'cancel_requested'}
                      onClick={() => action.mutate('cancel')}
                    >
                      {t('Cancel', '取消任务')}
                    </button>
                  )}
                  {['failed', 'cancelled', 'needs_attention'].includes(job.state) && (
                    <>
                      {(job.remote_may_run || job.state === 'needs_attention') && (
                        <label className="check-field">
                          <input
                            type="checkbox"
                            checked={risk}
                            onChange={(e) => setRisk(e.target.checked)}
                          />
                          {t(
                            'I acknowledge possible duplicate processing and charges.',
                            '我理解可能重复处理并产生费用。',
                          )}
                        </label>
                      )}
                      <button
                        className="secondary"
                        disabled={
                          action.isPending ||
                          job.error?.code === 'result_deleted' ||
                          ((job.remote_may_run || job.state === 'needs_attention') && !risk)
                        }
                        onClick={() => action.mutate('retry')}
                      >
                        {t('Retry / recover', '重试 / 恢复')}
                      </button>
                    </>
                  )}
                </>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
