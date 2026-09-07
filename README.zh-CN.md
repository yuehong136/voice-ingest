# Voice Ingest

**把长录音变成可阅读、可检索、可继续使用的文字。**

面向个人、开发者与 AI Agent 的自托管转写工作台。在网页上传，用终端批量处理，或让 MCP 客户端接续同一个持久化任务。

[English](README.md) · **简体中文**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Checks](https://github.com/yuehong136/voice-ingest/actions/workflows/check.yml/badge.svg)](https://github.com/yuehong136/voice-ingest/actions/workflows/check.yml)

[体验工作台](#体验工作台) · [快速开始](#快速开始) · [Web 工作台](#web-工作台) · [MCP](#mcp) · [Python SDK](#python-sdk) · [CLI](#cli) · [部署指南](docs/deployment.md)

![Voice Ingest 中文示例工作台：录音列表、说话人分段、原始时间戳、正文搜索与导出](docs/assets/screenshots/workspace-zh-CN.png)

*实际运行的 Web 界面，使用项目内置的合成示例内容，未展示私人录音或真实 ASR 结果。[复现这些截图](docs/assets/screenshots/README.md)。*

Voice Ingest 处理云端 ASR 周边的工程工作：断点续传、异步任务、重启恢复和统一导出。适用于个人或内部可信团队，通过 API Key 访问共享工作区。

## 为什么选择 Voice Ingest？

- **长录音，有界内存。** 默认以 16 MiB 分片上传，每个文件最多四个分片并发；识别前通过 ffprobe 检查媒体。
- **断开连接，任务继续。** PostgreSQL 保存进度和供应商任务 ID；worker 通过租约与执行代次恢复工作。
- **五种入口，同一套任务。** Web、HTTP、CLI、异步 Python SDK 与 MCP 共用任务；网页上传后可将任务 ID 交给 Agent 接续处理。
- **可复用的结果。** 保留供应商原始结果与标准 JSON，导出 TXT、Markdown、SRT、VTT；不填造缺失时间戳。
- **明确的重试与计费行为。** 幂等键防止重复请求；供应商提交结果不确定时进入待处理状态，不自动重提。
- **无需云密钥即可开发。** 模拟供应商可验证完整流程，不调用云识别、不产生识别费用。

| 你想做什么 | 从这里开始 |
| --- | --- |
| 核对访谈或会议内容、查找正文、导出字幕 | [Web 工作台](#web-工作台) |
| 批量转写文件夹中的录音，恢复中断的上传 | [CLI](#cli) |
| 将转写接入 Python 应用 | [异步 Python SDK](#python-sdk) |
| 让 Agent 上传文件、查询进度、按时间范围读取 | [MCP](#mcp) · [本地文件实践案例](docs/examples/cloud-backend-local-files.zh-CN.md) |

## 体验工作台

先体验界面，再配置基础设施。需要 **Node.js 24 LTS**（最低 22.12）：

```bash
git clone https://github.com/yuehong136/voice-ingest.git
cd voice-ingest/web
npm ci
npm run dev
```

打开[本地工作台](http://127.0.0.1:5174)，点击 **Explore sample transcript**，再通过侧栏 **中文** 切换语言。可以搜索“时间戳”、切换导出格式。示例无需后端、API Key 或云账号，使用演示文本，不含原始音频。要处理自己的录音，请继续完成下方后端配置。

## 快速开始

在项目本地目录中操作：后端需要 **Docker Compose**，CLI / SDK 开发需要 **Python 3.12 和 [uv](https://docs.astral.sh/uv/)**，无需本地 GPU。

下列命令均在仓库根目录 `voice-ingest/` 执行。如果前端正在运行，保留该终端，另开一个终端进入仓库根目录。

### 1. 启动后端

```bash
cp .env.example .env
# 编辑 .env：更换服务 API Key、数据库密码和 S3 凭证。
docker compose --env-file .env -f deploy/compose.yaml up -d --build
curl --fail http://127.0.0.1:18080/v1/health/ready
```

命令启动独立的 API、worker、PostgreSQL 和 MinIO。默认本地端口为 **18080**（API）和 **19000**（S3），不占用 80/443。

默认供应商为 `mock`，输出带 `[MOCK]` 标记，不会识别录音正文。初始化完成后，健康检查应返回 HTTP 200。

### 2. 提交录音

```bash
uv sync --all-extras --frozen
export VOICE_URL=http://localhost:18080
export VOICE_API_KEY='与-dotenv-中一致的服务密钥'

uv run voice-ingest transcribe meeting.m4a --wait --format markdown
```

将 `meeting.m4a` 替换为音频路径。`--wait` 轮询任务，成功后输出 Markdown；不加则立即返回任务 ID。中断等待不会取消后端任务。

> **验证状态：** 第一阶段检查及本阶段阿里 STT/TTS 真实验收已于 2026-09-07 通过，包括 Worker 重启恢复、跨入口查询、浏览器播放下载及用户试听确认。证据和剩余质量/部署边界见[当前交接](docs/plans/phase-1-aliyun-stt-tts.md)；[历史录音验收](docs/acceptance.md)单独保留。独立验收不代表生产部署已验收。

第一阶段新增**语音合成**工作区：连接后端，选择模型、部署与音色，输入完整文本并明确提交，完成后播放和下载。
阿里首个配置为 `qwen-audio-3.0-tts-flash` / `longanhuan_v3.6` / MP3；mock 部署输出 WAV 静音测试音频。
CLI 使用 `voice-ingest syntheses --help`；SDK 使用 `synthesize()`、`get_synthesis()`、`synthesis_result()` 和 `synthesis_audio()`；
远程和本地 MCP 提供音色查询及合成生命周期工具，均复用相同业务实现。
已有数据库必须执行新增 `0002` 迁移，不重建数据库。后续接手请从[阶段文档](docs/plans/phase-1-aliyun-stt-tts.md)进入设计和完整调研。

## 供应商与模型

| 供应商 / 模型 | 当前能力 | 验证情况 |
| --- | --- | --- |
| Mock | 完整上传、任务和导出流程；生成模拟文本 | 离线测试及 PostgreSQL/MinIO 集成测试 |
| 阿里 `qwen-audio-3.0-asr-flash-filetrans` | 默认整文件异步 ASR | 历史 87 分钟录音；本阶段短样本重启恢复与导出验收通过 |
| 阿里 `qwen-audio-3.0-tts-flash` | 完整文本合成、`longanhuan_v3.6`、MP3 | 真实合成、浏览器播放下载与用户试听确认通过 |
| 阿里 `fun-asr` | 显式选择模型 | 已有适配器契约测试，尚未真实调用验收 |

当前 STT 模型校验上限为 **12 小时 / 2 GB**；开启说话人分离时，超过两小时会拒绝。语言提示、说话人分离和上下文支持随模型而异，可通过 `voice-ingest models` 或 `/v1/models` 查询。整文件提交，不自动压缩或做 VAD 切片。

启用阿里时，编辑 `.env`，并重新创建 API 和 worker：

```dotenv
VOICE_PROVIDER=aliyun
VOICE_ALIYUN_REGION=beijing
VOICE_ALIYUN_API_KEY=YOUR_REGIONAL_DASHSCOPE_KEY
VOICE_S3_PUBLIC_ENDPOINT=https://files.example.com
```

在默认 `signed_url` 模式下，文件地址必须实际连接到 S3 服务，并可被客户端和阿里访问；`localhost` 无法供云端识别读取。支持 HTTP 和 HTTPS，公网部署请使用 HTTPS。S3 内网访问地址与公网签名地址分别配置。

本地没有公网 S3 时，可设置 `VOICE_ALIYUN_SOURCE_MODE=temporary_upload` 并重启 API 和 worker，使用阿里官方临时文件服务完成真实转写测试。此模式仅用于本地评估，生产环境保持默认 `signed_url`。详见[本地浏览器配置](docs/deployment.md#real-asr-from-a-local-browser)。

**计费通道：** 当前适配常规 DashScope ASR，未接入 Token Plan / Coding Plan，也不会在计费通道间自动回退。`VOICE_API_KEY` 用于访问你的后端，`VOICE_ALIYUN_API_KEY` 用于后端调用阿里。详见[部署与凭证配置](docs/deployment.md)。

## Web 工作台

可选的 [React 前端](web/README.md) 将录音与转写结果放在同一个中英文工作区中。使用[上方体验命令](#体验工作台)启动，再通过服务密钥连接已运行的后端。

1. **上传并确认。** 上传文件后选择识别设置；上传完成会停在确认页，点击“开始转写”才会提交任务。
2. **跟踪与阅读。** 按状态筛选任务，核对说话人分段与原始时间戳，搜索已加载的正文。
3. **导出或交给 Agent。** 下载 Markdown、TXT、JSON、SRT 或 VTT；连接后可复制任务 ID，通过 MCP 或 SDK 继续处理。

<details>
<summary>查看移动端阅读界面</summary>

<br>
<img src="docs/assets/screenshots/reader-mobile-zh-CN.png" width="390" alt="390 像素移动端视口下的实际示例阅读界面，包含导出、句段时间轴与说话人分段">

同一个响应式工作台，滚动至正文阅读区域。截图使用合成示例文本，不含原始音频。

</details>

**前后端同时在本机运行时：** Vite 将 `/api` 转发至 `http://127.0.0.1:18080`，浏览器上传还需可访问的 S3 地址及存储 CORS 配置。部署时，可选 Web 容器使用 **18081** 端口。选择“稍后转写”可将待处理文件保留在当前页面，刷新后重新选择同一文件即可恢复上传记录。配置、分步确认流程、部署与测试见[前端指南](web/README.md)。

## CLI

```bash
uv run voice-ingest transcribe meeting.m4a
uv run voice-ingest batch ./recordings --recursive --resume
uv run voice-ingest --json jobs list
uv run voice-ingest jobs get JOB_ID
uv run voice-ingest jobs cancel JOB_ID
uv run voice-ingest export JOB_ID --format srt --output meeting.srt
```

在 `transcribe` 或 `batch` 后添加 `--model fun-asr` 可选择另一款阿里模型。

单文件默认续传，同一文件和参数会复用本地记录的任务；使用 `--no-resume` 主动重新提交。批量恢复需显式传入 `--resume`，一个文件失败不会终止后续文件处理。

`--json` 是全局参数，放在子命令前；进度写入 stderr。续传状态位于 `~/.local/state/voice-ingest/`，不在其中保存密钥。

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | 网络或服务错误 |
| `2` | 参数或本地文件错误 |
| `3` | 任务失败或批量部分失败 |
| `130` | 用户中断 |

## Python SDK

仅使用 SDK 时，可在已激活的环境中从项目目录执行 `uv pip install .`。默认依赖为 HTTPX 与 Pydantic，不引入数据库、HTTP 服务端或 MCP 依赖；可选安装组为 `cli`、`server`、`mcp`。

```python
import asyncio
import os

from voice_ingest import AsyncVoiceClient, TranscriptionOptions


async def main():
    async with AsyncVoiceClient("http://localhost:18080", os.environ["VOICE_API_KEY"]) as client:
        asset = await client.upload("meeting.m4a")
        job = await client.submit(
            asset.id,
            options=TranscriptionOptions(language_hints=["zh"], diarization=True),
            idempotency_key="meeting-001-v1",
        )
        job = await client.wait(job.id)
        if job.state == "succeeded":
            transcript = await client.result(job.id)
            print(transcript.text)
        else:
            print(job.model_dump_json())


asyncio.run(main())
```

重试同一次提交时复用幂等键，参数变化时换新键。`needs_attention` 表示供应商可能已经接受任务；取消后若 `remote_may_run=true`，远端仍可能执行并计费。

## MCP

让 Agent 接收录音，保留一个随时可继续查询的任务 ID。Agent 可以查询进度、按时间范围读取正文、请求导出；后端会在工具调用之间持续处理任务。

```mermaid
flowchart LR
    File[本地录音] --> Upload[upload_local_audio]
    Upload --> Asset[asset_id]
    Asset --> Submit[submit_transcription]
    Submit --> Job[job_id]
    Job --> Read[read_transcript]
    Job --> Export[export_transcript]
```

`upload_local_audio` 由本地桥接器提供。先通过 `get_transcription` 查询至任务成功，再读取或导出；仅使用远程客户端时，从已有文件或任务开始。

### 实践案例：云端后端，本地录音

> 转写电脑上的会议录音，准备 Markdown 和 SRT 导出，并保留任务 ID，方便我稍后继续查看。

使用轻量本地 MCP 桥接器将文件上传到云端后端，或先在网页上传，再让远程 Agent 接续已有任务。
长时间转写由后端持续执行。

**[查看完整案例 →](docs/examples/cloud-backend-local-files.zh-CN.md)**：包含客户端配置、上传流程图、
工具调用示例、鉴权下载，以及云端聊天附件的访问边界。

### 连接远程客户端

端点为 `http://localhost:18080/v1/mcp/`，请求头为 `Authorization: Bearer YOUR_VOICE_INGEST_API_KEY`。在客户端的 HTTP MCP 配置中填入地址与请求头。

| 操作 | 工具 |
| --- | --- |
| 查询模型 | `list_models` |
| 管理任务 | `submit_transcription`、`get_transcription`、`list_transcriptions`、`cancel_transcription`、`retry_transcription` |
| 读取与导出 | `read_transcript`、`export_transcript` |

提交后立即返回持久化业务任务 ID，无需客户端支持 MCP Tasks，也无需保持 MCP 连接。转写读取支持分页与时间范围，避免一次响应塞入整段长录音。

`submit_transcription` 只需提供 `asset_id`。MCP 自动按文件及规范化后的转写参数去重，
重连后或任务完成后重复调用也返回同一任务，无需在 Agent 提示词中管理幂等键。
可选的 `idempotency_key` 用于明确发起一次新的识别，同一次请求重试时复用；
失败任务使用 `retry_transcription`。HTTP/SDK 的幂等契约保持不变。

### 让 Agent 上传本地文件

执行 `uv sync --all-extras --frozen` 后，在支持 `mcpServers` 配置的客户端中添加本地 stdio 桥接器：

```json
{
  "mcpServers": {
    "voice-ingest": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/voice-ingest",
        "voice-ingest-mcp", "--url", "http://localhost:18080",
        "--allow-dir", "/absolute/path/to/recordings"
      ],
      "env": {"VOICE_API_KEY": "YOUR_VOICE_INGEST_API_KEY"}
    }
  }
}
```

替换两个绝对路径和服务密钥，确保客户端 PATH 中可找到 `uv`，并提前启动后端。其他客户端可能使用不同配置格式。

桥接器额外提供 `upload_local_audio`，解析真实路径后检查允许目录，包括符号链接是否越界。文件上传到后端后返回 asset ID，再由转写工具提交任务；远程 MCP 不接受用户电脑上的本地路径。

## HTTP API

业务路由统一使用 `/v1` 与 Bearer 鉴权；创建转写必须提供 `Idempotency-Key`，返回 **202 Accepted**。

| 资源 | 用途 |
| --- | --- |
| `/v1/uploads` | 创建、查询、分片签名、完成或终止上传 |
| `/v1/assets/{asset_id}` | 查询或删除原始音频 |
| `/v1/models` | 查询模型能力 |
| `/v1/transcriptions` | 提交任务、游标分页列表 |
| `/v1/transcriptions/{job_id}` | 查询任务或删除其结果 |
| `…/{job_id}/cancel`、`…/{job_id}/retry` | 显式取消或重试 |
| `…/{job_id}/result`、`…/{job_id}/exports/{format}` | 读取标准结果与导出文件 |

具体方法与请求体以 OpenAPI 为准：

```bash
curl -H "Authorization: Bearer $VOICE_API_KEY" \
  "$VOICE_URL/v1/openapi.json" -o openapi.json
```

`/v1/docs` 同样需要鉴权。`/v1/health/live` 和 `/v1/health/ready` 是公开的进程与就绪检查；`/v1/metrics` 需要服务密钥。

## 工作方式

```mermaid
flowchart LR
    CLI[CLI / Python SDK] --> API[HTTP API]
    Agent[Agent] --> MCP[Remote MCP]
    Agent --> Bridge[Local MCP bridge]
    Bridge --> API
    MCP --> Service[Transcription service]
    API --> Service
    CLI -->|Presigned upload| S3[(Private S3)]
    Service --> PG[(PostgreSQL jobs)]
    PG --> Worker[Worker]
    Worker --> Provider[Aliyun / Mock]
    Worker --> S3
    Provider -->|Signed audio URL| S3
```

上传得到稳定的 `asset_id`，转写得到独立的 `job_id`。PostgreSQL 保存任务状态，私有 S3 保存音频、原始结果与导出。HTTP 和远程 MCP 共用业务用例；CLI 与本地 MCP 桥接器复用 SDK。

Worker 通过 `SKIP LOCKED` 领取到期任务，在事务外执行网络操作，并根据租约所有者和执行代次校验写入。重启后继续查询已保存的供应商任务；提交响应丢失时进入 `needs_attention`。只有文件级状态检查、结果下载和规范化均完成后，任务才标记成功。

## 开发

```bash
uv sync --all-extras --frozen
make check
uv build
```

`make check` 执行 Ruff、格式检查、Pyright 和离线测试。本机直接运行后端还需要 ffprobe、PostgreSQL 与 S3，启动 API 和 worker 前需执行迁移，详见[部署指南](docs/deployment.md)。

配置独立测试资源后，执行 `make integration` 验证真实 PostgreSQL/MinIO。这些测试使用模拟 ASR；真实云识别是独立的、可能产生费用的验收步骤。

开发前阅读 [AGENTS.md](AGENTS.md)。代码按 `transcription`、`media`、`providers`、`jobs`、`exports` 等能力组织，由薄接口层接入，共用运行设施。修改时保持模块边界，为契约与恢复语义的变化添加行为测试，并同步维护中英文 README。

## 范围与文档

当前版本聚焦共享可信工作区中的文件转写与完整文本合成。实时会话、声音克隆、自动长文本分段、多租户、其他厂商和知识库自动入库属于后续范围。

| 文档 | 内容 |
| --- | --- |
| [Web 工作台](web/README.md) | 浏览器配置、上传确认、存储 CORS 与前端检查（英文） |
| [云端后端 + 本地录音](docs/examples/cloud-backend-local-files.zh-CN.md) | 包含客户端配置与导出的完整 MCP 实践 |
| [部署指南](docs/deployment.md) | 配置、私有存储、HTTP/HTTPS、凭证与运维（英文） |
| [架构说明](docs/architecture.md) | 模块边界、持久化、恢复与权衡（英文） |
| [架构决策](docs/decisions/0001-durable-capabilities.md) | 持久化任务与按能力组织代码（英文） |
| [验收记录](docs/acceptance.md) | 已验证行为及剩余验收事项 |
| [Agent 开发约定](AGENTS.md) | 开发者与 coding agent 的仓库规则（英文） |

## 开源协议

采用 [MIT 协议](LICENSE)，允许使用、修改、分发和商业使用，须保留版权与协议声明。
第三方依赖和云服务仍遵循各自的协议与服务条款。
