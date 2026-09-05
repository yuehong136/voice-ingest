import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AudioLines,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Download,
  FileAudio,
  FolderOpen,
  Globe2,
  Headphones,
  LoaderCircle,
  RefreshCw,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  X,
  Unplug,
  CircleAlert,
  Code2,
  Copy,
} from 'lucide-react'
import {
  Api,
  download,
  terminal,
  time,
  type Asset,
  type Format,
  type Job,
  type JobPage,
  type Model,
  type Page,
} from './api'
import { demoAssets, demoJobs, demoModels, demoSegments } from './demo'
import { labels } from './status'
import { JobRow } from './recordings/JobRow'
import { UploadModal, type UploadDraft } from './recordings/UploadModal'
import { Connection } from './connection/Connection'

export default function App() {
  const [zh, setZh] = useState(() => {
    try {
      return localStorage.getItem('voice-language') === 'zh'
    } catch {
      return false
    }
  })
  const t = (en: string, cn: string) => (zh ? cn : en)
  const [api, setApi] = useState<Api | null>(null)
  const [preview, setPreview] = useState(false)
  const [draft, setDraft] = useState<UploadDraft | null>(null)
  const [filter, setFilter] = useState('all')
  const [dialog, setDialog] = useState<'connect' | 'upload' | null>(null)
  const [selected, setSelected] = useState('sample-1')
  const [search, setSearch] = useState('')
  const [format, setFormat] = useState<Format>('markdown')
  const [notice, setNotice] = useState('')
  const [playback, setPlayback] = useState<{ id: string; url: string } | null>(null)
  const [risk, setRisk] = useState(false)
  const audio = useRef<HTMLAudioElement>(null)
  const client = useQueryClient()
  useEffect(() => {
    document.documentElement.lang = zh ? 'zh-CN' : 'en'
    try {
      localStorage.setItem('voice-language', zh ? 'zh' : 'en')
    } catch {
      /* Language preference is optional. */
    }
  }, [zh])
  useEffect(
    () => () => {
      if (playback) URL.revokeObjectURL(playback.url)
    },
    [playback],
  )
  useEffect(() => {
    setSearch('')
    setRisk(false)
    setNotice('')
  }, [selected])
  const models = useQuery({
    queryKey: ['models'],
    queryFn: ({ signal }) => api!.request<Model[]>('/v1/models', { signal }),
    enabled: !!api,
  })
  const jobs = useInfiniteQuery({
    queryKey: ['jobs'],
    initialPageParam: '',
    enabled: !!api,
    queryFn: ({ pageParam, signal }) =>
      api!.request<JobPage>(
        `/v1/transcriptions?limit=30${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ''}`,
        { signal },
      ),
    getNextPageParam: (last) => last.next_cursor || undefined,
    refetchInterval: 4000,
  })
  const records = api ? jobs.data?.pages.flatMap((p) => p.items) || [] : preview ? demoJobs : []
  const visibleRecords = records.filter(
    (record) =>
      filter === 'all' ||
      (filter === 'active'
        ? !terminal.has(record.state)
        : filter === 'ready'
          ? record.state === 'succeeded'
          : ['failed', 'needs_attention', 'cancelled'].includes(record.state)),
  )
  const jobQuery = useQuery({
    queryKey: ['job', selected],
    enabled: !!api && !!selected,
    queryFn: ({ signal }) => api!.request<Job>(`/v1/transcriptions/${selected}`, { signal }),
    refetchInterval: (q) => (q.state.data && terminal.has(q.state.data.state) ? false : 2500),
  })
  const job = api ? jobQuery.data : preview ? demoJobs.find((j) => j.id === selected) : undefined
  const asset = useQuery({
    queryKey: ['asset', job?.asset_id],
    enabled: !!api && !!job,
    queryFn: ({ signal }) => api!.request<Asset>(`/v1/assets/${job!.asset_id}`, { signal }),
    refetchInterval: job && !terminal.has(job.state) ? 4000 : false,
  })
  const source = api ? asset.data : demoAssets.find((a) => a.id === job?.asset_id)
  const transcript = useInfiniteQuery({
    queryKey: ['segments', selected, job?.attempt],
    initialPageParam: '',
    enabled: !!api && job?.state === 'succeeded',
    queryFn: ({ pageParam, signal }) =>
      api!.request<Page>(
        `/v1/transcriptions/${selected}/segments?limit=50${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ''}`,
        { signal },
      ),
    getNextPageParam: (last) => last.next_cursor || undefined,
  })
  const segments = api ? transcript.data?.pages.flatMap((p) => p.segments) || [] : demoSegments(zh)
  const filtered = segments.filter((s) =>
    s.text.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  )
  const action = useMutation({
    mutationFn: async (kind: 'cancel' | 'retry') =>
      api!.request<Job>(`/v1/transcriptions/${selected}/${kind}`, {
        method: 'POST',
        body: kind === 'retry' ? JSON.stringify({ acknowledge_duplicate_risk: risk }) : undefined,
      }),
    onSuccess: (data) => {
      client.setQueryData(['job', selected], data)
      void client.invalidateQueries({ queryKey: ['jobs'] })
      void client.invalidateQueries({ queryKey: ['segments', selected] })
    },
  })
  const exporting = useMutation({
    mutationFn: async () => {
      if (!api) {
        if (format === 'json')
          return new Blob([JSON.stringify({ demo: true, segments }, null, 2)], {
            type: 'application/json',
          })
        const stamp = (ms: number, comma: boolean) =>
          new Date(ms)
            .toISOString()
            .slice(11, 23)
            .replace('.', comma ? ',' : '.')
        const text =
          format === 'srt' || format === 'vtt'
            ? (format === 'vtt' ? 'WEBVTT\n\n' : '') +
              segments
                .map(
                  (s, i) =>
                    `${format === 'srt' ? `${i + 1}\n` : ''}${stamp(s.start_ms!, format === 'srt')} --> ${stamp(s.end_ms!, format === 'srt')}\n${s.text}\n`,
                )
                .join('\n')
            : segments.map((s) => s.text).join('\n\n')
        return new Blob([text], { type: 'text/plain;charset=utf-8' })
      }
      return api.export(selected, format)
    },
    onSuccess: (blob) => {
      download(
        blob,
        `${api ? 'transcript' : 'sample-transcript'}.${format === 'markdown' ? 'md' : format}`,
      )
      setNotice(t('Export downloaded.', '导出已下载。'))
    },
  })
  const error =
    jobs.error ||
    jobQuery.error ||
    models.error ||
    asset.error ||
    transcript.error ||
    action.error ||
    exporting.error
  function switchConnection(next: Api | null) {
    setApi(next)
    setPreview(false)
    setDraft(null)
    setFilter('all')
    client.clear()
    setSelected(next ? '' : 'sample-1')
    setPlayback(null)
    setDialog(null)
    setNotice('')
  }
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#">
          <span className="brand-mark">
            <AudioLines size={24} />
          </span>
          voice ingest<span className="brand-period">.</span>
        </a>
        <div className="workspace-label">
          <span className="workspace-avatar">V</span>
          <span>
            {t('Transcription workspace', '语音转写工作区')}
            <small>
              {api ? t('Connected workspace', '已连接工作区') : t('Not connected', '尚未连接')}
            </small>
          </span>
        </div>
        <nav aria-label={t('Workspace', '工作区')}>
          <button
            className="nav-item active"
            onClick={() => document.querySelector('main')?.scrollIntoView()}
          >
            <FolderOpen size={19} />
            {t('Recordings', '录音工作台')}
            <span>{records.length}</span>
          </button>
          <button className="nav-item" onClick={() => setDialog('connect')}>
            <Settings2 size={19} />
            {t('Connection', '连接设置')}
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="workflow-note">
            <AudioLines size={27} />
            <h3>{t('Keep the conversation.', '让每段对话可查可用。')}</h3>
            <p>
              {t(
                'A transcript you can read, search, and build with.',
                '阅读、查找、导出，让每段录音都有下文。',
              )}
            </p>
          </div>
          <a
            className="source-link"
            href="https://github.com/yuehong136/voice-ingest"
            target="_blank"
            rel="noreferrer"
          >
            <Code2 size={17} />
            {t('Open source on GitHub', '在 GitHub 查看源码')}
            <ArrowUpRight size={14} />
          </a>
          <div className="sidebar-foot">
            <span>
              v0.1 <span className="dot">·</span> MIT
            </span>
            <button className="text-button" onClick={() => setZh(!zh)}>
              <Globe2 size={15} />
              {zh ? 'English' : '中文'}
            </button>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            {t('Workspace', '工作区')}
            <span>/</span>
            <strong>{t('Recordings', '录音')}</strong>
          </div>
          <div className="topbar-actions">
            <span className={`connection-pill ${api ? 'connected' : ''}`}>
              <span />
              {api
                ? t('Connected', '已连接')
                : preview
                  ? t('Sample content', '示例内容')
                  : t('Not connected', '未连接')}
            </span>
            <button
              className="avatar"
              aria-label={t('Connection settings', '连接设置')}
              onClick={() => setDialog('connect')}
            >
              V
            </button>
          </div>
        </header>
        <div className="workspace-content">
          <div className="page-heading">
            <div>
              <h1>{t('Transcriptions', '转写工作台')}</h1>
              <p>
                {t(
                  'Upload recordings. Review transcripts. Deliver the words that matter.',
                  '上传录音，核对正文，让每一次对话都有清晰的记录。',
                )}
              </p>
            </div>
            <button
              className="primary"
              onClick={() => setDialog(api ? 'upload' : 'connect')}
              disabled={!!api && !models.data?.length}
            >
              <Plus size={19} />
              {draft ? t('Continue setup', '继续转写设置') : t('New transcription', '新建转写')}
            </button>
          </div>
          {!api ? (
            <div className="demo-banner">
              <span className="sample-tag">
                {preview
                  ? t('Sample workspace', '示例工作区')
                  : t('Workspace access', '工作区访问')}
              </span>
              <p>
                {t(
                  'Connect your workspace to upload recordings and access your transcripts.',
                  '连接工作区，上传自己的录音并查看转写结果。',
                )}
              </p>
              <button className="text-button" onClick={() => setDialog('connect')}>
                {t('Connect backend', '连接后端')}
                <ArrowUpRight size={16} />
              </button>
            </div>
          ) : (
            <div className="live-banner">
              <ShieldCheck size={17} />
              <span>
                {models.data?.[0]?.provider === 'mock'
                  ? t(
                      'Mock provider · uploads are real, transcripts are synthetic.',
                      '模拟供应商：上传真实文件，生成模拟转写文本。',
                    )
                  : t(
                      'Cloud ASR · submitting recordings may incur charges.',
                      '云端 ASR：提交录音可能产生识别费用。',
                    )}
              </span>
              <button className="text-button" onClick={() => switchConnection(null)}>
                <Unplug size={14} />
                {t('Disconnect', '断开')}
              </button>
            </div>
          )}
          {error && (
            <div className="error global-error" role="alert">
              <CircleAlert size={18} />
              <span>{error.message}</span>
              <button
                className="text-button"
                onClick={() => {
                  void client.invalidateQueries()
                  action.reset()
                  exporting.reset()
                }}
              >
                {t('Refresh', '刷新')}
              </button>
            </div>
          )}
          {!api && !preview ? (
            <section className="welcome-panel">
              <div className="welcome-copy">
                <Headphones size={38} />
                <h2>
                  {t('Every conversation, ready to work with.', '把完整对话，留成可用的文字。')}
                </h2>
                <p>
                  {t(
                    'A focused workspace for interviews, meetings and long recordings. Keep the source, follow the progress, and export a transcript with its original timestamps.',
                    '为访谈、会议与长录音准备的工作区。保留原始文件，跟踪处理进度，导出带原始时间戳的转写记录。',
                  )}
                </p>
                <div className="welcome-actions">
                  <button className="primary" onClick={() => setDialog('connect')}>
                    {t('Connect workspace', '连接工作区')}
                  </button>
                  <button
                    className="secondary"
                    onClick={() => {
                      setPreview(true)
                      setSelected('sample-1')
                    }}
                  >
                    {t('Explore sample transcript', '查看示例转写')}
                  </button>
                </div>
                <p className="help">
                  {t(
                    'Your workspace access key is provided by the service operator.',
                    '工作区访问密钥由服务管理员提供。',
                  )}
                </p>
              </div>
              <ol className="welcome-flow">
                <li>
                  <span>1</span>
                  <div>
                    <h3>{t('Upload your file', '上传文件')}</h3>
                    <p>
                      {t(
                        'Audio and video, with resumable uploads.',
                        '支持音频与视频，上传中断可恢复。',
                      )}
                    </p>
                  </div>
                </li>
                <li>
                  <span>2</span>
                  <div>
                    <h3>{t('Review and start', '确认后开始转写')}</h3>
                    <p>
                      {t(
                        'Choose language and speaker settings before recognition.',
                        '识别前确认语言与说话人设置。',
                      )}
                    </p>
                  </div>
                </li>
                <li>
                  <span>3</span>
                  <div>
                    <h3>{t('Read and export', '阅读与导出')}</h3>
                    <p>
                      {t(
                        'Search transcripts and download five formats.',
                        '查找正文，下载五种格式的结果。',
                      )}
                    </p>
                  </div>
                </li>
              </ol>
            </section>
          ) : (
            <div className="studio">
              <section className="library" aria-label={t('Recordings', '录音列表')}>
                <div className="library-heading">
                  <h2>{t('All recordings', '全部录音')}</h2>
                  <span className="count">{records.length}</span>
                  <button
                    className="icon-button"
                    aria-label={t('Refresh recordings', '刷新录音')}
                    onClick={() => void client.invalidateQueries({ queryKey: ['jobs'] })}
                  >
                    <RefreshCw size={19} />
                  </button>
                </div>
                <div
                  className="library-filters"
                  role="group"
                  aria-label={t('Filter recordings', '筛选录音')}
                >
                  {(['all', 'active', 'ready', 'attention'] as const).map((value, i) => (
                    <button
                      key={value}
                      aria-pressed={filter === value}
                      onClick={() => setFilter(value)}
                    >
                      {
                        [
                          t('All', '全部'),
                          t('Processing', '处理中'),
                          t('Ready', '已完成'),
                          t('Attention', '需处理'),
                        ][i]
                      }
                    </button>
                  ))}
                </div>
                {draft && (
                  <button className="pending-upload" onClick={() => setDialog('upload')}>
                    <FileAudio size={19} />
                    <span>
                      <strong>{draft.file.name}</strong>
                      <small>{t('Uploaded · ready to configure', '已上传 · 等待确认转写')}</small>
                    </span>
                  </button>
                )}
                <div className="recordings">
                  {visibleRecords.map((record) => (
                    <JobRow
                      key={record.id}
                      job={record}
                      api={api}
                      active={selected === record.id}
                      zh={zh}
                      onSelect={() => setSelected(record.id)}
                    />
                  ))}
                  {records.length > 0 && !visibleRecords.length && (
                    <p className="empty-small">
                      {t('No recordings in this view.', '此分类暂无录音。')}
                    </p>
                  )}
                  {api && jobs.isPending && (
                    <p className="empty-small">
                      <LoaderCircle className="spin" size={20} />
                      {t('Loading recordings…', '正在加载录音…')}
                    </p>
                  )}
                  {api && !jobs.isPending && !records.length && (
                    <div className="empty-small">
                      <Headphones size={26} />
                      <p>{t('Your first recording starts here.', '从第一段录音开始。')}</p>
                    </div>
                  )}
                </div>
                {jobs.hasNextPage && (
                  <button
                    className="text-button load-more"
                    disabled={jobs.isFetchingNextPage}
                    onClick={() => void jobs.fetchNextPage()}
                  >
                    {t('Load more', '加载更多')}
                  </button>
                )}
                <div className="library-footer">
                  <ShieldCheck size={15} />
                  {t('Private storage. Durable jobs.', '私有存储，任务持久保存。')}
                </div>
              </section>
              <section className="reader" aria-label={t('Transcript', '转写结果')}>
                {!job ? (
                  <div className="empty-reader">
                    <span className="empty-icon">
                      <AudioLines size={35} />
                    </span>
                    <h2>{t('Select a recording to get started', '选择录音，查看完整记录')}</h2>
                    <p>
                      {t(
                        'Select a recording or upload a new one to get started.',
                        '选择一段录音，或上传新文件开始转写。',
                      )}
                    </p>
                    <button
                      className="primary"
                      onClick={() => setDialog(api ? 'upload' : 'connect')}
                      disabled={!!api && !models.data?.length}
                    >
                      <Plus size={18} />
                      {t('New transcription', '新建转写')}
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="reader-heading">
                      <div>
                        <div className={`status-badge ${job.state}`}>
                          {job.state === 'succeeded' ? (
                            <CheckCircle2 size={14} />
                          ) : (
                            <Clock3 size={14} />
                          )}{' '}
                          {labels[job.state]?.[zh ? 1 : 0]}
                        </div>
                        <h2>{source?.filename.replace(/\.[^.]+$/, '') || job.id.slice(0, 12)}</h2>
                        <p className="recording-meta">
                          <FileAudio size={14} />
                          {source?.filename.split('.').pop()?.toUpperCase() || 'Audio'}
                          <span className="dot">·</span>
                          {time(source?.duration_ms)}
                          <span className="dot">·</span>
                          {source ? `${(source.size / 1e6).toFixed(1)} MB` : '—'}
                        </p>
                        {api && (
                          <button
                            className="text-button job-reference"
                            onClick={async () => {
                              try {
                                await navigator.clipboard.writeText(job.id)
                                setNotice(
                                  t(
                                    'Job ID copied. Use it with your agent or SDK.',
                                    '任务 ID 已复制，可交给 Agent 或 SDK 使用。',
                                  ),
                                )
                              } catch {
                                setNotice(
                                  t(
                                    'Copy unavailable. Select the job ID below.',
                                    '无法自动复制，请选择下方任务 ID。',
                                  ),
                                )
                              }
                            }}
                          >
                            <Copy size={13} />
                            {t('Copy job ID', '复制任务 ID')}
                          </button>
                        )}
                        {api && (
                          <details className="job-details">
                            <summary>{t('Task details', '任务详情')}</summary>
                            <dl>
                              <dt>{t('Job ID', '任务 ID')}</dt>
                              <dd>{job.id}</dd>
                              <dt>{t('Asset ID', '文件 ID')}</dt>
                              <dd>{job.asset_id}</dd>
                              <dt>{t('Submitted', '提交时间')}</dt>
                              <dd>
                                {new Date(job.created_at).toLocaleString(zh ? 'zh-CN' : 'en')}
                              </dd>
                              <dt>{t('Attempt', '调用次数')}</dt>
                              <dd>{job.attempt}</dd>
                            </dl>
                          </details>
                        )}
                      </div>
                      <div className="export-control">
                        <label className="sr-only" htmlFor="format">
                          {t('Export format', '导出格式')}
                        </label>
                        <select
                          id="format"
                          value={format}
                          onChange={(e) => setFormat(e.target.value as Format)}
                        >
                          <option value="markdown">Markdown</option>
                          <option value="txt">TXT</option>
                          <option value="json">JSON</option>
                          <option value="srt">SRT</option>
                          <option value="vtt">VTT</option>
                        </select>
                        <button
                          className="secondary"
                          disabled={job.state !== 'succeeded' || exporting.isPending}
                          onClick={() => exporting.mutate()}
                        >
                          <Download size={16} />
                          {t('Export', '导出')}
                        </button>
                      </div>
                    </div>
                    <div className="audio-overview">
                      <div className="audio-label">
                        <AudioLines size={17} />
                        <strong>{t('Loaded segment timeline', '已加载句段时间轴')}</strong>
                        <span>{time(source?.duration_ms)}</span>
                      </div>
                      <div
                        className="timeline"
                        aria-label={t('Transcript segment positions', '转写句段位置')}
                      >
                        {segments.map(
                          (s, i) =>
                            s.start_ms != null &&
                            s.end_ms != null && (
                              <span
                                key={i}
                                style={{
                                  left: `${(s.start_ms / (source?.duration_ms || 1)) * 100}%`,
                                  width: `${Math.max(0.2, ((s.end_ms - s.start_ms) / (source?.duration_ms || 1)) * 100)}%`,
                                  background: i % 2 ? '#8caadd' : '#3569c8',
                                }}
                              />
                            ),
                        )}
                      </div>
                      <div className="timeline-ticks">
                        <span>00:00</span>
                        <span>{time((source?.duration_ms || 0) / 2)}</span>
                        <span>{time(source?.duration_ms)}</span>
                      </div>
                      {playback?.id === selected ? (
                        <audio ref={audio} controls src={playback.url} className="audio-player" />
                      ) : (
                        <p className="audio-hint">
                          {api
                            ? t(
                                'Local playback is available for files uploaded in this tab.',
                                '在本页面上传的文件可直接回听。',
                              )
                            : t(
                                'Sample transcript · illustrative text, no source audio.',
                                '示例转写 · 演示文本，不包含原始音频。',
                              )}
                        </p>
                      )}
                    </div>
                    <div className="transcript-toolbar">
                      <div className="tab-label">
                        {t('Transcript', '转写正文')}
                        <span>{segments.length}</span>
                      </div>
                      <label className="search-box">
                        <Search size={16} />
                        <input
                          aria-label={t('Search loaded transcript', '搜索已加载正文')}
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                          placeholder={t('Search loaded text', '搜索已加载的正文')}
                        />
                        {search && (
                          <button
                            className="icon-button"
                            aria-label={t('Clear search', '清空搜索')}
                            onClick={() => setSearch('')}
                          >
                            <X size={14} />
                          </button>
                        )}
                      </label>
                    </div>
                    <div className="transcript-content">
                      {job.state === 'succeeded' ? (
                        <>
                          {transcript.isPending && api && (
                            <p className="empty-small">
                              <LoaderCircle size={20} className="spin" />
                              {t('Loading transcript…', '加载转写结果…')}
                            </p>
                          )}
                          {filtered.map((segment, i) => (
                            <article className="segment" key={`${segment.start_ms}-${i}`}>
                              <button
                                className="timestamp"
                                disabled={playback?.id !== selected || segment.start_ms == null}
                                onClick={() => {
                                  if (audio.current && segment.start_ms != null) {
                                    audio.current.currentTime = segment.start_ms / 1000
                                    void audio.current
                                      .play()
                                      .catch(() =>
                                        setNotice(t('Press play to listen.', '点击播放即可回听。')),
                                      )
                                  }
                                }}
                              >
                                {time(segment.start_ms)}
                              </button>
                              <div>
                                <span className="speaker">
                                  <span />
                                  {segment.speaker_id != null
                                    ? `${t('Speaker', '说话人')} ${segment.speaker_id}`
                                    : t('Audio', '录音')}
                                </span>
                                <p>{segment.text}</p>
                              </div>
                            </article>
                          ))}
                          {!filtered.length && !transcript.isFetching && (
                            <p className="empty-small">
                              {t(
                                'No matching text in the loaded segments.',
                                '已加载句段中没有匹配内容。',
                              )}
                            </p>
                          )}
                          {transcript.hasNextPage && (
                            <button
                              className="secondary load-more"
                              disabled={transcript.isFetchingNextPage}
                              onClick={() => void transcript.fetchNextPage()}
                            >
                              <ChevronDown size={16} />
                              {t('Load more transcript', '加载更多正文')}
                            </button>
                          )}
                          {transcript.data?.pages[0]?.warnings?.map((warning) => (
                            <p className="callout" key={warning}>
                              {warning}
                            </p>
                          ))}
                        </>
                      ) : (
                        <div className="job-progress">
                          <AudioLines
                            size={34}
                            className={!terminal.has(job.state) ? 'pulse' : ''}
                          />
                          <h3>{labels[job.state]?.[zh ? 1 : 0]}</h3>
                          <p>
                            {job.error?.message ||
                              t(
                                'You can leave this page. Your job will keep running.',
                                '可以离开页面，任务将在后台继续。',
                              )}
                          </p>
                          {job.remote_may_run && (
                            <p className="callout">
                              {t(
                                'The provider may still be processing and charging for this job.',
                                '供应商可能仍在执行任务并计费。',
                              )}
                            </p>
                          )}
                          {['failed', 'needs_attention', 'cancelled'].includes(job.state) && (
                            <>
                              {(job.remote_may_run || job.state === 'needs_attention') && (
                                <label className="check-field">
                                  <input
                                    type="checkbox"
                                    checked={risk}
                                    onChange={(e) => setRisk(e.target.checked)}
                                  />
                                  {t(
                                    'I understand retrying may duplicate recognition charges.',
                                    '我理解重试可能产生重复识别费用。',
                                  )}
                                </label>
                              )}
                              <button
                                className="secondary"
                                disabled={
                                  action.isPending ||
                                  ((job.remote_may_run || job.state === 'needs_attention') && !risk)
                                }
                                onClick={() => action.mutate('retry')}
                              >
                                {t('Retry job', '重试任务')}
                              </button>
                            </>
                          )}
                          {!terminal.has(job.state) && (
                            <button
                              className="secondary"
                              disabled={action.isPending || job.state === 'cancel_requested'}
                              onClick={() => action.mutate('cancel')}
                            >
                              {t('Cancel job', '取消任务')}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                    <footer className="reader-footer">
                      <span>
                        <Check size={14} />
                        {api ? job.options.model : t('Sample content', '示例内容')}
                      </span>
                      <span>{t('Original timestamps', '保留原始时间轴')}</span>
                    </footer>
                  </>
                )}
              </section>
            </div>
          )}
          <footer className="page-footer">
            <span>{t('Built for long conversations.', '为长录音而设计。')}</span>
            <span>
              HTTP API <span className="dot">/</span> Python SDK <span className="dot">/</span> MCP
            </span>
          </footer>
        </div>
      </main>
      {notice && (
        <div role="status" className="toast">
          <CheckCircle2 size={17} />
          {notice}
          <button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss">
            <X size={16} />
          </button>
        </div>
      )}
      {dialog === 'connect' && (
        <Connection zh={zh} close={() => setDialog(null)} connect={switchConnection} />
      )}
      {dialog === 'upload' && api && (
        <UploadModal
          api={api}
          models={models.data || demoModels}
          draft={draft}
          prepared={setDraft}
          zh={zh}
          close={() => setDialog(null)}
          complete={(newJob, file) => {
            setDraft(null)
            setFilter('all')
            setSelected(newJob.id)
            setPlayback({ id: newJob.id, url: URL.createObjectURL(file) })
            setDialog(null)
            client.setQueryData(['job', newJob.id], newJob)
            void client.invalidateQueries({ queryKey: ['jobs'] })
          }}
        />
      )}
    </div>
  )
}
