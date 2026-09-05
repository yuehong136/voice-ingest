import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { LoaderCircle, ShieldCheck } from 'lucide-react'
import { Api, ApiError, type Model } from '../api'
import { Modal } from '../components/Modal'

export function Connection({
  zh,
  connect,
  close,
}: {
  zh: boolean
  connect: (api: Api) => void
  close: () => void
}) {
  const [key, setKey] = useState('')
  const mutation = useMutation({
    mutationFn: async () => {
      const api = new Api(key.trim())
      await api.request<Model[]>('/v1/models')
      return api
    },
    onSuccess: connect,
  })
  return (
    <Modal title={zh ? '连接工作区' : 'Connect your workspace'} close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
      >
        <p className="muted">
          {zh
            ? '输入后端管理员设置的工作区访问密钥，即可上传文件并查看转写结果。密钥仅保留在当前页面内存中。'
            : 'Enter the workspace access key configured by your backend administrator to upload files and read transcripts. The key stays in this tab’s memory.'}
        </p>
        <label className="field">
          {zh ? '工作区访问密钥' : 'Workspace access key'}
          <input
            autoFocus
            type="password"
            required
            value={key}
            onChange={(e) => {
              setKey(e.target.value)
              mutation.reset()
            }}
            autoComplete="off"
            placeholder="VOICE_API_KEY"
          />
        </label>
        <p className="help">
          {zh
            ? '对应后端 VOICE_API_KEY。阿里模型密钥由后端单独配置，无需在这里填写。'
            : 'This is the backend VOICE_API_KEY. Aliyun model credentials are configured separately on the backend.'}
        </p>
        {mutation.error && (
          <p role="alert" className="error">
            {mutation.error instanceof ApiError && mutation.error.status === 401
              ? zh
                ? '工作区访问密钥不正确。请使用后端的 VOICE_API_KEY；阿里 API Key 不能用于登录工作区。'
                : 'Workspace access key is incorrect. Use the backend VOICE_API_KEY; an Aliyun API key cannot sign in to this workspace.'
              : mutation.error.message}
          </p>
        )}
        <button className="primary full" disabled={!key.trim() || mutation.isPending}>
          {mutation.isPending ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <ShieldCheck size={17} />
          )}{' '}
          {zh ? '连接工作区' : 'Connect workspace'}
        </button>
      </form>
    </Modal>
  )
}
