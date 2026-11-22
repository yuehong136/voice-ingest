# Interview clip checklist

[简体中文](clip-checklist.zh-CN.md) · [Voice Ingest](../../README.md)

Use a checklist to find an exact quote in your editor. Each entry identifies the source version, provides the in and out timecodes, and gives a separate reason to consider the clip.

## Watch the sample

Open the finished checklist and the matching subtitles. To save either SRT from the GitHub file view, select **Raw** and save it as `.srt`. Both versions contain “We lowered the review time from nine hours to four.” Seek to `00:00:07,000` on the original, or `00:00:02,000` on the trim. [Checklist](../../skills/voice-ingest-clip-checklist/assets/example-checklist.md) · [Original SRT](../../skills/voice-ingest-clip-checklist/assets/interview-original.srt) · [Trimmed SRT](../../skills/voice-ingest-clip-checklist/assets/interview-trim-5s.srt)

Download and open the HTML in your browser, watch the short recording, or extract the ZIP for separate media, subtitles, and checklist. Both media versions use synthetic speech. [Offline example](https://github.com/yuehong136/voice-ingest/releases/download/v0.1.0-alpha.1/clip-demo.html) · [Recording](https://github.com/yuehong136/voice-ingest/releases/download/v0.1.0-alpha.1/clip-checklist-demo.mp4) · [Example ZIP](https://github.com/yuehong136/voice-ingest/releases/download/v0.1.0-alpha.1/voice-ingest-clip-demo.zip)

To verify the line in your editor, load the named file and set the time display to source time. The checklist's out is the end boundary. In Shotcut at 24 fps, the last included frame comes immediately before this boundary. Use the position, quote, and source version together when checking the cut.

## Use an SRT you already have

1. Download and extract the ZIP, then use your client's local Skill setup to load the [clip checklist Skill](../../skills/voice-ingest-clip-checklist/SKILL.md). [Skill ZIP](https://github.com/yuehong136/voice-ingest/releases/download/v0.1.0-alpha.1/voice-ingest-clip-checklist.zip)
2. Explicitly provide the SRT and the media filename/version or sequence name/revision it came from. Say whether the timestamps are media time or sequence time. If the client cannot read the file, use an approved attachment or paste the complete cue blocks. Use the [plain-text example](../../skills/voice-ingest-clip-checklist/assets/paste-example.md) to try this route.
3. Ask for exact quotes with both endpoints and a separate reason for each candidate. Seek to at least one quote in your own editor before using the cuts.

Copy this request after attaching the original SRT.

> Use the interview clip checklist Skill. I attached subtitles for `interview-original.mp4`, using media time. Find the measurable result. Give me that exact quote, its cue number, both timecodes, the source version, and a separate reason for the pick.

This route requires an agent that can read the supplied subtitles. The Voice Ingest server, MCP connection, and transcription key are optional. Check the input-handling policy of your chosen agent client before providing private subtitles. The Skill also includes a Python reader you can run locally to inspect the cue text and timing.

## Use a recording or an existing job

Start on [mock with a synthetic recording](../../README.md#quickstart) to try the upload, status lookup, and exports. Mock results are synthetic. For actual transcript text and timing, configure [Aliyun ASR](../../README.md#providers) with a regional DashScope key and a source mode the provider can reach. Submit only media you have permission to process. Cloud recognition may incur charges.

In Web, select a recording, wait for the upload to finish, and choose **Start transcription** after reviewing the settings. For an existing job, open it and choose **Copy for Agent**, or pass the job ID alone to the Skill. Clipboard fallback text contains the same ID and instructions. Set the service key in the [client's MCP configuration](../../README.md#connect-a-remote-client). The key, presigned URLs, and transcript text stay out of the handoff message. A client on another machine needs a backend address it can reach.

| What happens | What to do |
| --- | --- |
| Agent cannot authenticate or cannot find the job | Check the backend address, credentials, and job ID for that workspace. If MCP is unavailable, export JSON or SRT from Web using a session that can access the job and supply the file through an approved attachment. |
| The job is still processing | Keep the same ID and check its status later. Upload and transcription creation are separate operations. |
| The job needs attention after an uncertain provider response | Check the status and any provider receipt before explicitly retrying. The worker never automatically resubmits an uncertain request. Another submission can incur a second charge. |
| Timestamps are missing and SRT fails | Download JSON to keep the text and available timestamps. Ask the agent to flag unverified entries. If the SRT and media version disagree, get the matching subtitles before using the range. |

## Data and deletion

The configured backend keeps job state in PostgreSQL and stores audio and results in private S3. With Aliyun enabled, the worker submits a signed source URL or stages the file in Aliyun's temporary file service, depending on your settings. Attachments and reads through agent tools follow that agent client's data policy. Use synthetic files for a first run and keep credentials in your own configuration. [Architecture](../architecture.md) · [Provider configuration](../deployment.md#real-asr-from-a-local-browser)

Use `uv run voice-ingest jobs delete JOB_ID` to delete a job's results. The service retains an idempotency tombstone to avoid unintended re-creation. When the source is no longer in use, `uv run voice-ingest assets delete ASSET_ID` removes it. Confirm successful deletion and handle local downloads, backups, and provider-side copies according to their separate retention policies. [Recovery and retention](../deployment.md#recovery-and-monitoring) · [Deletion behavior](../operations/deployment-rehearsal.md#删除与恢复审查边界)
