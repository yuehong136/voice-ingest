import type { Job, Asset, Model, Segment } from './api'
export const demoModels: Model[] = [
  {
    id: 'qwen-audio-3.0-asr-flash-filetrans',
    provider: 'mock',
    context: true,
    diarization: true,
    max_bytes: 2_000_000_000,
    max_duration_ms: 43200000,
    max_diarization_ms: 7200000,
    max_language_hints: 1,
  },
]
export const demoJobs: Job[] = ['Product discovery', 'Research interview', 'Design review'].map(
  (_, i) => ({
    id: `sample-${i + 1}`,
    asset_id: `asset-${i + 1}`,
    state: 'succeeded',
    attempt: 1,
    options: { model: 'qwen-audio-3.0-asr-flash-filetrans', diarization: true },
    created_at: '2026-09-05T09:00:00Z',
    updated_at: '2026-09-05T09:01:00Z',
    remote_may_run: false,
  }),
)
export const demoAssets: Asset[] = [
  'Product discovery.wav',
  'Research interview.m4a',
  'Design review.mp3',
].map((filename, i) => ({
  id: `asset-${i + 1}`,
  filename,
  size: 12400000 + i * 2000000,
  duration_ms: 192000 + i * 60000,
}))
export function demoSegments(zh: boolean): Segment[] {
  const texts = zh
    ? [
        '今天我们想回答一个问题：一段录音结束之后，怎样让里面的想法真正被用起来？',
        '现在最大的障碍是重新寻找上下文。大家记得有人说过，但不记得在第几分钟。',
        '所以时间戳很重要。它让文字和原始录音保持联系，也让复核变得简单。',
        '我们先把流程做好：上传录音，离开页面，回来的时候结果还在。',
        '然后让结果走进大家已经在用的工具。开发者可以调用接口，Agent 可以直接查询。',
        '导出也应该简单。同一份内容，阅读用 Markdown，剪辑用字幕，程序用 JSON。',
        '第一步就从这里开始：让每一次对话，都有一个清晰、可继续使用的结果。',
      ]
    : [
        'Let’s start with one question: when a recording ends, how do we put the ideas inside it to work?',
        'The hardest part is finding the context again. People remember something was said, but not at which minute.',
        'That’s why timestamps matter. They keep the text connected to the original recording and make review straightforward.',
        'Let’s get the workflow right first. Upload a recording, leave the page, and come back to a result that is still there.',
        'Then bring that result into the tools people already use. Developers can call an API. Agents can query the transcript.',
        'Export should be simple too. The same content: Markdown for reading, subtitles for editing, JSON for your code.',
        'That’s a useful place to begin. Give every conversation a clear result that people can keep working with.',
      ]
  return texts.map((text, i) => ({
    text,
    start_ms: i * 25000,
    end_ms: i * 25000 + 19000,
    speaker_id: i % 2 ? '1' : '0',
    channel_id: 0,
  }))
}
