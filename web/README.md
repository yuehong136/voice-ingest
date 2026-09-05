# Voice Ingest Web

An English/Chinese transcription workspace for the existing API. The entry screen connects to your real workspace; synthetic sample transcripts are available through an explicit preview action.

## Run locally

Use Node.js 24 LTS (minimum 22.12) and npm. From `web/`:

```sh
npm ci
npm run dev
```

Open http://127.0.0.1:5174. Demo mode needs no backend or credentials. For actual jobs, start the API/worker/storage stack first. Vite forwards `/api` to `http://127.0.0.1:18080`; override the target with `VOICE_API_TARGET` when starting Vite. Click **Connect backend**, then enter `VOICE_API_KEY` in the **Workspace access key** field. Aliyun credentials stay on the backend.

## Behavior

- React 19, Vite 8, TypeScript 7 and TanStack Query 5; exact versions are in `package-lock.json`.
- Service keys stay in memory. Reloading requires reconnecting. Audio and transcripts are never persisted by the frontend.
- Upload and recognition are separate actions: **Upload file**, then review settings and **Start transcription**. Uploading alone never starts ASR.
- **Transcribe later** keeps one pending file in this tab. Reopen **Continue setup** to submit, or select the displayed asset ID for an agent. After reloading, reconnect and re-select the same file to recover its completed upload; this is not a server-wide asset library.
- Filter loaded jobs by processing, ready or attention status. Task details expose asset/job IDs and submission time; copy the job ID for MCP follow-up.
- A worker computes SHA-256 in 2 MiB chunks. Upload uses four concurrent 16 MiB parts and refreshes part signatures on rejected requests.
- Re-select the same file to resume. Browser storage holds hashed workspace/file identity, upload IDs and submission idempotency keys. Disabling storage disables durable browser resume.
- Cancel during upload pauses the client operation. Incomplete uploads expire according to backend policy. Submitted jobs survive closing the browser.
- Live text is fetched in pages of 50 segments. Search applies to loaded text only. Exports retrieve the entire backend result.
- Local playback is available for audio uploaded in the current tab; source download for older jobs is not exposed by the backend API.
- This first web iteration handles one upload at a time; CLI batch workflows remain available.

### Customer walkthrough

Connect the workspace, upload a recording, and show the completed-upload confirmation before starting
recognition. Explain the model/language/speaker settings, then start the job. Review its status and
original timestamps, search loaded text, and export Markdown or subtitles. Use **Task details** to
continue the same job with an agent. For a walkthrough without cloud charges, use the explicitly
labeled sample transcript or deploy with the mock provider. Do not present synthetic text as ASR output.

## S3 browser access

File parts go directly to presigned S3 URLs, without the service authorization header. The S3 origin must be reachable from the browser and permit CORS `PUT` from the web origin. AWS S3 example:

```json
[
  {
    "AllowedOrigins": ["https://voice.example.com"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["*"],
    "MaxAgeSeconds": 3600
  }
]
```

MinIO has its own deployment-level CORS configuration; verify OPTIONS/PUT with your distribution. Do not make the bucket public. Serve S3 over HTTPS when the UI is HTTPS, or browsers will block mixed content. Do not rewrite the host of a presigned URL.

## Deployment

From the repository root:

```sh
docker compose --env-file .env -f deploy/compose.yaml -f deploy/compose.web.yaml up -d --build
```

The optional web container listens on local port **18081**. Nginx serves the built SPA and proxies `/api` to the API on the internal network, so backend API CORS is not necessary. No keys are baked into the bundle. Use a TLS reverse proxy for public access. Full Compose deployment is a separate acceptance step.

## Checks and generated contracts

```sh
npm run check
npm run build
npm test
```

Browser tests default to installed Google Chrome. On CI, install it with `npx playwright install --with-deps chrome`, or configure `PLAYWRIGHT_CHANNEL` for a supported installed channel. Tests cover sample interactions, mobile overflow, auth errors, upload headers, idempotency and uncertain retry acknowledgement. Tracing is disabled to avoid capturing credentials or transcripts.

API types are generated from FastAPI's OpenAPI schema without connecting to services. For regeneration, install Python server dependencies from the project root, then run:

```sh
npm ci --prefix tools
npm run types:generate
```

The OpenAPI generator currently requires TypeScript 5, so its dependencies live in `tools/`. Application compilation uses TypeScript 7 without peer-dependency overrides. Commit the generated types when backend contracts change.

## Switch from mock to real recognition

Set `VOICE_PROVIDER=aliyun` and the regional `VOICE_ALIYUN_API_KEY` in the backend `.env`, then restart both API and worker. Enter only `VOICE_API_KEY` in the browser. The cloud-provider banner confirms which mode is active; a successful workspace connection alone is not a provider credential check.

For local evaluation without public storage, also set `VOICE_ALIYUN_SOURCE_MODE=temporary_upload`. The worker stages files through Aliyun’s official temporary upload service; production keeps `signed_url`. See [backend configuration](../docs/deployment.md#real-asr-from-a-local-browser).

Routine Playwright tests remain cloud-free. Real ASR browser acceptance requires explicit authorization and is recorded separately; never point the automatic mock-backend test at a billable provider.
