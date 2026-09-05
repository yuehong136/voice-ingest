# Transcribe local recordings with a cloud backend

**English** · [简体中文](cloud-backend-local-files.zh-CN.md)

Keep Voice Ingest on your server and ask an agent to transcribe a recording on your laptop.
The agent coordinates the workflow through MCP; the file travels through HTTP/S3 upload.
You receive a durable job ID and can return to the transcript in another conversation or the web workspace.

> Transcribe `/Users/alex/Recordings/meeting.mp4`. You may use the configured paid ASR provider.
> When it finishes, prepare Markdown and SRT exports and give me the job ID.

This is an example prompt, not a recorded tool response. MP4 transcription extracts speech from its
audio track; it does not OCR slides or read embedded subtitles.

## Choose your entry point

| Where your agent runs | How the file reaches Voice Ingest | Setup |
| --- | --- | --- |
| On your computer, with local MCP process support | The local bridge uploads the file | Case A below |
| In a hosted chat product, with remote HTTP MCP support | Upload and submit in the web workspace, then use the agent on the existing job | Case B below |

An attachment in a chat is not automatically readable by MCP. The chat host must expose an accessible
file or implement an upload integration. Voice Ingest currently has no chat-specific attachment connector.

## Before you start

The operator deploys the API, worker, PostgreSQL and private S3 storage using the
[deployment guide](../deployment.md). In this example, `https://voice.example.com` is a placeholder
for the **API base URL**, and its remote MCP endpoint is `/mcp/`. If your frontend proxies the API
under `/api`, use the externally routed API base URL instead of assuming the frontend origin is the API.

- Configure the provider key on the backend. Give clients a **Voice Ingest workspace key** through their secret settings.
- Clients must reach both the API and the signed S3 upload endpoint. Browser uploads also require S3 CORS.
- With the default `signed_url` source mode, the ASR provider must reach signed S3 download URLs.
- A private bucket can have a public network endpoint: signed requests authorize object access.
- A local `localhost` S3 address is unreachable from the cloud provider. `temporary_upload` is an explicit local-evaluation option, not the production setup used here.

The workspace is shared by a trusted team; an API key does not create per-user storage or task isolation.

## Case A: a local MCP bridge uploads to your cloud backend

Install the lightweight client on the user's computer with Python 3.12 and uv:

```bash
git clone https://github.com/yuehong136/voice-ingest.git
cd voice-ingest
uv sync --frozen --extra mcp --extra cli --no-dev
```

No local database, S3 server, GPU or inbound port is needed. In a client supporting `mcpServers`, add:

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

Replace the executable path, API address, existing allowed directory and key. The JSON is illustrative;
use your client's configuration schema and secret handling. Repeat `--allow-dir` for additional directories.
The bridge resolves real paths and rejects files outside those directories, including symlink escapes.

```mermaid
sequenceDiagram
    participant Agent as Agent + local bridge
    participant API as Cloud API
    participant S3 as Private S3
    participant Worker as Cloud worker
    participant ASR as ASR provider
    Agent->>API: Create upload session
    API-->>Agent: Signed multipart upload URLs
    Agent->>S3: Upload file parts over HTTP
    Agent->>API: Complete upload
    API-->>Agent: asset_id
    Agent->>API: Submit transcription
    API-->>Agent: job_id immediately
    Worker->>ASR: Submit signed source URL
    ASR->>S3: Download recording
    Worker->>ASR: Poll and retrieve result
    Worker->>S3: Store results and exports
    Agent->>API: Query job and read transcript
```

The expected tool sequence is:

| Tool | Example input | What comes back |
| --- | --- | --- |
| `list_models` | `{}` | Configured model capabilities |
| `upload_local_audio` | `{"path":"/Users/alex/Recordings/meeting.mp4"}` | An asset whose `id` is the `asset_id` |
| `submit_transcription` | `{"asset_id":"ASSET_ID"}` | A job whose `id` is the `job_id` |
| `get_transcription` | `{"job_id":"JOB_ID"}` | Current durable status |
| `read_transcript` | `{"job_id":"JOB_ID","limit":50}` | A page of segments; follow `next_cursor` |
| `export_transcript` | `{"job_id":"JOB_ID","format":"markdown"}` | An authenticated API download path |

Use returned IDs rather than these placeholders. Read and export after `succeeded`; use `srt` for the
second export. MCP generates a stable key from the asset and normalized options when the optional
`idempotency_key` is omitted. Repeating the call after a lost response or reconnect returns the same
job, including completed jobs. Changed options create a different job; use an explicit fresh key only
for intentional new recognition with identical options, and reuse that key for network retries. Uploading alone
does not start recognition; submitting to a real provider may incur charges.

## Case B: browser upload, remote agent follow-up

1. Open the deployed web workspace and connect with the workspace key.
2. Upload the recording and submit transcription there.
3. Configure your hosted agent's HTTP MCP connection with `https://voice.example.com/mcp/` and the header `Authorization: Bearer YOUR_WORKSPACE_API_KEY`.
4. Ask the agent to use `list_transcriptions` to find the existing job, then inspect it with `get_transcription`. If several jobs match, identify the intended job before proceeding.

> Find my recently submitted transcription. Show its status and job ID. Once it succeeds,
> read the first five minutes and prepare a Markdown export. Use the existing job.

Remote MCP operates on managed assets and jobs; it cannot read `/Users/...` on your laptop or upload an
arbitrary remote URL. If you uploaded through the SDK/API without submitting, pass the returned `asset_id`
to `submit_transcription`. The web upload review also exposes this asset ID: choose **Transcribe later**
to hand it to an agent before recognition. If you clicked **Start transcription** in the web workspace,
use its existing job instead of submitting again. Pending upload setup stays in this tab; after a refresh,
re-select the same file to recover it.

## Return later and download the result

Closing the conversation does not cancel the backend job. In a later conversation, provide `job_id`
or use `list_transcriptions`. Automatic polling and notifications depend on the agent host; the server
does not independently send a new chat message when recognition finishes.

Read long transcripts in pages or request a time range using `start_ms` and `end_ms`.
`export_transcript` returns a path, not an attached file or a public download link. A client must download
it with the workspace Bearer token. Alternatively, use the authenticated web workspace or CLI:

```bash
# Set VOICE_API_KEY in your shell using your usual secret management.
export VOICE_URL=https://voice.example.com
uv run --no-sync voice-ingest export JOB_ID --format markdown --output meeting.md
uv run --no-sync voice-ingest export JOB_ID --format srt --output meeting.srt
```

Run these commands from the client checkout installed above. SRT/VTT require valid timestamps.
If the job enters `needs_attention`, inspect it before retrying: the provider might already have
accepted a billable request. Retrying is not a way to check progress.

For production reachability and deployment checks, see [deployment](../deployment.md).
For what has actually been tested, see [acceptance](../acceptance.md).
