"""Dedicated resources only. Never point these tests at an application database."""

import asyncio
import hashlib
import os
import shutil
import socket
import wave
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastmcp import Client
from pydantic import SecretStr
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from voice_ingest.client import AsyncVoiceClient
from voice_ingest.interfaces.http import create_app
from voice_ingest.jobs.worker import LeaseLost, Worker
from voice_ingest.media.probe import MediaProbe
from voice_ingest.media.service import UploadService
from voice_ingest.media.storage import S3Storage
from voice_ingest.providers.mock import MockProvider
from voice_ingest.runtime.database import Asset, Base, Job, SchedulerLock, now, uid
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import CreateTranscription
from voice_ingest.transcription.service import TranscriptionService

pytestmark = pytest.mark.integration


@pytest.fixture
async def real_env():
    url = os.environ.get("VOICE_TEST_DATABASE_URL")
    endpoint = os.environ.get("VOICE_TEST_S3_ENDPOINT")
    if not url or not endpoint:
        pytest.skip("Dedicated test PostgreSQL and S3 environment variables are required")
    if not url.split("?")[0].endswith("/voice_test"):
        pytest.fail("Integration database must be named voice_test")
    schema = "voice_test_" + uuid4().hex
    bootstrap = create_async_engine(url)
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        database_url=url,
        api_key=SecretStr("test-api-key"),
        s3_endpoint=endpoint,
        s3_public_endpoint=endpoint,
        s3_bucket=schema.replace("_", "-"),
        s3_access_key=SecretStr(os.environ["VOICE_TEST_S3_ACCESS_KEY"]),
        s3_secret_key=SecretStr(os.environ["VOICE_TEST_S3_SECRET_KEY"]),
        poll_seconds=0.1,
        enable_mcp=True,
        ffprobe_binary=os.getenv("VOICE_TEST_FFPROBE", "ffprobe"),
    )
    storage = S3Storage(settings)
    storage.internal.create_bucket(Bucket=storage.bucket)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions.begin() as session:
        session.add(SchedulerLock(id=1))
    provider = MockProvider()
    probe = MediaProbe(storage, settings.ffprobe_binary)
    env = SimpleNamespace(
        settings=settings,
        engine=engine,
        sessions=sessions,
        storage=storage,
        provider=provider,
        transcriptions=TranscriptionService(sessions, storage, settings),
        uploads=UploadService(sessions, storage),
    )
    env.worker = Worker(sessions, storage, provider, probe, settings)
    try:
        yield env
    finally:
        await storage.delete_prefix("")
        uploads = storage.internal.list_multipart_uploads(Bucket=storage.bucket).get("Uploads", [])
        for upload in uploads:
            storage.internal.abort_multipart_upload(
                Bucket=storage.bucket, Key=upload["Key"], UploadId=upload["UploadId"]
            )
        storage.internal.delete_bucket(Bucket=storage.bucket)
        await storage.close()
        await engine.dispose()
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


def recording(path: Path, seconds: int):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        second = b"\0" * 16000
        for _ in range(seconds):
            audio.writeframesraw(second)


async def finish(env, job_id):
    for _ in range(10):
        async with env.sessions.begin() as session:
            await session.execute(update(Job).where(Job.id == job_id).values(next_run_at=now()))
        await env.worker.tick()
        job = await env.transcriptions.get(job_id)
        if job.state == "succeeded":
            return job
        if job.state == "failed":
            pytest.fail(str(job.error))
    pytest.fail("Job did not complete")


async def test_postgres_concurrent_claim_fencing_and_idempotency(real_env):
    env = real_env
    asset_id = uid()
    async with env.sessions.begin() as session:
        session.add(
            Asset(
                id=asset_id,
                filename="a.wav",
                size=4,
                sha256=hashlib.sha256(b"test").hexdigest(),
                object_key=f"audio/{asset_id}/source",
                ready=True,
            )
        )
    request = CreateTranscription(asset_id=asset_id)
    duplicates = await asyncio.gather(
        *(env.transcriptions.create(request, "same-key") for _ in range(8))
    )
    assert len({job.id for job in duplicates}) == 1
    for i in range(4):
        await env.transcriptions.create(request, f"different-{i}")
    workers = [
        Worker(env.sessions, env.storage, env.provider, env.worker.probe, env.settings)
        for _ in range(6)
    ]
    claims = await asyncio.gather(*(worker.claim() for worker in workers))
    assert len([claim for claim in claims if claim]) == 2
    assert len({claim.id for claim in claims if claim}) == 2
    index = next(i for i, claim in enumerate(claims) if claim)
    claimed = claims[index]
    async with env.sessions.begin() as session:
        await session.execute(
            update(Job).where(Job.id == claimed.id).values(lease_until=now() - timedelta(seconds=1))
        )
    replacement = await env.worker.claim()
    assert replacement.id == claimed.id
    with pytest.raises(LeaseLost):
        await workers[index].checkpoint(claimed, "succeeded")


@pytest.mark.parametrize("seconds", [1800, 3600])
async def test_real_upload_probe_worker_and_http_mcp(real_env, tmp_path, seconds):
    env = real_env
    if not shutil.which(env.settings.ffprobe_binary):
        pytest.skip("ffprobe required for media integration")
    file = tmp_path / "meeting.wav"
    await asyncio.to_thread(recording, file, seconds)
    app = create_app(env.settings, env)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        if serving.done():
            await serving
        await asyncio.sleep(0.01)
    try:
        async with AsyncVoiceClient(f"http://127.0.0.1:{port}", "test-api-key") as sdk:
            asset = await sdk.upload(file, state_dir=tmp_path / "state")
            repeated = await sdk.upload(file, state_dir=tmp_path / "state")
            assert repeated.id == asset.id
            async with env.sessions() as session:
                saved = await session.get(Asset, asset.id)
                private_url = (
                    f"{env.settings.s3_public_endpoint}/{env.storage.bucket}/{saved.object_key}"
                )
                signed_url = env.storage.sign_download(saved.object_key)
            async with httpx.AsyncClient() as http:
                assert (await http.get(private_url)).status_code == 403
                async with http.stream("GET", signed_url) as response:
                    assert response.status_code == 200
            job = await sdk.submit(asset.id, idempotency_key="long-recording")
            await env.worker.tick()
            assert (await sdk.get(job.id)).state == "running"
            env.worker = Worker(
                env.sessions, env.storage, MockProvider(), env.worker.probe, env.settings
            )
            await finish(env, job.id)
            result = await sdk.result(job.id)
            assert result.duration_ms == seconds * 1000
            assert result.segments[-1].end_ms == seconds * 1000
            assert (await sdk.asset(asset.id)).media_info["sha256_verified"]
            assert b"WEBVTT" in await sdk.export(job.id, "vtt")
            async with Client(f"http://127.0.0.1:{port}/mcp/", auth="test-api-key") as mcp:
                response = await mcp.call_tool("get_transcription", {"job_id": job.id})
                assert response.structured_content["state"] == "succeeded"
    finally:
        server.should_exit = True
        await serving
        sock.close()
