import hashlib

import httpx
import pytest
from conftest import upload_transport
from fastmcp import Client
from fastmcp.exceptions import ToolError
from test_jobs import finish

from voice_ingest.client import AsyncVoiceClient
from voice_ingest.interfaces.http import create_app
from voice_ingest.interfaces.local_mcp import allowed_file
from voice_ingest.interfaces.mcp import create_mcp
from voice_ingest.media.contracts import CreateUpload
from voice_ingest.transcription.contracts import CreateTranscription, DomainError


async def test_sdk_upload_and_all_surfaces(env, tmp_path):
    app = create_app(env.settings, env)
    async with AsyncVoiceClient(
        "http://test",
        "test-api-key",
        transport=httpx.ASGITransport(app),
        upload_transport=upload_transport(env),
    ) as sdk:
        file = tmp_path / "meeting.wav"
        file.write_bytes(b"recording" * 100)
        asset = await sdk.upload(file, state_dir=tmp_path / "cache")
        repeated = await sdk.upload(file, state_dir=tmp_path / "cache")
        assert repeated.id == asset.id
        job = await sdk.submit(asset.id, idempotency_key="sdk-job")
        assert job.state == "queued"
        await finish(env, job.id)
        result = await sdk.result(job.id)
        assert result.segments[-1].end_ms == 3_600_000
        first = await sdk.read(job.id, limit=1)
        second = await sdk.read(job.id, cursor=first.next_cursor, limit=1)
        assert first.segments != second.segments
        for format in ("json", "txt", "markdown", "srt", "vtt"):
            assert await sdk.export(job.id, format)
        async with Client(create_mcp(env.transcriptions)) as mcp:
            tools = await mcp.list_tools()
            assert len(tools) == 8
            response = await mcp.call_tool("get_transcription", {"job_id": job.id})
            assert response.structured_content["id"] == job.id
            page = await mcp.call_tool("read_transcript", {"job_id": job.id, "limit": 1})
            assert len(page.structured_content["segments"]) == 1


async def test_auth_validation_and_nonblocking_submit(env, asset):
    app = create_app(env.settings, env)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as http:
        unauthorized = await http.get("/v1/models")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["request_id"]
        assert (await http.get("/health/live")).status_code == 200
        http.headers["Authorization"] = "Bearer test-api-key"
        invalid = await http.post("/v1/transcriptions", json={"bad": "sensitive input"})
        assert invalid.status_code == 422 and "sensitive input" not in invalid.text
        response = await http.post(
            "/v1/transcriptions", json={"asset_id": asset}, headers={"Idempotency-Key": "http"}
        )
        assert response.status_code == 202
        assert response.json()["state"] == "queued"


async def test_wait_cancellation_does_not_cancel_job(env, asset):
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "wait")
    app = create_app(env.settings, env)
    async with AsyncVoiceClient(
        "http://test", "test-api-key", transport=httpx.ASGITransport(app)
    ) as sdk:
        with pytest.raises(TimeoutError):
            await sdk.wait(job.id, timeout=0.05, interval=0.01)
    assert (await env.transcriptions.get(job.id)).state == "queued"


async def test_closed_upload_and_incomplete_recovery(env):
    request = CreateUpload(filename="a.wav", size=4, sha256=hashlib.sha256(b"test").hexdigest())
    upload = await env.uploads.create(request)
    with pytest.raises(DomainError, match="expected file parts"):
        await env.uploads.complete(upload.id)
    assert (await env.uploads.get(upload.id)).state == "uploading"
    with pytest.raises(DomainError, match="outside this file"):
        await env.uploads.sign(upload.id, 2)
    await env.uploads.abort(upload.id)
    with pytest.raises(DomainError, match="closed"):
        await env.uploads.sign(upload.id, 1)


def test_local_mcp_blocks_symlink_escape(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.wav"
    outside.write_bytes(b"private")
    (allowed / "link.wav").symlink_to(outside)
    with pytest.raises(DomainError, match="allowed directory"):
        allowed_file(str(allowed / "link.wav"), [allowed])


async def test_sdk_changed_file_gets_new_asset(env, tmp_path):
    app = create_app(env.settings, env)
    async with AsyncVoiceClient(
        "http://test",
        "test-api-key",
        transport=httpx.ASGITransport(app),
        upload_transport=upload_transport(env),
    ) as sdk:
        file = tmp_path / "meeting.wav"
        file.write_bytes(b"one")
        first = await sdk.upload(file, state_dir=tmp_path / "cache")
        file.write_bytes(b"two")
        second = await sdk.upload(file, state_dir=tmp_path / "cache")
        assert first.id != second.id


async def test_mcp_default_submission_survives_reconnect_and_local_bridge(env, asset, tmp_path):
    from voice_ingest.interfaces.local_mcp import create_local_mcp
    from voice_ingest.transcription.contracts import TranscriptionOptions

    async with Client(create_mcp(env.transcriptions)) as remote:
        tool = next(t for t in await remote.list_tools() if t.name == "submit_transcription")
        assert tool.input_schema["required"] == ["asset_id"]
        first = await remote.call_tool("submit_transcription", {"asset_id": asset})
        job_id = first.structured_content["id"]
    await finish(env, job_id)
    async with Client(create_mcp(env.transcriptions)) as remote:
        repeated = await remote.call_tool(
            "submit_transcription",
            {"asset_id": asset, "options": TranscriptionOptions().model_dump()},
        )
        assert repeated.structured_content["id"] == job_id
        assert repeated.structured_content["state"] == "succeeded"
        changed = await remote.call_tool(
            "submit_transcription", {"asset_id": asset, "options": {"language_hints": ["en"]}}
        )
        assert changed.structured_content["id"] != job_id

    sdk = AsyncVoiceClient(
        "http://test", "test-api-key", transport=httpx.ASGITransport(create_app(env.settings, env))
    )
    async with Client(create_local_mcp(sdk, [tmp_path])) as local:
        repeated = await local.call_tool("submit_transcription", {"asset_id": asset})
        assert repeated.structured_content["id"] == job_id


async def test_mcp_explicit_keys_retain_conflicts_and_reject_empty_keys(env, asset):
    async with Client(create_mcp(env.transcriptions)) as mcp:
        args = {"asset_id": asset, "idempotency_key": "intentional-new-recognition"}
        first = await mcp.call_tool("submit_transcription", args)
        repeated = await mcp.call_tool("submit_transcription", args)
        assert first.structured_content["id"] == repeated.structured_content["id"]
        automatic = await mcp.call_tool("submit_transcription", {"asset_id": asset})
        assert automatic.structured_content["id"] != first.structured_content["id"]
        with pytest.raises(ToolError, match="different parameters"):
            await mcp.call_tool(
                "submit_transcription", {**args, "options": {"language_hints": ["en"]}}
            )
        with pytest.raises(ToolError):
            await mcp.call_tool("submit_transcription", {**args, "idempotency_key": ""})
