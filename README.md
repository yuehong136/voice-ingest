# Voice Ingest

**Long-form audio transcription for developers and AI agents.**

Upload once. Submit a durable job. Retrieve structured transcripts from your terminal, Python code, or MCP client.

**English** · [简体中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Quickstart](#quickstart) · [CLI](#cli) · [Python SDK](#python-sdk) · [MCP](#mcp) · [Deployment](docs/deployment.md) · [Architecture](docs/architecture.md)

Voice Ingest handles the work around cloud ASR: resumable uploads, asynchronous jobs, restart recovery, and consistent exports. It is built for personal use and trusted teams sharing an API-key-protected workspace.

## Why Voice Ingest?

- **Long recordings, bounded memory.** Upload in 16 MiB parts with four concurrent parts per file; validate media with ffprobe before recognition.
- **Jobs survive client disconnects.** PostgreSQL persists progress and provider task IDs. Workers use leases and execution generations to recover work safely.
- **One workflow, four interfaces.** HTTP, CLI, an async Python SDK, and FastMCP 4.0.2 with MCP Python SDK v2 address the same jobs.
- **Results you can reuse.** Keep raw provider output and normalized JSON; export TXT, Markdown, SRT, and VTT. Missing timestamps stay missing.
- **Explicit retry and billing behavior.** Idempotency keys prevent duplicate requests. Uncertain provider submissions require attention instead of automatic resubmission.
- **Develop without cloud credentials.** The mock provider exercises the workflow without recognition charges or provider network calls.

## Quickstart

From a local checkout, use **Docker Compose** for the backend and **Python 3.12 + [uv](https://docs.astral.sh/uv/)** for CLI/SDK development. No local GPU is required.

### 1. Start the backend

```bash
cp .env.example .env
# Edit .env: replace the API key, database password, and S3 credentials.
docker compose --env-file .env -f deploy/compose.yaml up -d --build
curl --fail http://127.0.0.1:18080/health/ready
```

This starts a separate API, worker, PostgreSQL, and MinIO stack. The default local ports are **18080** (API) and **19000** (S3); 80/443 are unused.

The default provider is `mock`. Its output is labeled `[MOCK]` and does not transcribe the contents of your recording. The health request should return HTTP 200 once initialization completes.

### 2. Submit a recording

```bash
uv sync --all-extras --frozen
export VOICE_URL=http://localhost:18080
export VOICE_API_KEY='the-service-key-from-your-dotenv'

uv run voice-ingest transcribe meeting.m4a --wait --format markdown
```

Replace `meeting.m4a` with your audio file. `--wait` polls the job and prints Markdown when it succeeds. Omit it to return the job ID immediately; interrupting a wait does not cancel server-side work.

> **Validation status:** Local tests and a real Aliyun recording test have passed. A complete Compose startup has not yet been validated; the last image build was interrupted by dependency download timeouts. See the [acceptance record](docs/acceptance.md).

## Providers

| Provider / model | Available behavior | Verification |
| --- | --- | --- |
| Mock | Complete upload/job/export workflow; synthetic text | Offline and PostgreSQL/MinIO integration tests |
| Aliyun `qwen-audio-3.0-asr-flash-filetrans` | Default whole-file asynchronous ASR | Real 87-minute recording completed |
| Aliyun `fun-asr` | Explicit model selection | Adapter contract tests; no live acceptance yet |

The current model checks allow files up to **12 hours / 2 GB**. Speaker diarization is rejected above two hours. Language hints, diarization, and context support depend on the model; inspect `voice-ingest models` or `/v1/models` for capabilities. Files are sent whole, without automatic compression or VAD splitting.

To enable Aliyun, edit `.env` and recreate the API and worker:

```dotenv
VOICE_PROVIDER=aliyun
VOICE_ALIYUN_REGION=beijing
VOICE_ALIYUN_API_KEY=YOUR_REGIONAL_DASHSCOPE_KEY
VOICE_S3_PUBLIC_ENDPOINT=https://files.example.com
```

In the default `signed_url` mode, the file endpoint must actually route to your S3 service and be reachable by clients and Aliyun. `localhost` cannot serve cloud recognition. HTTP and HTTPS origins are supported; use HTTPS for public deployments. Internal storage access and public signing endpoints are configured separately.

For local real-ASR evaluation without public S3, set `VOICE_ALIYUN_SOURCE_MODE=temporary_upload` and restart the API and worker. The worker uses Aliyun’s official temporary file service; this mode is for local evaluation only. Production keeps the default `signed_url` mode. See [local browser setup](docs/deployment.md#real-asr-from-a-local-browser).

**Billing:** This adapter uses regular DashScope ASR. Token Plan / Coding Plan is not integrated, and there is no automatic fallback between billing channels. `VOICE_API_KEY` protects your backend; `VOICE_ALIYUN_API_KEY` authenticates the backend to Aliyun. See [deployment and credential configuration](docs/deployment.md).

## Web workspace

The optional [React frontend](web/README.md) provides a transcription workspace with separate upload and recognition steps, status filters, transcript search and five export formats. English is the default; Chinese is available in the sidebar.

```bash
cd web
npm ci
npm run dev
```

Open http://127.0.0.1:5174 and connect your workspace with its service key, or explicitly explore a sample transcript without credentials. Uploading stops at a review step; **Start transcription** submits the job. See the [web guide](web/README.md) for a customer walkthrough, storage CORS, deployment and tests.

## CLI

```bash
uv run voice-ingest transcribe meeting.m4a
uv run voice-ingest batch ./recordings --recursive --resume
uv run voice-ingest --json jobs list
uv run voice-ingest jobs get JOB_ID
uv run voice-ingest jobs cancel JOB_ID
uv run voice-ingest export JOB_ID --format srt --output meeting.srt
```

Use `--model fun-asr` on `transcribe` or `batch` to select the other Aliyun model.

Single-file transcription resumes by default and reuses the local job record for the same file and options. Use `--no-resume` for a fresh submission. Batch resume is explicit; one file's failure does not stop the remaining files.

`--json` is a global option and goes before the subcommand. Progress goes to stderr. Resume state lives under `~/.local/state/voice-ingest/`; credentials are not stored there.

| Exit code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Network or service error |
| `2` | Invalid arguments or local file |
| `3` | Job failure or partial batch failure |
| `130` | User interruption |

## Python SDK

For SDK-only use, install from the checkout with `uv pip install .` in an activated environment. The default package depends on HTTPX and Pydantic, without database, HTTP server, or MCP dependencies. Optional extras are `cli`, `server`, and `mcp`.

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

Reuse an idempotency key when retrying the same submission; use a new key for changed parameters. A job in `needs_attention` may already have been accepted by the provider. A cancellation with `remote_may_run=true` means the provider may still execute and charge for recognition.

## MCP

### Recipe: cloud backend, local recording

> Transcribe the meeting on my laptop. Prepare Markdown and SRT exports, and keep the job ID so I can return later.

Run a lightweight local MCP bridge to upload files to your cloud backend, or upload in the web workspace
and let a remote agent continue with the existing job. The backend owns the long-running work.

**[Follow the recipe →](docs/examples/cloud-backend-local-files.md)** — client configuration, upload flow,
example tool calls, and authenticated downloads. Includes the boundaries for cloud-hosted chat attachments.

### Connect a remote client

Use `http://localhost:18080/mcp/` with `Authorization: Bearer YOUR_VOICE_INGEST_API_KEY`. Configure the URL and header using your client's HTTP MCP settings.

| Task | Tools |
| --- | --- |
| Discover models | `list_models` |
| Manage jobs | `submit_transcription`, `get_transcription`, `list_transcriptions`, `cancel_transcription`, `retry_transcription` |
| Read and export | `read_transcript`, `export_transcript` |

Submissions return durable business job IDs immediately. MCP Tasks support and a persistent MCP connection are not required. Transcript reads support pagination and time ranges to keep long recordings out of a single tool response.

### Upload local files from an agent

After `uv sync --all-extras --frozen`, configure a local stdio bridge in a client that supports `mcpServers` configuration:

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

Replace both absolute paths and the service key; `uv` must be on the client's PATH. The backend must already be running. Other clients may use a different configuration schema.

The bridge adds `upload_local_audio` and checks resolved paths against explicitly allowed directories, including symlink boundaries. It uploads the file to the backend and returns an asset ID for a subsequent transcription submission. Remote MCP does not accept paths on your computer.

## HTTP API

All business routes use `/v1` and Bearer authentication. Creation of a transcription requires `Idempotency-Key` and returns **202 Accepted**.

| Resource | Purpose |
| --- | --- |
| `/v1/uploads` | Create, inspect, sign parts, complete, or abort an upload |
| `/v1/assets/{asset_id}` | Inspect or delete source audio |
| `/v1/models` | Query model capabilities |
| `/v1/transcriptions` | Submit jobs and list them with cursor pagination |
| `/v1/transcriptions/{job_id}` | Inspect a job or delete its results |
| `…/{job_id}/cancel`, `…/{job_id}/retry` | Cancel or retry explicitly |
| `…/{job_id}/result`, `…/{job_id}/exports/{format}` | Read normalized results and exports |

Download the OpenAPI schema for exact methods and request bodies:

```bash
curl -H "Authorization: Bearer $VOICE_API_KEY" \
  "$VOICE_URL/openapi.json" -o openapi.json
```

`/docs` also requires authentication. `/health/live` and `/health/ready` are public process/readiness checks; `/metrics` requires the service key.

## How it works

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

Uploading creates a stable `asset_id`; transcription creates a separate `job_id`. PostgreSQL owns job state, while private S3 stores audio, raw results, and exports. HTTP and remote MCP share business use cases; CLI and the local MCP bridge reuse the SDK.

Workers claim due jobs with `SKIP LOCKED`, run network operations outside transactions, and fence writes by lease ownership and generation. After a restart, a saved provider task ID is polled again. A lost submission response becomes `needs_attention`. Success requires checking file-level status, downloading the result, and normalizing it.

## Development

```bash
uv sync --all-extras --frozen
make check
uv build
```

`make check` runs Ruff, format checks, Pyright, and offline tests. Native backend development also requires ffprobe, PostgreSQL, and S3; run migrations before starting the API and worker. See the [deployment guide](docs/deployment.md).

For real PostgreSQL/MinIO tests, configure dedicated test resources and run `make integration`. These tests use the mock ASR provider. Cloud recognition is a separate, explicitly billable acceptance step.

Read [AGENTS.md](AGENTS.md) before coding. Modules are organized by capability (`transcription`, `media`, `providers`, `jobs`, `exports`) with thin interfaces and shared runtime wiring. Keep changes within these boundaries, add behavior tests for changed contracts or recovery semantics, and keep both READMEs in sync.

## Scope and documentation

The current release focuses on offline ASR for a shared, trusted workspace. Realtime recognition, TTS, multi-tenancy, and automatic knowledge-base ingestion are outside the current implementation. TTS is a future direction, without a committed release date.

| Document | Contents |
| --- | --- |
| [Deployment](docs/deployment.md) | Configuration, private storage, HTTP/HTTPS, credentials, operations |
| [Architecture](docs/architecture.md) | Module boundaries, persistence, recovery, and tradeoffs |
| [Architecture decision](docs/decisions/0001-durable-capabilities.md) | Durable jobs and capability-oriented organization |
| [Acceptance record](docs/acceptance.md) | Tested behavior and remaining validation work (Chinese) |
| [Agent instructions](AGENTS.md) | Repository rules for contributors and coding agents |

## License

[MIT](LICENSE). You may use, modify, distribute, and use this project commercially,
provided you retain the copyright and license notice. Third-party dependencies and
cloud services remain subject to their own licenses and terms.
