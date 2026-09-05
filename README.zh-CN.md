# Voice Ingest

**面向开发者与 AI Agent 的长录音转写服务。**

上传一次，创建持久化任务，通过终端、Python 或 MCP 客户端获取结构化转写结果。

[English](README.md) · **简体中文**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[快速开始](#快速开始) · [CLI](#cli) · [Python SDK](#python-sdk) · [MCP](#mcp) · [部署指南](docs/deployment.md) · [架构说明](docs/architecture.md)

Voice Ingest 处理云端 ASR 周边的工程工作：断点续传、异步任务、重启恢复和统一导出。适用于个人或内部可信团队，通过 API Key 访问共享工作区。

## 为什么选择 Voice Ingest？

- **长录音，有界内存。** 默认以 16 MiB 分片上传，每个文件最多四个分片并发；识别前通过 ffprobe 检查媒体。
- **断开连接，任务继续。** PostgreSQL 保存进度和供应商任务 ID；worker 通过租约与执行代次恢复工作。
- **四种入口，同一套任务。** HTTP、CLI、异步 Python SDK，以及基于 FastMCP 4.0.2 / MCP Python SDK v2 的 MCP 服务。
- **可复用的结果。** 保留供应商原始结果与标准 JSON，导出 TXT、Markdown、SRT、VTT；不填造缺失时间戳。
- **明确的重试与计费行为。** 幂等键防止重复请求；供应商提交结果不确定时进入待处理状态，不自动重提。
- **无需云密钥即可开发。** 模拟供应商可验证完整流程，不调用云识别、不产生识别费用。

## 快速开始

在项目本地目录中操作：后端需要 **Docker Compose**，CLI / SDK 开发需要 **Python 3.12 和 [uv](https://docs.astral.sh/uv/)**，无需本地 GPU。

### 1. 启动后端

```bash
cp .env.example .env
# 编辑 .env：更换服务 API Key、数据库密码和 S3 凭证。
docker compose --env-file .env -f deploy/compose.yaml up -d --build
curl --fail http://127.0.0.1:18080/health/ready
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

> **验证状态：** 本地测试及一次真实阿里录音转写已通过。完整 Compose 启动尚未验收，上次镜像构建因依赖下载超时中断。详见[验收记录](docs/acceptance.md)。

## 供应商与模型

| 供应商 / 模型 | 当前能力 | 验证情况 |
| --- | --- | --- |
| Mock | 完整上传、任务和导出流程；生成模拟文本 | 离线测试及 PostgreSQL/MinIO 集成测试 |
| 阿里 `qwen-audio-3.0-asr-flash-filetrans` | 默认整文件异步 ASR | 已完成 87 分钟真实录音转写 |
| 阿里 `fun-asr` | 显式选择模型 | 已有适配器契约测试，尚未真实调用验收 |

当前模型校验上限为 **12 小时 / 2 GB**；开启说话人分离时，超过两小时会拒绝。语言提示、说话人分离和上下文支持随模型而异，可通过 `voice-ingest models` 或 `/v1/models` 查询。整文件提交，不自动压缩或做 VAD 切片。

启用阿里时，编辑 `.env`，并重新创建 API 和 worker：

```dotenv
VOICE_PROVIDER=aliyun
VOICE_ALIYUN_REGION=beijing
VOICE_ALIYUN_API_KEY=YOUR_REGIONAL_DASHSCOPE_KEY
VOICE_S3_PUBLIC_ENDPOINT=https://files.example.com
```

文件地址必须实际连接到 S3 服务，并可被客户端和阿里访问；`localhost` 无法供云端识别读取。支持 HTTP 和 HTTPS，公网部署请使用 HTTPS。S3 内网访问地址与公网签名地址分别配置。

**计费通道：** 当前适配常规 DashScope ASR，未接入 Token Plan / Coding Plan，也不会在计费通道间自动回退。`VOICE_API_KEY` 用于访问你的后端，`VOICE_ALIYUN_API_KEY` 用于后端调用阿里。详见[部署与凭证配置](docs/deployment.md)。

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

### 连接远程客户端

端点为 `http://localhost:18080/mcp/`，请求头为 `Authorization: Bearer YOUR_VOICE_INGEST_API_KEY`。在客户端的 HTTP MCP 配置中填入地址与请求头。

| 操作 | 工具 |
| --- | --- |
| 查询模型 | `list_models` |
| 管理任务 | `submit_transcription`、`get_transcription`、`list_transcriptions`、`cancel_transcription`、`retry_transcription` |
| 读取与导出 | `read_transcript`、`export_transcript` |

提交后立即返回持久化业务任务 ID，无需客户端支持 MCP Tasks，也无需保持 MCP 连接。转写读取支持分页与时间范围，避免一次响应塞入整段长录音。

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
  "$VOICE_URL/openapi.json" -o openapi.json
```

`/docs` 同样需要鉴权。`/health/live` 和 `/health/ready` 是公开的进程与就绪检查；`/metrics` 需要服务密钥。

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

当前版本聚焦共享可信工作区中的离线 ASR，尚未实现实时识别、TTS、前端、多租户或知识库自动入库。TTS 是后续方向，暂无承诺的发布日期。

| 文档 | 内容 |
| --- | --- |
| [部署指南](docs/deployment.md) | 配置、私有存储、HTTP/HTTPS、凭证与运维（英文） |
| [架构说明](docs/architecture.md) | 模块边界、持久化、恢复与权衡（英文） |
| [架构决策](docs/decisions/0001-durable-capabilities.md) | 持久化任务与按能力组织代码（英文） |
| [验收记录](docs/acceptance.md) | 已验证行为及剩余验收事项 |
| [Agent 开发约定](AGENTS.md) | 开发者与 coding agent 的仓库规则（英文） |

## 开源协议

采用 [MIT 协议](LICENSE)，允许使用、修改、分发和商业使用，须保留版权与协议声明。
第三方依赖和云服务仍遵循各自的协议与服务条款。
