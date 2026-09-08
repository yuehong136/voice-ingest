# 远程部署与开发对接

本页是自托管实例的通用交接模板，不包含任何真实主机名、IP、API Key、厂商密钥、数据库密码、签名 URL、
录音或正文。部署负责人应在 Git 忽略的受控文档中记录实例值。通用部署、备份恢复和失败边界分别以
[部署指南](../deployment.md)与[部署演练](deployment-rehearsal.md)为准。

## 实例参数

先从部署负责人处取得实例参数，并在本机临时设置：

```bash
export VOICE_URL=https://voice.example.com
export VOICE_WEB_URL=https://voice.example.com
export VOICE_MCP_URL=https://voice.example.com/v1/mcp/
export VOICE_API_KEY='<从受控渠道取得>'
```

`VOICE_API_KEY` 是本服务的工作区凭据，不是阿里或其他厂商的 API Key。厂商密钥只保存在后端受控配置中，
不得下发到浏览器、CLI、SDK、MCP 客户端或对接文档。无 TLS 的 IP 入口只适合受限试运行；生产访问必须使用
HTTPS，并在防火墙或云安全组中限制管理端口来源。

## HTTP 调用

先检查就绪和模型目录：

```bash
curl --fail "$VOICE_URL/v1/health/ready"
curl --fail -H "Authorization: Bearer $VOICE_API_KEY" \
  "$VOICE_URL/v1/models"
```

创建 TTS 任务。网络重试必须复用同一个 `Idempotency-Key`：

```bash
curl --fail-with-body -X POST "$VOICE_URL/v1/syntheses" \
  -H "Authorization: Bearer $VOICE_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: dev-tts-001' \
  --data '{
    "text": "这是一段开发联调语音。",
    "options": {
      "model": "qwen-audio-3.0-tts-flash",
      "voice": "longanhuan_v3.6",
      "format": "mp3",
      "sample_rate": 22050
    }
  }'
```

响应中的 `id` 是持久化任务 ID。轮询与下载：

```bash
curl --fail -H "Authorization: Bearer $VOICE_API_KEY" \
  "$VOICE_URL/v1/syntheses/JOB_ID"
curl --fail -H "Authorization: Bearer $VOICE_API_KEY" \
  "$VOICE_URL/v1/syntheses/JOB_ID/audio" -o speech.mp3
```

转写上传包含创建上传、分片签名、上传、完成和提交任务多个步骤，建议直接使用下面的 CLI 或 Python SDK。
需要自己实现 HTTP 客户端时，以鉴权后的 `/v1/openapi.json` 为唯一方法与请求体依据。创建转写任务必须提供
`Idempotency-Key`；查询结果和导出分别使用：

```text
GET /v1/transcriptions/{job_id}
GET /v1/transcriptions/{job_id}/result
GET /v1/transcriptions/{job_id}/segments?limit=50&start_ms=0&end_ms=60000
GET /v1/transcriptions/{job_id}/exports/markdown
```

## CLI 调用

在本地仓库安装锁定依赖，然后指向远程地址：

```bash
uv sync --all-extras --frozen
uv run voice-ingest models
uv run voice-ingest transcribe ./meeting.m4a --wait --format markdown
uv run voice-ingest --json jobs list
uv run voice-ingest jobs get JOB_ID
uv run voice-ingest export JOB_ID --format srt --output meeting.srt
```

TTS 示例：

```bash
printf '这是一段开发联调语音。\n' > /tmp/voice-ingest-tts.txt
uv run voice-ingest syntheses voices
uv run voice-ingest syntheses submit /tmp/voice-ingest-tts.txt \
  --idempotency-key dev-tts-001
uv run voice-ingest syntheses get JOB_ID
uv run voice-ingest syntheses download JOB_ID speech.mp3
```

转写默认恢复同一文件与参数的本地上传记录。批量任务需显式添加 `--resume`。`needs_attention` 表示厂商可能
已接受任务，不能自动重提；`remote_may_run=true` 表示取消后远端仍可能继续执行和计费。

## Python SDK 调用

SDK-only 安装不引入 FastAPI、数据库或 MCP 依赖：

```bash
uv pip install .
```

```python
import asyncio
import os

from voice_ingest import AsyncVoiceClient, TranscriptionOptions


async def main() -> None:
    async with AsyncVoiceClient(os.environ["VOICE_URL"], os.environ["VOICE_API_KEY"]) as client:
        asset = await client.upload("meeting.m4a")
        job = await client.submit(
            asset.id,
            options=TranscriptionOptions(language_hints=["zh"], diarization=True),
            idempotency_key="meeting-v1",
        )
        final = await client.wait(job.id)
        if final.state == "succeeded":
            transcript = await client.result(final.id)
            print(transcript.text)
        else:
            print(final.model_dump_json())


asyncio.run(main())
```

## MCP 调用

支持 Streamable HTTP 的 MCP 客户端配置：

```json
{
  "url": "https://voice.example.com/v1/mcp/",
  "headers": {
    "Authorization": "Bearer YOUR_VOICE_INGEST_API_KEY"
  }
}
```

远程 MCP 可查询模型/音色，创建和管理 STT/TTS 任务，分页读取转写，返回鉴权导出路径。录音仍在开发者
电脑时，远程 MCP 看不到本地路径；用本地 stdio 桥接器增加 `upload_local_audio`：

```json
{
  "mcpServers": {
    "voice-ingest": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/voice-ingest",
        "voice-ingest-mcp", "--url", "https://voice.example.com",
        "--allow-dir", "/absolute/path/to/recordings"
      ],
      "env": {
        "VOICE_API_KEY": "YOUR_VOICE_INGEST_API_KEY"
      }
    }
  }
}
```

常用工具：`list_models`、`list_voices`、`submit_transcription`、`get_transcription`、
`read_transcript`、`export_transcript`、`submit_synthesis`、`get_synthesis`、
`get_synthesis_result`。任务提交后与 MCP 会话解耦，断开客户端不会取消后端任务。

## 本地开发后的发布

推荐的发布单位是已经通过检查并推送的精确 Git commit，不把未提交工作区或整目录直接覆盖到服务器：

```bash
make check
npm --prefix web run check
npm --prefix web run build
git push origin HEAD
git rev-parse HEAD
```

单机源码构建部署可以在服务器执行仓库内的通用发布脚本：

```bash
ssh "$DEPLOY_HOST" \
  "/opt/voice-ingest/current/scripts/deploy_server_release.sh <40位提交SHA>"
```

默认路径均可通过 `VOICE_APP_REPO`、`VOICE_CURRENT_LINK`、`VOICE_RELEASE_ROOT`、
`VOICE_BACKUP_ROOT`、`VOICE_ENV_FILE` 和 `VOICE_COMPOSE_PROJECT` 覆盖。脚本会拉取精确提交、在独立 worktree
中增量构建、用当前版本工具做 PostgreSQL 与 S3 成对停写快照、停止入口/Worker、执行迁移与存储初始化、
启动新版本并检查 readiness。只有健康检查通过才更新 `current` 链接和 `deployed-commit`。旧发布 worktree
和备份不会自动删除。

构建默认使用官方上游；受限网络可在部署 env 中设置 `VOICE_APT_MIRROR`、
`VOICE_PYPI_INDEX_URL` 和 `VOICE_NPM_REGISTRY`。锁文件仍保持 frozen。镜像站属于供应链的一部分，不能使用
不受信任的临时镜像。

如果发布失败，不要自动回滚数据库：先查看日志和备份位置，判断迁移是否已执行。容器回退不能撤销 Alembic
迁移，也不能撤销已经提交给厂商的任务与费用。涉及迁移、任务状态或恢复语义的版本必须按
[部署演练](deployment-rehearsal.md)执行恢复审查。

发布频率提高后，可由 CI 构建按 commit SHA 标记的不可变镜像并推送到受控 Registry，服务器只拉取镜像和
运行迁移。启用前应确定 Registry、镜像签名、部署身份、分支保护和失败回滚策略。

## 运维核对模板

```bash
cd /opt/voice-ingest/current
docker compose --project-name "$VOICE_COMPOSE_PROJECT" \
  --env-file "$VOICE_ENV_FILE" \
  -f deploy/compose.yaml -f deploy/compose.web.yaml ps

docker compose --project-name "$VOICE_COMPOSE_PROJECT" \
  --env-file "$VOICE_ENV_FILE" \
  -f deploy/compose.yaml -f deploy/compose.web.yaml logs --tail 100 api worker

curl --fail http://127.0.0.1:18080/v1/health/ready
```

停止时不要加 `-v`；`down -v` 会删除本项目数据库和对象卷。日志中不得输出厂商密钥、工作区 Key、签名 URL、
请求正文或转写内容。
