export const labels: Record<string, [string, string]> = {
  queued: ['Queued', '排队中'],
  preparing: ['Checking audio', '检查音频'],
  submitting: ['Submitting', '提交中'],
  running: ['Transcribing', '转写中'],
  finalizing: ['Saving transcript', '保存结果'],
  succeeded: ['Ready', '已完成'],
  failed: ['Failed', '失败'],
  cancelled: ['Cancelled', '已取消'],
  cancel_requested: ['Cancelling', '取消中'],
  needs_attention: ['Needs attention', '待处理'],
}
