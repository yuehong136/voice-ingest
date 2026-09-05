# 云端后端，转写用户本地录音

[English](cloud-backend-local-files.md) · **简体中文**

把 Voice Ingest 部署在服务器上，通过对话让 Agent 转写电脑里的录音。
Agent 使用 MCP 协调任务，文件通过 HTTP/S3 上传。拿到持久化任务 ID 后，
可以在下一次对话或网页工作区继续查看结果。

> 转写 `/Users/alex/Recordings/meeting.mp4`，允许调用已配置的付费 ASR 模型。
> 完成后准备 Markdown 和 SRT 导出，并告诉我任务 ID。

以上是示例提示词，不是真实调用记录。MP4 转写识别音轨中的讲话，不包含画面 OCR 或内嵌字幕提取。

## 选择入口

| Agent 运行位置 | 文件如何进入 Voice Ingest | 对应案例 |
| --- | --- | --- |
| 用户电脑，客户端支持启动本地 MCP 进程 | 本地桥接器上传文件 | 案例 A |
| 云端聊天产品，支持远程 HTTP MCP | 用户在网页上传并提交，Agent 接续已有任务 | 案例 B |

聊天附件不会自动变成 MCP 可读文件。聊天产品需要提供可访问的文件，或接入上传接口。
目前 Voice Ingest 没有针对各聊天产品的附件连接器。

## 开始之前

管理员按照[部署指南](../deployment.md)部署 API、worker、PostgreSQL 和私有 S3。
本案例中的 `https://voice.example.com` 是 **API 基础地址占位符**，远程 MCP 位于 `/mcp/`。
如果前端通过 `/api` 代理后端，请使用实际对外路由的 API 基础地址，不要默认网页域名就是 API 地址。

- 阿里密钥配置在后端；客户端通过自己的密钥配置功能保存 **Voice Ingest 工作区访问密钥**。
- 用户电脑需要能访问 API 和 S3 签名上传地址；浏览器直传还需要 S3 CORS 配置。
- 默认 `signed_url` 模式要求 ASR 供应商能访问 S3 签名下载地址。
- 私有桶可以拥有公网网络入口，通过签名请求授权访问，无需将桶设为公开读取。
- 云端供应商无法访问用户电脑的 `localhost`。`temporary_upload` 是明确启用的本地评估选项，不是本案例的生产部署方式。

当前工作区面向可信团队共享使用；API Key 不提供按用户划分的文件和任务隔离。

## 案例 A：本地 MCP 桥接器连接云端后端

用户电脑安装 Python 3.12、uv，再安装轻量客户端：

```bash
git clone https://github.com/yuehong136/voice-ingest.git
cd voice-ingest
uv sync --frozen --extra mcp --extra cli --no-dev
```

本地无需数据库、S3 服务、GPU，也无需开放入站端口。在支持 `mcpServers` 的客户端中添加：

```json
{
  "mcpServers": {
    "voice-ingest": {
      "command": "/absolute/path/to/voice-ingest/.venv/bin/voice-ingest-mcp",
      "args": [
        "--url", "https://voice.example.com",
        "--allow-dir", "/Users/alex/Recordings"
      ],
      "env": {
        "VOICE_API_KEY": "YOUR_WORKSPACE_API_KEY"
      }
    }
  }
}
```

替换可执行文件路径、API 地址、已存在的允许目录和密钥。此 JSON 为通用示例，具体配置格式与
密钥保存方式以客户端为准。可以重复传入 `--allow-dir` 添加目录；桥接器解析真实路径，拒绝目录外文件及符号链接越界。

```mermaid
sequenceDiagram
    participant Agent as Agent 与本地桥接器
    participant API as 云端 API
    participant S3 as 私有 S3
    participant Worker as 云端 worker
    participant ASR as ASR 供应商
    Agent->>API: 创建上传会话
    API-->>Agent: 分片签名上传地址
    Agent->>S3: 通过 HTTP 上传文件分片
    Agent->>API: 完成上传
    API-->>Agent: asset_id
    Agent->>API: 提交转写
    API-->>Agent: 立即返回 job_id
    Worker->>ASR: 提交签名音频地址
    ASR->>S3: 下载录音
    Worker->>ASR: 轮询并获取结果
    Worker->>S3: 保存结果与导出文件
    Agent->>API: 查询任务与读取转写
```

预期工具调用顺序：

| 工具 | 示例参数 | 返回内容 |
| --- | --- | --- |
| `list_models` | `{}` | 已配置的模型能力 |
| `upload_local_audio` | `{"path":"/Users/alex/Recordings/meeting.mp4"}` | 文件记录，其 `id` 即 `asset_id` |
| `submit_transcription` | `{"asset_id":"ASSET_ID","idempotency_key":"UNIQUE_KEY_FOR_THIS_REQUEST"}` | 任务记录，其 `id` 即 `job_id` |
| `get_transcription` | `{"job_id":"JOB_ID"}` | 持久化任务状态 |
| `read_transcript` | `{"job_id":"JOB_ID","limit":50}` | 一页句段，通过 `next_cursor` 继续读取 |
| `export_transcript` | `{"job_id":"JOB_ID","format":"markdown"}` | 需要鉴权的 API 下载路径 |

实际调用使用上一步返回的 ID，不能照搬占位符。等待 `succeeded` 后读取和导出；第二份导出使用 `srt`。
同一次提交丢失网络响应时复用原幂等键。单独上传不会开始识别，向真实供应商提交转写可能产生费用。

## 案例 B：网页上传，云端 Agent 接续处理

1. 打开部署后的网页工作区，使用工作区访问密钥连接。
2. 在网页上传录音并提交转写。
3. 在云端 Agent 中配置 HTTP MCP：地址 `https://voice.example.com/mcp/`，请求头 `Authorization: Bearer YOUR_WORKSPACE_API_KEY`。
4. 让 Agent 使用 `list_transcriptions` 查找已有任务，再用 `get_transcription` 查询；若存在多个候选任务，先确认目标任务。

> 找到我刚提交的转写任务，告诉我状态和任务 ID。成功后读取前五分钟的文字，
> 并准备 Markdown 导出。使用已有任务。

远程 MCP 操作项目管理的文件和任务，不能读取用户电脑的 `/Users/...` 路径，也不支持提交任意远程文件 URL。
如果通过 SDK/API 只上传了文件，可以将返回的 `asset_id` 交给 `submit_transcription`。
当前网页流程已经创建转写任务，不需要再次提交。

## 稍后继续与下载结果

关闭对话不会取消后端任务。下次对话可以提供 `job_id`，或通过 `list_transcriptions` 查找。
是否自动轮询、主动通知取决于 Agent 客户端；服务端不会在识别完成后自行发送新的聊天消息。

长转写使用分页，或用 `start_ms`、`end_ms` 指定时间范围。
`export_transcript` 返回下载路径，不会直接附加文件，也不是公开下载链接。
客户端下载时必须携带工作区 Bearer Token，也可以在已连接的网页工作区下载，或使用 CLI：

```bash
# 使用自己的密钥管理方式，在 shell 中设置 VOICE_API_KEY。
export VOICE_URL=https://voice.example.com
uv run --no-sync voice-ingest export JOB_ID --format markdown --output meeting.md
uv run --no-sync voice-ingest export JOB_ID --format srt --output meeting.srt
```

在前面安装客户端的项目目录中执行命令。SRT/VTT 要求结果具有有效时间戳。
遇到 `needs_attention` 时先检查再重试：供应商可能已接受收费任务。不要用重试操作查询进度。

生产网络与部署检查见[部署指南](../deployment.md)，已经完成的验证及限制见[验收记录](../acceptance.md)。
