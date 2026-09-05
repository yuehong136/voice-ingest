# Deployment and real-provider acceptance

## Independent deployment

Use `deploy/compose.yaml` with a dedicated project directory and `.env`. Its PostgreSQL is private to
the Compose network, its S3 data and database have separate project-owned volumes, and no MinIO
management console is published. It uses 18080 (API/MCP) and 19000 (S3), leaving 80/443 and the existing
knowledge-base ports alone. Verify these new ports are free before deploying.

The example pins a concrete MinIO image for reproducibility; `VOICE_MINIO_IMAGE` can select your
organization's maintained S3-compatible distribution. AWS S3 or existing S3 can be used by configuring
endpoints and credentials and removing the sample `s3`/`storage-init` services from an override. The
core requires multipart, presigned GET/PUT, HEAD, list and delete operations.

From the project root:

```bash
cp .env.example .env
# Edit the three credentials, source URL, provider and bind address as needed.
docker compose --env-file .env -f deploy/compose.yaml config --quiet
docker compose --env-file .env -f deploy/compose.yaml up -d --build
docker compose --env-file .env -f deploy/compose.yaml logs --tail 50 api worker
curl http://127.0.0.1:18080/health/ready
```

Choose a database password without URL-reserved characters in the sample Compose URL, or supply an
appropriately URL-encoded database URL in your own deployment configuration. Do not print a full
rendered Compose config into logs: it contains secrets. The sample defaults to mock recognition and
loopback binding so it cannot accidentally bill Aliyun or expose a development key.

For an IP-based pilot on the inspected server, set:

```dotenv
VOICE_BIND_ADDRESS=0.0.0.0
VOICE_S3_PUBLIC_ENDPOINT=http://203.0.113.10:19000
```

The server firewall/cloud security group must allow the intended upload and ASR download traffic.
An exposed port alone does not prove it is reachable from Aliyun. HTTP source URLs are supported by
Aliyun but are unencrypted, including their temporary signatures. Use HTTPS for confidential public
traffic and API credentials. An SSH tunnel can protect operator API access during an HTTP pilot;
Aliyun still needs the source download URL to be reachable independently of that tunnel.

No changes to the existing server were performed by this project's implementation. In particular,
existing knowledge-base PostgreSQL, MinIO, Nginx and 80/443 mappings are not reused automatically.

## HTTPS later

`deploy/Caddyfile.example` shows optional API and file domains. On this server 80/443 are already
reserved by the knowledge-base container. Integrating a shared edge requires a separately reviewed
change to that deployment; do not simply start another proxy on those ports. A separate IP/edge or
an existing proxy route is also possible. Ensure the S3 signature's host, path and query survive the
proxy unchanged. Change the public S3 endpoint **before generating** URLs; do not rewrite signed URLs.

## Aliyun acceptance

Set the same regional API key/endpoint pair and keep credentials on the backend:

```dotenv
VOICE_PROVIDER=aliyun
VOICE_ALIYUN_REGION=beijing
VOICE_ALIYUN_WORKSPACE_ID=your-workspace-id
VOICE_ALIYUN_API_KEY=your-regional-key
```

An empty workspace ID uses the documented legacy DashScope endpoint. No automatic fallback between
regions is performed. Default model: `qwen-audio-3.0-asr-flash-filetrans`; comparison model: `fun-asr`.
Context is limited to 400 characters to avoid silent vendor truncation. Diarization is opt-in and
limited to two hours. The service checks file size, SHA-256, format and duration before submission.

1. Use a non-sensitive short recording to verify the actual public signed GET URL and provider flow.
2. Transcribe representative 30-minute and one-hour recordings using the CLI with `--wait`.
3. Inspect opening, middle and final utterances, terminology, speaker labels and timestamp alignment.
4. Restart a worker after it records a provider task ID. Confirm the same attempt resumes without a
   second paid submission; inspect the persisted attempt ID and provider dashboard if needed.
5. Export JSON and subtitles and compare original-audio playback positions. Record actual processing
   time and any missing utterances. Do not infer full recognition quality from a successful job state.

Real ASR requires your regional credentials, reachable audio source and a recording you authorize
for cloud processing. Mock results are explicitly marked synthetic and never establish ASR accuracy.

## Recovery and monitoring

- `needs_attention`: inspect the provider dashboard and attempt history. Do not automatically retry.
  `jobs retry --acknowledge-duplicate-risk` explicitly accepts possible duplicate processing/charges.
- `remote_may_run=true`: cancellation/timeout did not prove inference stopped. Known IDs are polled
  until terminal; do not delete their audio while the provider may still read it.
- `upload_busy`: another completion is in progress. After a crashed API, wait up to five minutes and
  resume the same upload. Unfinished uploads are cleaned after 24 hours.
- `/health/live` checks the process; `/health/ready` checks schema/database and bucket reachability.
  Authenticated `/metrics` exposes current state/error counts, oldest active job age and recent worker
  heartbeats. Alert on missing workers, increasing queue age and result download failures.
- `jobs delete` removes all result objects for a job and retains a minimal job/idempotency tombstone;
  `assets delete` removes source audio when it is not in use. Completed files do not expire implicitly.
- Stop the stack with Compose `down`; do not add `-v` unless you intend to erase its stored data.

## Token Plan is a separate channel

This project currently implements the **regular DashScope asynchronous ASR API**, not Token Plan or
Coding Plan. Purchasing a subscription does not make a regular key's API usage consume that plan.
Token Plan uses a dedicated `sk-sp-` key and separate endpoint; these keys are rejected at startup
rather than silently sent to the regular ASR route. Key prefix checks are an early configuration
check, not authoritative account/billing verification.

Aliyun's current Token Plan documentation includes multimodal models, but its usage scope is
interactive supported coding/agent tools, not an automated shared application backend or batch
service. An interactive MCP invocation alone does not establish that a background backend qualifies.
There is no automatic attempt to bypass those distinctions or fall back to another billable channel.

References:
- https://help.aliyun.com/zh/model-studio/token-plan-team-quickstart
- https://help.aliyun.com/en/model-studio/token-plan-personal-overview
- https://help.aliyun.com/en/model-studio/token-plan-team-overview

A user-supplied key was checked during development with authenticated model-list requests: Token Plan
returned 401 `InvalidApiKey`; Beijing DashScope returned 200. This is a route/authentication observation,
not verification of the account's invoice, free quota or subscription balance. No key is saved here.

## Real ASR from a local browser

There are two different credentials:

- `VOICE_API_KEY` is your workspace access key. Enter this in the web connection dialog.
- `VOICE_ALIYUN_API_KEY` is the regional DashScope key. Keep it in the backend's private `.env`;
  never put it into the web bundle or use it as a workspace login credential.

The web app uses the same durable task service as CLI and SDK. Connecting the web app does not
change the backend provider: `VOICE_PROVIDER=mock` returns synthetic text, while
`VOICE_PROVIDER=aliyun` starts real, potentially billable recognition.

For local evaluation without a public S3 endpoint, configure:

```dotenv
VOICE_PROVIDER=aliyun
VOICE_ALIYUN_REGION=beijing
VOICE_ALIYUN_API_KEY=YOUR_REGIONAL_DASHSCOPE_KEY
VOICE_ALIYUN_SOURCE_MODE=temporary_upload
```

Restart both API and worker after editing `.env`. The browser still uploads to the project's private
S3 bucket; the worker verifies the file, streams a temporary copy to Aliyun's official upload service,
then submits the ASR job. Raw responses and exports are downloaded back to the project's private S3.
No public tunnel or externally accessible local MinIO is necessary for this evaluation mode.
The browser must still be able to reach the configured S3 URL and pass its CORS preflight.

Temporary staging happens in `preparing`, before the billable submission boundary. A staging failure
can retry; an uncertain ASR submission still becomes `needs_attention` and never silently resubmits.
The source mode is captured with each provider attempt. Upload clients do not forward the DashScope
API key to OSS. Files are streamed via bounded buffers and temporary disk files, with worker heartbeats
remaining active during staging.

**Production uses `VOICE_ALIYUN_SOURCE_MODE=signed_url` (the default)** and a stable, provider-reachable
S3 origin. Aliyun documents its temporary URLs as valid for 48 hours and explicitly excludes this
upload facility from production/high-concurrency/load testing. See the
[official API source-file requirements](https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-http-api).
Do not treat a successful temporary-upload run as public S3 or production deployment acceptance.
