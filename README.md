# Voice Ingest

**Turn long recordings into transcripts you can read, search, and build with.**

A self-hosted transcription workspace for people, developers, and AI agents. Upload in your browser, automate from your terminal, or let an MCP client continue the same durable job.

**English** · [简体中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Checks](https://github.com/yuehong136/voice-ingest/actions/workflows/check.yml/badge.svg)](https://github.com/yuehong136/voice-ingest/actions/workflows/check.yml)

[Try the UI](#try-the-workspace) · [Quickstart](#quickstart) · [Web workspace](#web-workspace) · [MCP](#mcp) · [Python SDK](#python-sdk) · [CLI](#cli) · [Deployment](docs/deployment.md)

![Voice Ingest sample workspace showing recordings, speaker-labeled transcript segments, timestamps, search, and export controls](docs/assets/screenshots/workspace-en.png)

*Actual running Web UI with built-in synthetic sample content. No private recordings or real ASR results are shown. [Reproduce these screenshots](docs/assets/screenshots/README.md).*

Voice Ingest handles the work around cloud ASR: resumable uploads, asynchronous jobs, restart recovery, and consistent exports. It is built for personal use and trusted teams sharing an API-key-protected workspace.

## Why Voice Ingest?

- **Long recordings, bounded memory.** Upload in 16 MiB parts with four concurrent parts per file; validate media with ffprobe before recognition.
- **Jobs survive client disconnects.** PostgreSQL persists progress and provider task IDs. Workers use leases and execution generations to recover work safely.
- **One workflow, five interfaces.** Web, HTTP, CLI, an async Python SDK, and MCP address the same jobs. Upload in the browser and pass the job ID to an agent.
- **Results you can reuse.** Keep raw provider output and normalized JSON; export TXT, Markdown, SRT, and VTT. Missing timestamps stay missing.
- **Explicit retry and billing behavior.** Idempotency keys prevent duplicate requests. Uncertain provider submissions require attention instead of automatic resubmission.
- **Develop without cloud credentials.** The mock provider exercises the workflow without recognition charges or provider network calls.

| What you want to do | Start here |
| --- | --- |
| Review an interview or meeting, search its text, export subtitles | [Web workspace](#web-workspace) |
| Transcribe a folder and resume interrupted uploads | [CLI](#cli) |
| Add transcription to a Python application | [Async Python SDK](#python-sdk) |
| Let an agent upload, check progress, and read selected time ranges | [MCP](#mcp) · [Local-file recipe](docs/examples/cloud-backend-local-files.md) |

## Try the workspace

For phase-1 speech synthesis, connect the backend, open **Speech synthesis**, select a configured
model/deployment and voice, then explicitly submit text. Completed files can be played and downloaded.
Aliyun's first preset is `qwen-audio-3.0-tts-flash` / `longanhuan_v3.6` / MP3; mock deployments expose
`mock-tts` / `mock-voice` / WAV. Mock audio is synthetic silence, not a quality demonstration.
Use `voice-ingest syntheses --help` for CLI operations, or `AsyncVoiceClient.synthesize()` followed by
`get_synthesis()`, `synthesis_result()` and `synthesis_audio()` in Python. Remote/local MCP include
`submit_synthesis`, `list_voices` and synthesis lifecycle/result tools. All application endpoints,
including remote MCP, health, metrics and OpenAPI, are under `/v1`.

Existing installations must run incremental migration `0002`; do not recreate the database.
[Development design and acceptance](docs/plans/phase-1-aliyun-stt-tts.md) describe setup, tests,
deployment selection, recovery and the separate paid acceptance gate.

Explore the interface before setting up infrastructure. You need **Node.js 24 LTS** (minimum 22.12):

```bash
git clone https://github.com/yuehong136/voice-ingest.git
cd voice-ingest/web
npm ci
npm run dev
```

Open [the local workspace](http://127.0.0.1:5174) and click **Explore sample transcript**. Search for `timestamps`, switch export formats, or use **中文** in the sidebar. The sample needs no backend, API key, or cloud account; it uses illustrative text without source audio. To transcribe your own recordings, continue with the backend quickstart below.

## Quickstart

From a local checkout, use **Docker Compose** for the backend and **Python 3.12 + [uv](https://docs.astral.sh/uv/)** for CLI/SDK development. No local GPU is required.

Run these commands from the repository root (`voice-ingest/`). If the frontend is running in another terminal, leave it running and open a new terminal at the root.

### 1. Start the backend

```bash
cp .env.example .env
# Edit .env: replace the API key, database password, and S3 credentials.
docker compose --env-file .env -f deploy/compose.yaml up -d --build
curl --fail http://127.0.0.1:18080/v1/health/ready
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

> **Validation status:** Phase-1 checks and real Aliyun STT/TTS acceptance passed on 2026-09-07, including worker restart recovery, cross-interface access, browser playback/download and user listening confirmation. See the [current handoff](docs/plans/phase-1-aliyun-stt-tts.md) for evidence and remaining quality/deployment limits. The [historical acceptance record](docs/acceptance.md) is preserved separately. Isolated acceptance does not establish production deployment readiness.

## Providers

| Provider / model | Available behavior | Verification |
| --- | --- | --- |
| Mock | Complete upload/job/export workflow; synthetic text | Offline and PostgreSQL/MinIO integration tests |
| Aliyun `qwen-audio-3.0-asr-flash-filetrans` | Default whole-file asynchronous ASR | Historical 87-minute recording; phase-1 short-sample restart/export acceptance passed |
| Aliyun `qwen-audio-3.0-tts-flash` | Complete-text synthesis, `longanhuan_v3.6`, MP3 | Real synthesis, browser playback/download and user listening confirmation passed |
| Aliyun `fun-asr` | Explicit model selection | Adapter contract tests; no live acceptance yet |

The current STT model checks allow files up to **12 hours / 2 GB**. Speaker diarization is rejected above two hours. Language hints, diarization, and context support depend on the model; inspect `voice-ingest models` or `/v1/models` for capabilities. Files are sent whole, without automatic compression or VAD splitting.

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

The optional [React frontend](web/README.md) brings recordings and transcripts into one English/Chinese workspace. Start it with the [preview commands above](#try-the-workspace), then connect to your running backend with its service key.

1. **Upload and review.** Upload a file, then choose recognition settings. Uploading stops at a review step; **Start transcription** submits the job.
2. **Follow and read.** Filter jobs by status, review speaker labels and original timestamps, and search loaded transcript text.
3. **Export or continue with an agent.** Download Markdown, TXT, JSON, SRT, or VTT. Copy the job ID from a connected workspace for an MCP or SDK follow-up.

<details>
<summary>Mobile transcript reader</summary>

<br>
<img src="docs/assets/screenshots/reader-mobile-en.png" width="390" alt="Actual sample transcript reader at a 390-pixel mobile viewport, with export controls, a segment timeline, and speaker-labeled text">

The same responsive workspace, scrolled to the reader. Sample text is synthetic; no source audio is included.

</details>

**Running both services locally:** Vite forwards `/api` to `http://127.0.0.1:18080`. Browser uploads also need a reachable S3 endpoint and storage CORS. For deployment, the optional web container uses port **18081**. See the [web guide](web/README.md) for configuration, the upload review flow, deployment, and tests.

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

Give your agent a recording and keep a job ID you can return to. The agent can poll progress, read a time range, and request exports; the backend keeps working between tool calls.

```mermaid
flowchart LR
    File[Local recording] --> Upload[upload_local_audio]
    Upload --> Asset[asset_id]
    Asset --> Submit[submit_transcription]
    Submit --> Job[job_id]
    Job --> Read[read_transcript]
    Job --> Export[export_transcript]
```

The local bridge supplies `upload_local_audio`. Poll `get_transcription` until the job succeeds before reading or exporting; a remote-only client starts with an existing asset or job.

### Recipe: cloud backend, local recording

> Transcribe the meeting on my laptop. Prepare Markdown and SRT exports, and keep the job ID so I can return later.

Run a lightweight local MCP bridge to upload files to your cloud backend, or upload in the web workspace
and let a remote agent continue with the existing job. The backend owns the long-running work.

**[Follow the recipe →](docs/examples/cloud-backend-local-files.md)** — client configuration, upload flow,
example tool calls, and authenticated downloads. Includes the boundaries for cloud-hosted chat attachments.

### Connect a remote client

Use `http://localhost:18080/v1/mcp/` with `Authorization: Bearer YOUR_VOICE_INGEST_API_KEY`. Configure the URL and header using your client's HTTP MCP settings.

| Task | Tools |
| --- | --- |
| Discover models | `list_models` |
| Manage jobs | `submit_transcription`, `get_transcription`, `list_transcriptions`, `cancel_transcription`, `retry_transcription` |
| Read and export | `read_transcript`, `export_transcript` |

Submissions return durable business job IDs immediately. MCP Tasks support and a persistent MCP connection are not required. Transcript reads support pagination and time ranges to keep long recordings out of a single tool response.

`submit_transcription` only requires `asset_id`. MCP automatically deduplicates the same asset and
normalized options across reconnections, including completed jobs. An optional explicit
`idempotency_key` supports intentional new recognition; reuse it for retries of that request.
Use `retry_transcription` to retry a failed job. HTTP/SDK idempotency contracts are unchanged.

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
  "$VOICE_URL/v1/openapi.json" -o openapi.json
```

`/v1/docs` also requires authentication. `/v1/health/live` and `/v1/health/ready` are public process/readiness checks; `/v1/metrics` requires the service key.

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

The v1 speech framework implements file STT and complete-file TTS for a shared, trusted workspace. Phase 1 includes Aliyun adapters and explicit mock deployments. Realtime sessions, voice cloning, automatic text splitting, other vendors, local model hosting, multi-tenancy and knowledge-base ingestion remain out of scope. See the [phase record](docs/plans/phase-1-aliyun-stt-tts.md) for current acceptance evidence and quality/deployment limits.

| Document | Contents |
| --- | --- |
| [Web workspace](web/README.md) | Browser setup, upload review, storage CORS, and frontend checks |
| [Cloud backend + local recording](docs/examples/cloud-backend-local-files.md) | A complete MCP workflow with client configuration and exports |
| [Deployment](docs/deployment.md) | Configuration, private storage, HTTP/HTTPS, credentials, operations |
| [Architecture](docs/architecture.md) | Module boundaries, persistence, recovery, and tradeoffs |
| [Architecture decision](docs/decisions/0001-durable-capabilities.md) | Durable jobs and capability-oriented organization |
| [Acceptance record](docs/acceptance.md) | Tested behavior and remaining validation work (Chinese) |
| [Agent instructions](AGENTS.md) | Repository rules for contributors and coding agents |

## License

[MIT](LICENSE). You may use, modify, distribute, and use this project commercially,
provided you retain the copyright and license notice. Third-party dependencies and
cloud services remain subject to their own licenses and terms.
